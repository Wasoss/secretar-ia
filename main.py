"""
Secretar-IA - Asistente personal inteligente para Telegram.
Versión moderna con arquitectura clean, servicios desacoplados e IA enriquecida.

Punto de entrada principal - Configura y ejecuta el bot.
"""
import os
import asyncio
import datetime
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode

from config.settings import settings
from config.logging import configure_logging, get_logger
from infrastructure.di.container import initialize_container, close_container, get_container
from handlers import (
    # Basic commands
    start, ajuda, status, ping, test_sistema,
    # Calendar commands
    calendar_status,
    # Agenda commands
    ver_notas, ver_hoy, ver_hoy_corto, ver_semana, buscar, filtrar_tag, ver_pendientes,
    # Template commands
    ver_plantillas,
    # Objective/Review commands
    ver_objetivos, ver_revision,
    # Message handlers
    recibir_texto, recibir_audio,
    # Callback handlers
    callback_completar,
    # Job handlers
    enviar_resumen_diario, apply_daily_template_job, send_evening_reminder_job,
    send_weekly_review_job, keep_alive_db_job,
)

configure_logging()
logger = get_logger(__name__)

ZONA_HORARIA = settings.tz


# --- SERVIDOR WEB PARA RENDER (HEALTH CHECK) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ["/", "/health", "/healthz"]:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "service": "secretar-ia"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Silenciar logs del health check
        pass


def iniciar_servidor_web():
    """Inicia servidor HTTP para health checks de Render."""
    puerto = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", puerto), HealthCheckHandler)
    logger.info("health_check_server_started", port=puerto)
    server.serve_forever()


# --- STARTUP / SHUTDOWN ---
async def post_init(application: Application):
    """Inicialización post-arranque: DB, servicios, jobs."""
    logger.info("application_starting")

    # Inicializar container (DB + servicios)
    await initialize_container()

    # Registrar jobs
    await _register_jobs(application)

    logger.info("application_ready")


async def _register_jobs(application: Application):
    """Registra todos los jobs programados."""
    # Job diario a las 6:30 AM - Aplicar plantilla diaria
    hora_plantilla = datetime.time(hour=6, minute=30, tzinfo=ZONA_HORARIA)
    application.job_queue.run_daily(
        apply_daily_template_job,
        time=hora_plantilla,
        name="daily_template"
    )

    # Job diario a las 6:50 AM (resumen matutino)
    hora_envio = datetime.time(hour=6, minute=50, tzinfo=ZONA_HORARIA)
    application.job_queue.run_daily(enviar_resumen_diario, time=hora_envio)

    # Job diario a las 18:00 (recordatorio vespertino)
    hora_vespertino = datetime.time(hour=18, minute=0, tzinfo=ZONA_HORARIA)
    application.job_queue.run_daily(
        send_evening_reminder_job,
        time=hora_vespertino
    )

    # Job semanal: Domingo 10:00 AM - Revisión semanal
    from datetime import time
    hora_revision = time(hour=10, minute=0, tzinfo=ZONA_HORARIA)
    application.job_queue.run_daily(
        send_weekly_review_job,
        time=hora_revision,
        days=(6,)  # Domingo = 6 (0=Lunes, 6=Domingo)
    )

    # Keep-alive: cada 5 min hace query simple para evitar spin-down en Render free tier
    application.job_queue.run_repeating(
        keep_alive_db_job,
        interval=300,  # 5 minutos
        first=10,
        name="keep_alive_db"
    )

    logger.info("jobs_registered", jobs=[
        "daily_template", "morning_summary", "evening_reminder",
        "weekly_review", "keep_alive_db"
    ])


async def post_shutdown(application: Application):
    """Limpieza al apagar."""
    logger.info("application_shutting_down")
    await close_container()


# --- ERROR HANDLER ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler."""
    error = context.error
    error_msg = str(error)

    # Manejar Conflict específicamente (dos instancias del bot)
    if "Conflict: terminated by other getUpdates request" in error_msg or "ConflictError" in type(error).__name__:
        logger.error("bot_conflict", error=error_msg)
        if update and hasattr(update, 'message') and update.message:
            try:
                await update.message.reply_text(
                    "⚠️ <b>Conflict detectado</b>: Hay otra instancia del bot corriendo.\n"
                    "Detén la instancia local o hacé <i>Clear build cache & deploy</i> en Render.",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass  # Si falla el envío, al menos se logueó
        return

    logger.error("bot_error", error=error_msg, exc_info=context.error)


# --- COMMAND HANDLER FOR /aplicar_plantilla ---
async def aplicar_plantilla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando manual para aplicar plantilla: /aplicar_plantilla"""
    from handlers.base import require_auth

    if not await require_auth(update):
        return

    from infrastructure.di.container import get_container
    container = get_container()
    services = await container.get_all_services()
    weekly_planning_service = services['weekly_planning_service']

    task_id = await weekly_planning_service.apply_daily_template(settings.mi_telegram_id)
    if task_id:
        await update.message.reply_text(
            f"✅ Plantilla diaria aplicada (Task ID: {task_id})",
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            "ℹ️ No hay plantilla activa o ya se aplicó hoy.",
            parse_mode=ParseMode.HTML
        )


async def resumen_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /resumen - Resumen matutino manual."""
    from handlers.base import require_auth

    if not await require_auth(update):
        return

    from infrastructure.di.container import get_container
    container = get_container()
    services = await container.get_all_services()
    summary_service = services['summary_service']

    await summary_service.send_daily_summary(context.bot, settings.mi_telegram_id)


def main():
    """Punto de entrada principal."""
    app = Application.builder().token(settings.telegram_token).build()

    # --- Command Handlers ---
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ayuda", ajuda))
    app.add_handler(CommandHandler("test", test_sistema))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("calendar_status", calendar_status))
    app.add_handler(CommandHandler("notas", ver_notas))
    app.add_handler(CommandHandler("hoy", ver_hoy))
    app.add_handler(CommandHandler("hoy_corto", ver_hoy_corto))
    app.add_handler(CommandHandler("semana", ver_semana))
    app.add_handler(CommandHandler("buscar", buscar))
    app.add_handler(CommandHandler("tag", filtrar_tag))
    app.add_handler(CommandHandler(["pendientes", "tareas"], ver_pendientes))
    # /plantillas, /planillas, /planilla (singular y plural)
    app.add_handler(CommandHandler(["plantillas", "planillas", "planilla"], ver_plantillas))
    # /objetivos, /metas, /meta (singular y plural)
    app.add_handler(CommandHandler(["objetivos", "metas", "meta"], ver_objetivos))
    app.add_handler(CommandHandler("revision", ver_revision))
    app.add_handler(CommandHandler("resumen", resumen_manual))
    app.add_handler(CommandHandler("aplicar_plantilla", aplicar_plantilla))

    # --- Message Handlers ---
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_texto))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.Document.AUDIO, recibir_audio))

    # --- Callback Query Handlers ---
    app.add_handler(CallbackQueryHandler(callback_completar, pattern="^(complete_|delete_|subtask_)"))

    # --- Error Handler ---
    app.add_error_handler(error_handler)

    # --- Lifecycle Hooks ---
    app.post_init = post_init
    app.post_shutdown = post_shutdown

    # --- Iniciar servidor web para health checks en hilo separado ---
    threading.Thread(target=iniciar_servidor_web, daemon=True).start()

    logger.info("bot_starting_polling")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()