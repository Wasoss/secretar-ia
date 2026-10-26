"""
Secretar-IA - Bot de Telegram personal con IA.

Arquitectura limpia:
- config: Settings centralizadas y logging
- infrastructure: Database pool, repositories, external APIs
- application: Services y use cases
- interfaces: Telegram handlers
"""
import os
import datetime
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode

# Cargar .env temprano (antes de settings para que pydantic lo lea)
load_dotenv()

# Configuración y logging (validan env vars al importar)
from config.settings import settings
from config.logging import get_logger, logger

# Infraestructura
from infrastructure.database.connection import get_pool, close_pool, init_db
from infrastructure.database.repositories.task_repo import TaskRepository, TaskType, TaskStatus
from infrastructure.database.repositories.credential_repo import CredentialRepository

# Servicios de aplicación (se crearán después)
from application.services.calendar_service import CalendarService
from application.services.reminder_service import ReminderService
from application.services.summary_service import SummaryService
from application.services.ai_service import AIService

# ============================================================
# CONSTANTES Y UTILIDADES
# ============================================================

# Prefijos de callback data para evitar colisiones
CALLBACK_COMPLETE = "complete_"
CALLBACK_DELETE_NOTE = "delete_note_"

# Zona horaria única desde config
ZONA_HORARIA = settings.tz

# ============================================================
# SERVIDOR HEALTH CHECK PARA RENDER
# ============================================================

class HealthCheckHandler(BaseHTTPRequestHandler):
    """Handler HTTP para health checks de Render."""

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "healthy", "service": "secretar-ia"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Silenciar logs del servidor HTTP
        pass


def start_health_server():
    """Inicia servidor HTTP para health checks en puerto configurado."""
    port = settings.port
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logger.info("health_server_started", port=port)
    server.serve_forever()


# ============================================================
# FORMATO Y SEGURIDAD
# ============================================================

def format_fecha_arg(fecha_str: str | None) -> str:
    """Formatea fecha ISO a formato argentino DD/MM/YYYY HH:MM."""
    if not fecha_str:
        return ""
    try:
        # Manejar tanto string ISO como datetime
        if isinstance(fecha_str, datetime.datetime):
            dt = fecha_str
        else:
            # Limpiar string ISO (puede venir con 'T' o espacio)
            clean = fecha_str.replace("T", " ")[:19]
            dt = datetime.datetime.fromisoformat(clean)
        # Asegurar timezone aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZONA_HORARIA)
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception as e:
        logger.warning("date_format_failed", fecha_str=fecha_str, error=str(e))
        return str(fecha_str)


async def verify_user(update: Update) -> bool:
    """Verifica que el usuario esté autorizado."""
    chat_id = str(update.effective_chat.id)
    if chat_id != settings.mi_telegram_id:
        logger.warning("unauthorized_access_attempt", chat_id=chat_id)
        await update.message.reply_text(
            "⛔ Acceso denegado. No estás autorizado para usar este bot."
        )
        return False
    return True


# ============================================================
# SERVICIOS (Inicialización lazy para evitar imports circulares)
# ============================================================

_ai_service: AIService | None = None
_calendar_service: CalendarService | None = None
_reminder_service: ReminderService | None = None
_summary_service: SummaryService | None = None


def get_ai_service() -> AIService:
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service


def get_calendar_service() -> CalendarService:
    global _calendar_service
    if _calendar_service is None:
        _calendar_service = CalendarService()
    return _calendar_service


def get_reminder_service() -> ReminderService:
    global _reminder_service
    if _reminder_service is None:
        _reminder_service = ReminderService()
    return _reminder_service


def get_summary_service() -> SummaryService:
    global _summary_service
    if _summary_service is None:
        pool = get_pool()  # type: ignore
        task_repo = TaskRepository(pool)
        _summary_service = SummaryService(task_repo, get_calendar_service())
    return _summary_service


# ============================================================
# HANDLERS DE TELEGRAM
# ============================================================

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start - Inicializa el bot."""
    if not await verify_user(update):
        return

    chat_id = str(update.message.chat_id)
    # Guardar chat_id para jobs (recordatorios, resumen diario)
    context.job_queue.run_once(save_chat_id, 1, data=chat_id)

    await update.message.reply_text(
        "Hola. Soy tu Secretar-IA. Ya puedo gestionar tu agenda, "
        "alarmas y notas de forma segura en la nube."
    )


async def save_chat_id(context: ContextTypes.DEFAULT_TYPE):
    """Job para guardar chat_id en bot_data."""
    context.bot_data["chat_id"] = context.job.data


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ayuda - Muestra guía de uso."""
    if not await verify_user(update):
        return

    texto = (
        "🤖 <b>Guía de Funciones de Secretar-IA</b>\n\n"
        "• 📅 <b>Eventos:</b> Decí o escribí citas "
        "(ej. <i>'Reunión el martes a las 15hs'</i>) "
        "para guardarlas en Google Calendar.\n"
        "• ⏰ <b>Recordatorios:</b> Programá alarmas "
        "(ej. <i>'Recordame llamar a mamá a las 18hs'</i>).\n"
        "• 📔 <b>Notas:</b> Guardá información sin fecha "
        "(ej. <i>'Anotá la clave del wifi es 1234'</i>).\n"
        "• 📋 <b>Comandos disponibles:</b>\n"
        "  /resumen - Ver tareas y eventos próximos.\n"
        "  /notas - Consultar tus notas guardadas.\n"
        "  /ayuda - Muestra esta guía.\n"
        "  /test - Verifica el estado del sistema.\n"
        "• 🗑️ <b>Gestión:</b> Decí <i>'deshacer'</i> para borrar la última "
        "carga, o <i>'borrar todo lo del 25 de octubre'</i> para limpiar una fecha."
    )
    await update.message.reply_text(texto, parse_mode=ParseMode.HTML)


async def summary_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /resumen - Muestra resumen diario."""
    if not await verify_user(update):
        return
    await send_daily_summary(context)


async def notes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /notas - Muestra notas guardadas."""
    if not await verify_user(update):
        return

    chat_id = str(update.message.chat_id)
    pool = await get_pool()
    task_repo = TaskRepository(pool)
    notes = await task_repo.get_notes(chat_id)

    if not notes:
        await update.message.reply_text("📔 No tenés notas guardadas actualmente.")
        return

    mensaje = "📔 <b>Tus Notas guardadas:</b>\n\n"
    botones = []
    for nota in notes:
        mensaje += f"○ {nota.detalles}\n"
        botones.append([
            InlineKeyboardButton(
                f"❌ Borrar: {nota.detalles[:20]}",
                callback_data=f"{CALLBACK_DELETE_NOTE}{nota.id}"
            )
        ])

    teclado = InlineKeyboardMarkup(botones)
    await update.message.reply_text(
        text=mensaje,
        reply_markup=teclado,
        parse_mode=ParseMode.HTML
    )


async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /test - Diagnóstico del sistema."""
    if not await verify_user(update):
        return

    chat_id = str(update.effective_chat.id)
    pool = await get_pool()
    task_repo = TaskRepository(pool)

    try:
        # Test BD
        pending = await task_repo.get_pending(chat_id)
        # Test Calendar
        calendar = get_calendar_service()
        events = await calendar.get_upcoming_events()
        # Test AI
        ai = get_ai_service()
        ai_status = "Activo" if ai.is_available() else "No disponible"

        resultado = (
            "🧪 <b>Diagnóstico del Sistema:</b>\n\n"
            "✅ Base de datos (Neon.tech): Conectada\n"
            f"   └ Tareas/Notas pendientes: {len(pending)}\n"
            "✅ Google Calendar: Conectado\n"
            f"   └ Próximos eventos sincronizados: {len(events)}\n"
            f"✅ Motor de IA (Groq): {ai_status}"
        )
        await update.message.reply_text(resultado, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("system_test_failed", error=str(e), exc_info=True)
        await update.message.reply_text(
            f"❌ Error en el test del sistema:\n<code>{e}</code>",
            parse_mode=ParseMode.HTML
        )


async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler para mensajes de texto."""
    await process_request(update, context, update.message.text)


async def receive_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler para mensajes de voz."""
    if not await verify_user(update):
        return

    voice = update.message.voice
    if not voice:
        return

    # Descargar audio a archivo temporal (cleanup automático)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        file = await voice.get_file()
        await file.download_to_drive(tmp_path)

        ai = get_ai_service()
        transcription = await ai.transcribe_audio(tmp_path)

        if transcription:
            await process_request(update, context, transcription)
        else:
            await update.message.reply_text(
                "No pude transcribir el audio. Probá de nuevo o escribí el mensaje."
            )
    except Exception as e:
        logger.error("audio_processing_failed", error=str(e), exc_info=True)
        await update.message.reply_text("Error procesando el audio. Intentá de nuevo.")
    finally:
        # Cleanup garantizado
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler para callbacks de botones inline."""
    query = update.callback_query
    if not query or not query.data:
        return

    # Verificar autorización
    if str(query.message.chat_id) != settings.mi_telegram_id:
        await query.answer("No autorizado", show_alert=True)
        return

    data = query.data
    pool = await get_pool()
    task_repo = TaskRepository(pool)

    # Completar tarea/recordatorio
    if data.startswith(CALLBACK_COMPLETE):
        task_id_str = data[len(CALLBACK_COMPLETE):]
        try:
            task_id = int(task_id_str)
            success = await task_repo.complete(task_id)
            if success:
                await query.answer("¡Acción completada! ✅")
                await refresh_keyboard(query, task_id)
            else:
                await query.answer("Ya estaba completada o no existe", show_alert=True)
        except ValueError:
            logger.error("invalid_callback_task_id", data=data)
            await query.answer("Error: ID inválido", show_alert=True)

    # Borrar nota
    elif data.startswith(CALLBACK_DELETE_NOTE):
        task_id_str = data[len(CALLBACK_DELETE_NOTE):]
        try:
            task_id = int(task_id_str)
            success = await task_repo.delete_by_id(task_id)
            if success:
                await query.answer("Nota eliminada 🗑️")
                await refresh_keyboard(query, task_id)
            else:
                await query.answer("No se encontró la nota", show_alert=True)
        except ValueError:
            logger.error("invalid_callback_note_id", data=data)
            await query.answer("Error: ID inválido", show_alert=True)


async def refresh_keyboard(query, completed_task_id: int):
    """Actualiza el teclado inline removiendo el botón completado."""
    try:
        if not query.message.reply_markup:
            return

        keyboard = query.message.reply_markup.inline_keyboard
        new_keyboard = [
            [btn for btn in row if btn.callback_data != f"{CALLBACK_COMPLETE}{completed_task_id}"
             and btn.callback_data != f"{CALLBACK_DELETE_NOTE}{completed_task_id}"]
            for row in keyboard
        ]
        # Filtrar filas vacías
        new_keyboard = [row for row in new_keyboard if row]

        if new_keyboard:
            await query.edit_message_reply_markup(InlineKeyboardMarkup(new_keyboard))
        else:
            await query.edit_message_text("¡Todas las tareas de esta lista están listas! 🎉")
    except Exception as e:
        logger.warning("keyboard_refresh_failed", error=str(e))


# ============================================================
# LÓGICA DE NEGOCIO - PROCESAMIENTO DE PETICIONES
# ============================================================

async def process_request(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_text: str
):
    """Procesa una petición del usuario (texto o voz transcrita)."""
    if not await verify_user(update):
        return

    chat_id = str(update.message.chat_id)
    pool = await get_pool()
    task_repo = TaskRepository(pool)

    # Clasificar intención con IA
    ai = get_ai_service()
    result = await ai.classify_intent(user_text)

    action = result.get("accion", "ERROR")
    details = result.get("detalles", "")
    fecha_hora_str = result.get("fecha_hora")

    logger.info("intent_classified", action=action, details=details[:50], fecha_hora=fecha_hora_str)

    # Parsear fecha si existe
    fecha_hora = None
    if fecha_hora_str and fecha_hora_str.lower() != "null":
        try:
            # La IA devuelve formato "YYYY-MM-DD HH:MM" en zona local
            naive_dt = datetime.datetime.strptime(fecha_hora_str, "%Y-%m-%d %H:%M")
            fecha_hora = naive_dt.replace(tzinfo=ZONA_HORARIA)
        except ValueError as e:
            logger.warning("date_parse_failed", fecha_hora_str=fecha_hora_str, error=str(e))

    # Manejar acciones especiales
    if action == "RECHAZADO_GASTOS":
        await update.message.reply_text(
            f"No gestiono finanzas. Registrá esto en tu otro bot: {details}"
        )
        return

    if action == "CONVERSACION":
        await update.message.reply_text(details)
        return

    if action == "DESHACER":
        last_task = await task_repo.get_last_task(chat_id)
        if last_task:
            await task_repo.delete_by_id(last_task.id)
            msg = f"🗑️ Se deshizo tu última carga: [{last_task.tipo.value}] {last_task.detalles}"
            if last_task.tipo == TaskType.EVENTO:
                msg += (
                    "\n⚠️ (Importante: Borralo manualmente de Google Calendar, "
                    "ya que esa conexión es de una sola vía por ahora)."
                )
            await update.message.reply_text(msg)
        else:
            await update.message.reply_text("No encontré ningún registro reciente para deshacer.")
        return

    if action == "ELIMINAR_FECHA":
        if fecha_hora:
            date_str = fecha_hora.strftime("%Y-%m-%d")
            deleted = await task_repo.delete_by_date(chat_id, date_str)
            await update.message.reply_text(
                f"🗑️ Se eliminaron {deleted} registros programados para el {date_str}."
            )
        else:
            await update.message.reply_text(
                "No pude identificar qué fecha querés borrar. "
                "Probá diciendo 'Borrar todo lo del 25 de octubre'."
            )
        return

    # Crear evento en Google Calendar
    if action == "EVENTO" and fecha_hora:
        calendar = get_calendar_service()
        success = await calendar.create_event(details, fecha_hora)
        if success:
            await update.message.reply_text(f"📅 Evento agendado en Calendar: {details}")
        else:
            await update.message.reply_text("Hubo un error al guardar en Calendar.")
        return

    # Guardar en BD (RECORDATORIO, NOTA, o EVENTO sin calendar)
    await task_repo.save(
        telefono_id=chat_id,
        tipo=TaskType(action),
        detalles=details,
        fecha_hora=fecha_hora,
    )

    response = f"📝 Guardado como {action}."

    # Programar alarma si es RECORDATORIO con fecha futura
    if action == "RECORDATORIO" and fecha_hora:
        reminder_service = get_reminder_service()
        scheduled = await reminder_service.schedule_reminder(
            context.job_queue,
            chat_id=update.message.chat_id,
            details=details,
            when=fecha_hora,
        )
        if scheduled:
            response += " ⏰ Alarma programada."

    await update.message.reply_text(response)


# ============================================================
# RESUMEN DIARIO (Job programado)
# ============================================================

async def send_daily_summary(context: ContextTypes.DEFAULT_TYPE):
    """Envía resumen diario al usuario (job programado a las 6:50)."""
    chat_id = settings.mi_telegram_id
    if not chat_id:
        return

    try:
        summary_service = get_summary_service()
        await summary_service.send_daily_summary(context.bot, chat_id)
    except Exception as e:
        logger.error("daily_summary_failed", error=str(e), exc_info=True)


# ============================================================
# MAIN - ENTRY POINT
# ============================================================

async def post_init(application: Application):
    """Inicialización post-construcción de la aplicación."""
    # Inicializar pool de BD y tablas
    await init_db()
    logger.info("database_ready")

    # Verificar servicios
    ai = get_ai_service()
    if not ai.is_available():
        logger.warning("ai_service_unavailable")
    else:
        logger.info("ai_service_ready")

    calendar = get_calendar_service()
    try:
        await calendar.ensure_credentials()
        logger.info("calendar_service_ready")
    except Exception as e:
        logger.warning("calendar_service_unavailable", error=str(e))


async def post_shutdown(application: Application):
    """Limpieza al apagar."""
    await close_pool()
    logger.info("application_shutdown_complete")


def main():
    """Punto de entrada principal."""
    logger.info("starting_secretar_ia")

    # Construir aplicación
    app = (
        Application.builder()
        .token(settings.telegram_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Registrar handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("ayuda", help_cmd))
    app.add_handler(CommandHandler("resumen", summary_cmd))
    app.add_handler(CommandHandler("notas", notes_cmd))
    app.add_handler(CommandHandler("test", test_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text))
    app.add_handler(MessageHandler(filters.VOICE, receive_audio))
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Job diario: resumen a las 6:50 AM (hora Argentina)
    daily_time = datetime.time(hour=6, minute=50, tzinfo=ZONA_HORARIA)
    app.job_queue.run_daily(send_daily_summary, time=daily_time)
    logger.info("daily_summary_scheduled", time="06:50", timezone=str(ZONA_HORARIA))

    # Iniciar health check server en background thread
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()

    logger.info("bot_started_polling")
    app.run_polling()


if __name__ == "__main__":
    main()