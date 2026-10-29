"""
Secretar-IA - Asistente personal inteligente para Telegram.
Versión moderna con arquitectura async, servicios desacoplados y IA enriquecida.
"""
import os
import asyncio
import datetime
import threading
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo
from typing import Optional
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode

from config.settings import settings
from config.logging import configure_logging, get_logger
from application.services.ai_service import AIService, ActionType, ParsedIntent
from application.services.calendar_service import CalendarService
from application.services.reminder_service import ReminderService
from application.services.summary_service import SummaryService
from application.services.weekly_planning_service import WeeklyPlanningService
from infrastructure.database.connection import init_db, close_pool
from infrastructure.database.repositories.task_repo import TaskRepository, TaskType, TaskStatus, SubTask
from infrastructure.database.repositories.plantilla_repo import PlantillaRepository
from infrastructure.database.repositories.objetivo_repo import ObjetivoRepository
from infrastructure.database.repositories.revision_repo import RevisionRepository

load_dotenv()

# Configurar logging estructurado
configure_logging()
logger = get_logger(__name__)

# Servicios globales (inicializados en startup)
ai_service: AIService = None
calendar_service: CalendarService = None
reminder_service: ReminderService = None
summary_service: SummaryService = None
weekly_planning_service: WeeklyPlanningService = None
task_repo: TaskRepository = None
plantilla_repo: PlantillaRepository = None
objetivo_repo: ObjetivoRepository = None
revision_repo: RevisionRepository = None

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


# --- FORMATEO Y UTILIDADES ---
def formatear_fecha_arg(fecha_str: str) -> str:
    """Formatea fecha ISO a formato argentino (DD/MM/YYYY HH:MM)."""
    if not fecha_str or fecha_str.lower() == "null":
        return ""
    try:
        clean = fecha_str.replace("T", " ")[:19]
        dt = datetime.datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZONA_HORARIA)
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return fecha_str


async def verificar_usuario(update: Update) -> bool:
    """Verifica que el usuario sea el autorizado."""
    chat_id = str(update.effective_chat.id)
    if chat_id != settings.mi_telegram_id:
        logger.warning("acceso_bloqueado", chat_id=chat_id)
        await update.message.reply_text("⛔ Acceso denegado. No estás autorizado para usar este bot.")
        return False
    return True


# --- HANDLERS DE COMANDOS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start - Bienvenida y registro de chat_id."""
    if not await verificar_usuario(update):
        return

    # Guardar chat_id para jobs
    context.job_queue.run_once(guardar_chat_id, 1, data=str(update.message.chat_id))

    await update.message.reply_text(
        "Hola. Soy tu Secretar-IA. ✨\n\n"
        "Ahora entiendo peticiones complejas:\n"
        "• <i>\"Reunión con Juan el próximo martes a las 14hs, urgente #trabajo\"</i>\n"
        "• <i>\"Recordame tomar agua cada hora en días hábiles\"</i>\n"
        "• <i>\"Cambia la reunión de Juan al miércoles a las 15hs\"</i>\n"
        "• <i>\"Qué tengo el viernes\"</i> / <i>\"Buscar nota wifi\"</i>\n"
        "• <i>\"Lista de tareas de hoy: estudiar lógica, preparar clases, limpiar piso\"</i>\n\n"
        "Comandos: /resumen /pendientes /notas /ayuda /test",
        parse_mode=ParseMode.HTML
    )


async def guardar_chat_id(context: ContextTypes.DEFAULT_TYPE):
    """Guarda el chat_id en bot_data para jobs programados."""
    context.bot_data['chat_id'] = context.job.data


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ayuda - Guía de funciones."""
    if not await verificar_usuario(update):
        return

    texto = (
        "🤖 <b>Guía de Secretar-IA</b>\n\n"
        "📅 <b>Eventos (Google Calendar):</b>\n"
        "  <i>\"Reunión el martes a las 15hs\"</i>\n"
        "  <i>\"Cita dentista el 20/01 a las 10:30\"</i>\n"
        "  <i>\"Clase yoga cada lunes a las 19hs\"</i> (recurrente)\n\n"
        "⏰ <b>Recordatorios (alarmas locales):</b>\n"
        "  <i>\"Recordame llamar a mamá a las 18hs\"</i>\n"
        "  <i>\"Avisame tomar pastillas cada 8hs\"</i> (recurrente)\n\n"
        "📔 <b>Notas (sin fecha):</b>\n"
        "  <i>\"Anotá la clave wifi es 1234\"</i>\n"
        "  <i>\"Idea: regalo para Ana - libro\"</i>\n\n"
        "☑️ <b>Tareas diarias (lista con sub-items):</b>\n"
        "  <i>\"Lista de hoy: estudiar lógica, preparar clases, limpiar\"</i>\n"
        "  → Se crea una lista con checkboxes para tachar individualmente\n\n"
        "🔧 <b>Gestión avanzada:</b>\n"
        "  <i>\"Cambia la reunión al miércoles 16hs\"</i> (reagendar)\n"
        "  <i>\"Borrar todo del 25 de octubre\"</i>\n"
        "  <i>\"Deshacer\"</i> (borra último)\n\n"
        "📋 <b>Comandos:</b>\n"
        "  /resumen — Resumen matutino (eventos hoy/mañana + tareas)\n"
        "  /pendientes — Ver tareas diarias con sub-items para tachar\n"
        "  /notas — Consultar notas guardadas\n"
        "  /hoy — Ver agenda de hoy\n"
        "  /semana — Ver agenda de la semana\n"
        "  /buscar &lt;texto&gt; — Buscar en notas/eventos\n"
        "  /tag <etiqueta> — Filtrar por tag\n"
        "  /ayuda — Esta guía\n"
        "  /test — Diagnóstico del sistema\n\n"
        "💡 <b>Tips:</b> Usá #tag para organizar. "
        "Palabras clave: <i>urgente</i> (prioridad alta), "
        "<i>no apura</i> (baja).\n"
        "Para lista diaria: decí <i>\"Lista de hoy: ...\"</i> o <i>\"Tareas de hoy: ...\"</i>"
    )
    await update.message.reply_text(texto, parse_mode=ParseMode.HTML)


async def test_sistema(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /test - Diagnóstico del sistema."""
    if not await verificar_usuario(update):
        return

    chat_id = str(update.effective_chat.id)
    try:
        # Test DB
        pending = await task_repo.get_pending(chat_id)
        # Test Calendar
        events = await calendar_service.get_upcoming_events(max_results=3)
        # Test IA
        ai_ok = ai_service.is_available()

        resultado = (
            "🧪 <b>Diagnóstico del Sistema:</b>\n\n"
            f"✅ Base de datos (Neon): Conectada\n"
            f"   └ Tareas pendientes: {len(pending)}\n"
            f"✅ Google Calendar: Conectado\n"
            f"   └ Próximos eventos: {len(events)}\n"
            f"{'✅' if ai_ok else '❌'} Motor IA (Groq): {'Activo' if ai_ok else 'No disponible'}\n"
            f"   └ Modelo: {settings.groq_model}"
        )
        await update.message.reply_text(resultado, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("test_sistema_failed", error=str(e), exc_info=True)
        await update.message.reply_text(f"❌ Error en test:\n<code>{e}</code>", parse_mode=ParseMode.HTML)


async def calendar_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /calendar_status - Diagnóstico detallado de Google Calendar."""
    if not await verificar_usuario(update):
        return

    chat_id = str(update.effective_chat.id)
    try:
        from infrastructure.database.connection import get_pool
        from infrastructure.database.repositories.credential_repo import CredentialRepository

        pool = await get_pool()
        cred_repo = CredentialRepository(pool)

        # Verificar token en BD
        token_json = await cred_repo.get_token("google_calendar")

        mensaje = "📅 <b>Estado Google Calendar:</b>\n\n"

        if not token_json:
            mensaje += "❌ <b>Sin token OAuth en BD</b>\n"
            mensaje += "   Necesitás correr el flujo OAuth localmente una vez.\n\n"
            mensaje += "<b>Pasos:</b>\n"
            mensaje += "1. En local: <code>python -m scripts.setup_calendar</code>\n"
            mensaje += "2. Autorizá en el navegador\n"
            mensaje += "3. El token se guarda automáticamente en Neon\n"
            mensaje += "4. Redeploy en Render\n\n"
            mensaje += "<i>Alternativa: Insertar token JSON manualmente en tabla 'credenciales' (name='google_calendar')</i>"
        else:
            mensaje += "✅ Token encontrado en BD\n"
            try:
                import json
                token_data = json.loads(token_json)
                if 'expiry' in token_data:
                    mensaje += f"   Expira: {token_data['expiry']}\n"
                if 'refresh_token' in token_data:
                    mensaje += "   ✅ Tiene refresh_token\n"
                else:
                    mensaje += "   ⚠️ SIN refresh_token (no se puede renovar)\n"
            except Exception:
                mensaje += "   ⚠️ Token con formato inválido\n"

            # Probar conexión real
            try:
                events = await calendar_service.get_upcoming_events(max_results=1)
                mensaje += f"\n✅ Conexión API: OK ({len(events)} eventos próximos)"
            except Exception as e:
                mensaje += f"\n❌ Error conectando a API: <code>{e}</code>"

        await update.message.reply_text(mensaje, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error("calendar_status_failed", error=str(e), exc_info=True)
        await update.message.reply_text(f"❌ Error:\n<code>{e}</code>", parse_mode=ParseMode.HTML)


async def ver_notas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /notas - Ver solo notas."""
    if not await verificar_usuario(update):
        return

    chat_id = str(update.message.chat_id)
    notas = await task_repo.get_notes(chat_id)

    if not notas:
        await update.message.reply_text("📔 No tenés notas guardadas actualmente.")
        return

    mensaje = "📔 <b>Tus Notas:</b>\n\n"
    botones = []
    for nota in notas:
        tag_str = f" #{' #'.join(nota.tags)}" if nota.tags else ""
        mensaje += f"○ {nota.detalles}{tag_str}\n"
        botones.append([InlineKeyboardButton(f"🗑️ {nota.detalles[:25]}", callback_data=f"delete_{nota.id}")])

    teclado = InlineKeyboardMarkup(botones)
    await update.message.reply_text(text=mensaje, reply_markup=teclado, parse_mode=ParseMode.HTML)


async def ver_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /hoy - Ver agenda de hoy."""
    if not await verificar_usuario(update):
        return

    chat_id = str(update.message.chat_id)
    hoy = datetime.datetime.now(ZONA_HORARIA).replace(hour=0, minute=0, second=0, microsecond=0)
    manana = hoy + datetime.timedelta(days=1)

    tasks = await task_repo.get_tasks_by_date_range(chat_id, hoy, manana)
    events = await calendar_service.get_upcoming_events(max_results=10, time_min=hoy)

    # Filtrar eventos de hoy
    events_hoy = [e for e in events if _event_starts_today(e, hoy)]

    await summary_service.send_custom_summary(
        context.bot, chat_id, tasks, events_hoy, "📅 Agenda de Hoy"
    )


async def ver_semana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /semana - Ver agenda de la semana."""
    if not await verificar_usuario(update):
        return

    chat_id = str(update.message.chat_id)
    hoy = datetime.datetime.now(ZONA_HORARIA).replace(hour=0, minute=0, second=0, microsecond=0)
    en_una_semana = hoy + datetime.timedelta(days=7)

    tasks = await task_repo.get_tasks_by_date_range(chat_id, hoy, en_una_semana)
    events = await calendar_service.get_upcoming_events(max_results=20, time_min=hoy)

    await summary_service.send_custom_summary(
        context.bot, chat_id, tasks, events, "📅 Agenda de la Semana"
    )


async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /buscar - Buscar en tareas y notas."""
    if not await verificar_usuario(update):
        return

    chat_id = str(update.message.chat_id)
    query = " ".join(context.args) if context.args else ""

    if not query:
        await update.message.reply_text("Uso: /buscar <texto a buscar>")
        return

    tasks = await task_repo.search_tasks(chat_id, query)
    # También buscar en calendar (limitado)
    events = await calendar_service.get_upcoming_events(max_results=50)
    events_filtrados = [e for e in events if query.lower() in e.get('summary', '').lower()]

    await summary_service.send_custom_summary(
        context.bot, chat_id, tasks, events_filtrados, f"🔍 Resultados: '{query}'"
    )


async def filtrar_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /tag - Filtrar tareas por tag."""
    if not await verificar_usuario(update):
        return

    chat_id = str(update.message.chat_id)
    tag = " ".join(context.args) if context.args else ""

    if not tag:
        await update.message.reply_text("Uso: /tag <etiqueta>")
        return

    tasks = await task_repo.get_tasks_by_tag(chat_id, tag.lower())
    await summary_service.send_custom_summary(
        context.bot, chat_id, tasks, [], f"🏷️ Tag: #{tag}"
    )


async def ver_pendientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /pendientes - Ver tareas diarias con sub-items para tachar."""
    if not await verificar_usuario(update):
        return

    chat_id = str(update.message.chat_id)
    daily_tasks = await task_repo.get_daily_tasks(chat_id)

    if not daily_tasks:
        await update.message.reply_text(
            "☑️ No tenés listas de tareas diarias activas.\n"
            "Crea una diciendo: <i>\"Lista de hoy: estudiar, preparar clases, limpiar\"</i>",
            parse_mode=ParseMode.HTML
        )
        return

    mensaje = "☑️ <b>Tareas diarias pendientes:</b>\n\n"
    botones = []

    for tarea in daily_tasks:
        pending_subs = tarea.get_pending_subtasks()
        completed_subs = tarea.get_completed_subtasks()
        total_subs = len(tarea.subtareas)

        if total_subs > 0:
            progress = f" ({len(completed_subs)}/{total_subs})"
        else:
            progress = ""

        mensaje += f"▷ <b>{tarea.detalles}</b>{progress}\n"

        # Sub-items pendientes con botones para marcar
        for sub in pending_subs:
            botones.append([
                InlineKeyboardButton(
                    f"☑️ {sub.texto[:35]}",
                    callback_data=f"subtask_{tarea.id}_{sub.id}"
                )
            ])
        # Sub-items completados (mostrar tachados)
        for sub in completed_subs:
            mensaje += f"  ~~{sub.texto}~~ ✅\n"

    if botones:
        teclado = InlineKeyboardMarkup(botones)
        await update.message.reply_text(
            text=mensaje,
            reply_markup=teclado,
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            text=mensaje + "\n✅ ¡Todas las sub-tareas completadas!",
            parse_mode=ParseMode.HTML
        )


# --- PROCESAMIENTO PRINCIPAL ---
async def procesar_peticion(update: Update, context: ContextTypes.DEFAULT_TYPE, texto_usuario: str):
    """Procesa el texto del usuario usando el servicio de IA enriquecido."""
    if not await verificar_usuario(update):
        return

    chat_id = str(update.message.chat_id)

    # Shortcut: comandos de ayuda → mostrar ayuda directamente (antes de IA)
    texto_lower = texto_usuario.lower().strip()
    if texto_lower in ("lista de comandos", "comandos", "ayuda", "menu", "menú", "help"):
        logger.info("help_shortcut_triggered", text=texto_usuario)
        await ayuda(update, context)
        return

    # Clasificar intención con IA
    intent: ParsedIntent = await ai_service.classify_intent(texto_usuario)

    # Log para debugging
    logger.info("intent_received", action=intent.accion.value,
               detalles=intent.detalles[:50], fecha=intent.fecha_hora,
               recurrence=intent.recurrencia, tags=intent.tags)

    # Manejar según acción
    if intent.accion == ActionType.ERROR:
        await update.message.reply_text(f"⚠️ No entendí: {intent.detalles}")
        return

    if intent.accion == ActionType.RECHAZADO_GASTOS:
        await update.message.reply_text(f"No gestiono finanzas. Registrá esto en tu otro bot: {intent.detalles}")
        return

    if intent.accion == ActionType.CONVERSACION:
        await update.message.reply_text(intent.detalles)
        return

    if intent.accion == ActionType.AYUDA:
        await ayuda(update, context)
        return

    if intent.accion == ActionType.DESHACER:
        await handle_deshacer(update, chat_id)
        return

    if intent.accion == ActionType.ELIMINAR_FECHA:
        await handle_eliminar_fecha(update, chat_id, intent.fecha_hora)
        return

    if intent.accion == ActionType.REAGENDAR:
        await handle_reagendar(update, context, chat_id, intent)
        return

    if intent.accion == ActionType.LISTAR:
        await handle_listar(update, context, chat_id, intent)
        return

    if intent.accion == ActionType.BUSCAR:
        await handle_buscar(update, context, chat_id, intent)
        return

    if intent.accion == ActionType.TAREA_DIARIA:
        await handle_guardar_tarea_diaria(update, context, chat_id, intent)
        return

    if intent.accion == ActionType.PLANTILLA_CREAR:
        await handle_crear_plantilla(update, context, chat_id, intent)
        return

    if intent.accion == ActionType.PLANTILLA_LISTAR:
        await handle_listar_plantillas(update, chat_id)
        return

    if intent.accion == ActionType.PLANTILLA_ACTIVAR:
        await handle_activar_plantilla(update, chat_id, intent)
        return

    if intent.accion == ActionType.OBJETIVO_CREAR:
        await handle_crear_objetivo(update, chat_id, intent)
        return

    if intent.accion == ActionType.OBJETIVO_LISTAR:
        await handle_listar_objetivos(update, chat_id)
        return

    if intent.accion == ActionType.OBJETIVO_PROGRESO:
        await handle_progreso_objetivo(update, chat_id, intent)
        return

    if intent.accion == ActionType.REVISION_SEMANAL:
        await handle_revision_semanal(update, chat_id)
        return

    # Acciones que guardan en BD: EVENTO, RECORDATORIO, NOTA
    await handle_guardar_tarea(update, context, chat_id, intent)


async def handle_guardar_tarea(update: Update, context: ContextTypes.DEFAULT_TYPE,
                               chat_id: str, intent: ParsedIntent):
    """Guarda EVENTO, RECORDATORIO o NOTA en BD y Calendar si aplica."""

    # Validación: EVENTO requiere fecha/hora
    if intent.accion == ActionType.EVENTO and not intent.fecha_hora:
        await update.message.reply_text(
            "📅 <b>Evento sin fecha/hora</b>\n\n"
            "Para agendar en Calendar necesitás día y hora.\n"
            "Probá: <i>\"mañana 9hs reunión con Juan\"</i> o <i>\"el 25/12 a las 10hs cita\"</i>",
            parse_mode=ParseMode.HTML
        )
        return

    calendar_event_id = None
    calendar_warning = ""

    # Guardar SIEMPRE en BD primero (garantiza persistencia local)
    task_id = await task_repo.save(
        telefono_id=chat_id,
        tipo=TaskType(intent.accion.value),
        detalles=intent.detalles,
        fecha_hora=intent.fecha_hora,
        recurrencia=intent.recurrencia,
        prioridad=intent.prioridad,
        tags=intent.tags,
        calendar_event_id=None,  # Se actualiza después si sincroniza
    )

    # Si es EVENTO, intentar sincronizar con Google Calendar
    if intent.accion == ActionType.EVENTO and intent.fecha_hora:
        start_dt = intent.fecha_hora
        end_dt = start_dt + datetime.timedelta(hours=1)

        # Verificar conflictos (solo avisar, no bloquear)
        conflicts = await calendar_service.check_conflicts(start_dt, end_dt)
        if conflicts:
            conflict_names = [c.get('summary', 'Sin título') for c in conflicts[:3]]
            calendar_warning = f"\n⚠️ <b>Conflicto en Calendar</b>: {', '.join(conflict_names)}"

        # Intentar crear en Calendar
        try:
            created_event = await calendar_service.create_event(
                summary=intent.detalles,
                start_dt=start_dt,
                end_dt=end_dt,
                recurrence=intent.recurrencia,
            )
            if created_event:
                calendar_event_id = created_event.get('id')
                # Actualizar BD con calendar_event_id
                await task_repo.update_task(task_id, calendar_event_id=calendar_event_id)
                logger.info("calendar_event_synced", local_action="EVENTO",
                           calendar_event_id=calendar_event_id, task_id=task_id)
            else:
                calendar_warning += "\n⚠️ No se pudo sincronizar con Google Calendar (¿token expirado?)."
        except Exception as e:
            logger.error("calendar_sync_failed", error=str(e), task_id=task_id)
            # Mostrar error específico al usuario
            error_msg = str(e)
            if "credenciales" in error_msg.lower() or "token" in error_msg.lower() or "oauth" in error_msg.lower():
                calendar_warning += "\n⚠️ <b>Sin token OAuth válido</b> - Usá <code>/calendar_status</code> para detalles"
            elif "conflict" in error_msg.lower():
                calendar_warning += "\n⚠️ Conflicto en Calendar"
            else:
                calendar_warning += f"\n⚠️ Error Calendar: <code>{error_msg[:80]}</code>"

    # Respuesta al usuario
    respuesta = _build_confirmation_message(intent, task_id, calendar_event_id)
    if calendar_warning:
        respuesta += calendar_warning

    # Programar recordatorio si es RECORDATORIO
    if intent.accion == ActionType.RECORDATORIO and intent.fecha_hora:
        success = await reminder_service.schedule_reminder(
            context.job_queue,
            int(chat_id),
            intent.detalles,
            intent.fecha_hora,
        )
        if success:
            respuesta += " ⏰ Alarma programada."
        else:
            respuesta += " ⚠️ No se pudo programar la alarma (¿fecha pasada?)."

    await update.message.reply_text(respuesta, parse_mode=ParseMode.HTML)


async def handle_guardar_tarea_diaria(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                       chat_id: str, intent: ParsedIntent):
    """Guarda una TAREA_DIARIA con sub-items en BD."""
    import uuid

    # Parsear los sub-items del texto (separados por comas, "y", saltos de línea)
    texto = intent.detalles
    # Separadores comunes: coma, "y", salto de línea, punto y coma
    import re
    items = re.split(r'[,;\n]|\\s+y\\s+', texto)
    items = [item.strip() for item in items if item.strip()]

    if not items:
        await update.message.reply_text("❌ No pude identificar los items de la lista. Probá: \"Lista de hoy: estudiar, preparar clases, limpiar\"")
        return

    # Crear sub-items con IDs únicos
    subtareas = []
    for i, item in enumerate(items):
        subtareas.append(SubTask(
            id=str(uuid.uuid4())[:8],  # ID corto
            texto=item,
            completado=False,
            orden=i
        ))

    # Guardar en BD como TAREA_DIARIA
    task_id = await task_repo.save(
        telefono_id=chat_id,
        tipo=TaskType.TAREA_DIARIA,
        detalles=texto,  # Título de la lista
        fecha_hora=None,  # Sin fecha específica, es para hoy
        estado=TaskStatus.PENDIENTE,
        prioridad=intent.prioridad,
        tags=intent.tags,
        subtareas=subtareas,
    )

    # Respuesta con botones para tachar
    mensaje = f"☑️ <b>Lista diaria creada</b> (ID: {task_id})\n"
    mensaje += f"📝 {texto}\n\n"

    botones = []
    for sub in subtareas:
        botones.append([
            InlineKeyboardButton(
                f"☑️ {sub.texto[:35]}",
                callback_data=f"subtask_{task_id}_{sub.id}"
            )
        ])
        mensaje += f"  ☐ {sub.texto}\n"

    mensaje += f"\n📋 Total: {len(subtareas)} items"
    if intent.prioridad == 1:
        mensaje += " 🔴"
    elif intent.prioridad == -1:
        mensaje += " 🟢"
    if intent.tags:
        mensaje += f" #{' #'.join(intent.tags)}"

    teclado = InlineKeyboardMarkup(botones)
    await update.message.reply_text(mensaje, reply_markup=teclado, parse_mode=ParseMode.HTML)


# ============================================================
# NUEVOS HANDLERS: Plantillas, Objetivos, Revisión Semanal
# ============================================================

async def handle_crear_plantilla(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                  chat_id: str, intent: ParsedIntent):
    """Crea una plantilla diaria reutilizable desde texto libre."""
    try:
        if weekly_planning_service is None or plantilla_repo is None:
            logger.error("handle_crear_plantilla: services not initialized")
            await update.message.reply_text("❌ Servicio no disponible. Reintentá en unos segundos.")
            return
        # Usar primer tag como nombre, o generar uno automático
        nombre = intent.tags[0] if intent.tags else None
        plantilla_id = await weekly_planning_service.create_plantilla_from_text(
            telefono_id=chat_id,
            texto=intent.detalles,
            nombre=nombre,
        )
        await update.message.reply_text(
            f"📋 <b>Plantilla creada</b> (ID: {plantilla_id})\n"
            f"📝 Items: {intent.detalles}\n"
            f"✅ Ahora se aplicará cada mañana a las 6:30 AM",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error("handle_crear_plantilla_error", error=str(e), exc_info=True)
        await update.message.reply_text("❌ Error al crear plantilla. Reintentá en unos segundos.")

async def handle_listar_plantillas(update: Update, chat_id: str):
    """Lista todas las plantillas del usuario."""
    try:
        if plantilla_repo is None:
            logger.error("handle_listar_plantillas: plantilla_repo is None")
            await update.message.reply_text("❌ Servicio no disponible. Reintentá en unos segundos.")
            return
        plantillas = await plantilla_repo.get_all(chat_id)

        if not plantillas:
            await update.message.reply_text(
                "📋 No tenés plantillas guardadas.\n"
                "Crea una diciendo: <i>\"Plantilla: cada día estudiar 2h, ejercicio\"</i>",
                parse_mode=ParseMode.HTML
            )
            return

        mensaje = "📋 <b>Tus plantillas:</b>\n\n"
        for p in plantillas:
            activa = " ✅ <b>ACTIVA</b>" if p.activa else ""
            items_preview = ", ".join([item.get("texto", "")[:30] for item in p.items[:3]])
            if len(p.items) > 3:
                items_preview += f" ... y {len(p.items) - 3} más"
            mensaje += f"▷ <b>{p.nombre}</b>{activa}\n  {items_preview}\n"

        await update.message.reply_text(mensaje, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("handle_listar_plantillas_error", error=str(e), exc_info=True)
        await update.message.reply_text("❌ Error al obtener plantillas. Reintentá en unos segundos.")

async def handle_activar_plantilla(update: Update, chat_id: str, intent: ParsedIntent):
    """Activa una plantilla por nombre."""
    try:
        if plantilla_repo is None:
            logger.error("handle_activar_plantilla: plantilla_repo is None")
            await update.message.reply_text("❌ Servicio no disponible. Reintentá en unos segundos.")
            return
        nombre = intent.detalles.strip()
        plantillas = await plantilla_repo.get_all(chat_id)

        # Buscar por nombre (parcial, case-insensitive)
        plantilla = None
        for p in plantillas:
            if nombre.lower() in p.nombre.lower():
                plantilla = p
                break

        if not plantilla:
            await update.message.reply_text(f"❌ No encontré plantilla: \"{nombre}\". Usá /plantillas para verlas.")
            return

        await plantilla_repo.set_active(chat_id, plantilla.id)
        await update.message.reply_text(
            f"✅ Plantilla activada: <b>{plantilla.nombre}</b>\n"
            f"Se aplicará mañana a las 6:30 AM",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error("handle_activar_plantilla_error", error=str(e), exc_info=True)
        await update.message.reply_text("❌ Error al activar plantilla. Reintentá en unos segundos.")

async def handle_crear_objetivo(update: Update, chat_id: str, intent: ParsedIntent):
    """Crea un objetivo semanal."""
    try:
        if weekly_planning_service is None or objetivo_repo is None:
            logger.error("handle_crear_objetivo: services not initialized")
            await update.message.reply_text("❌ Servicio no disponible. Reintentá en unos segundos.")
            return

        # Usar valores parseados por la IA si vienen, si no parsear del texto
        if intent.objetivo_valor is not None and intent.objetivo_unidad:
            valor = intent.objetivo_valor
            unidad = intent.objetivo_unidad
        else:
            # Fallback: parsear del texto
            import re
            texto = intent.detalles
            match = re.search(r'(\d+(?:\.\d+)?)\s*(h|hrs?|horas?|veces?|libros?|km|paginas?|minutos?)', texto, re.IGNORECASE)
            if match:
                valor = float(match.group(1))
                unidad = match.group(2).lower()
            else:
                valor = 1
                unidad = "veces"

        objetivo_id = await weekly_planning_service.create_objetivo(
            telefono_id=chat_id,
            descripcion=intent.detalles,
            objetivo_valor=valor,
            objetivo_unidad=unidad,
        )

        await update.message.reply_text(
            f"🎯 <b>Objetivo creado</b> (ID: {objetivo_id})\n"
            f"📝 {intent.detalles}\n"
            f"📊 Meta: {valor} {unidad}/semana\n"
            f"📅 Para la semana actual",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error("handle_crear_objetivo_error", error=str(e), exc_info=True)
        await update.message.reply_text("❌ Error al crear objetivo. Reintentá en unos segundos.")

async def handle_listar_objetivos(update: Update, chat_id: str):
    """Lista objetivos de la semana actual."""
    try:
        if objetivo_repo is None:
            logger.error("handle_listar_objetivos: objetivo_repo is None")
            await update.message.reply_text("❌ Servicio no disponible. Reintentá en unos segundos.")
            return
        objetivos = await objetivo_repo.get_active(chat_id)

        if not objetivos:
            await update.message.reply_text(
                "🎯 No tenés objetivos para esta semana.\n"
                "Crea uno: <i>\"Meta: estudiar 10h/semana\"</i>",
                parse_mode=ParseMode.HTML
            )
            return

        mensaje = "🎯 <b>Objetivos de esta semana:</b>\n\n"
        for obj in objetivos:
            emoji = obj.estado_emoji()
            mensaje += f"{emoji} <b>{obj.descripcion}</b>\n"
            mensaje += f"   Progreso: {obj.formatear_progreso()} ({obj.porcentaje:.1f}%)\n\n"

        await update.message.reply_text(mensaje, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("handle_listar_objetivos_error", error=str(e), exc_info=True)
        await update.message.reply_text("❌ Error al obtener objetivos. Reintentá en unos segundos.")

async def handle_progreso_objetivo(update: Update, chat_id: str, intent: ParsedIntent):
    """Actualiza progreso de un objetivo."""
    try:
        if objetivo_repo is None:
            logger.error("handle_progreso_objetivo: objetivo_repo is None")
            await update.message.reply_text("❌ Servicio no disponible. Reintentá en unos segundos.")
            return
        # Buscar objetivo por descripción
        objetivos = await objetivo_repo.get_active(chat_id)

        obj = None
        for o in objetivos:
            if intent.detalles.lower() in o.descripcion.lower() or o.descripcion.lower() in intent.detalles.lower():
                obj = o
                break

        if not obj:
            await update.message.reply_text("❌ No encontré ese objetivo. Usá /objetivos para verlos.")
            return

        # Usar valor parseado por la IA si viene, si no parsear del texto
        if intent.objetivo_valor is not None:
            incremento = intent.objetivo_valor
        else:
            import re
            match = re.search(r'(\d+(?:\.\d+)?)', intent.detalles)
            if not match:
                await update.message.reply_text("❌ No pude identificar el progreso. Probá: \"Avancé 2h en estudio\"")
                return
            incremento = float(match.group(1))

        await objetivo_repo.update_progress(obj.id, incremento)

        # Obtener objetivo actualizado
        obj_actualizado = await objetivo_repo.get_by_id(obj.id)

        await update.message.reply_text(
            f"📈 <b>Progreso actualizado</b>\n"
            f"📝 {obj_actualizado.descripcion}\n"
            f"📊 Progreso: {obj_actualizado.formatear_progreso()} ({obj_actualizado.porcentaje:.1f}%)\n"
            + ("✅ ¡Objetivo completado!" if obj_actualizado.completado else ""),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error("handle_progreso_objetivo_error", error=str(e), exc_info=True)
        await update.message.reply_text("❌ Error al actualizar progreso. Reintentá en unos segundos.")

async def handle_revision_semanal(update: Update, chat_id: str):
    """Genera y envía revisión semanal."""
    try:
        if weekly_planning_service is None:
            logger.error("handle_revision_semanal: weekly_planning_service is None")
            await update.message.reply_text("❌ Servicio no disponible. Reintentá en unos segundos.")
            return
        await weekly_planning_service.send_weekly_review(
            bot=update._bot,
            chat_id=chat_id
        )
    except Exception as e:
        logger.error("handle_revision_semanal_error", error=str(e), exc_info=True)
        await update.message.reply_text("❌ Error al generar revisión. Reintentá en unos segundos.")


# Commands handlers
async def ver_plantillas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /plantillas - Ver/gestionar plantillas."""
    try:
        if not await verificar_usuario(update):
            return
        if plantilla_repo is None:
            logger.error("ver_plantillas: plantilla_repo is None")
            await update.message.reply_text("❌ Servicio no disponible. Reintentá en unos segundos.")
            return
        await handle_listar_plantillas(update, chat_id=str(update.message.chat_id))
    except Exception as e:
        logger.error("ver_plantillas_error", error=str(e), exc_info=True)
        await update.message.reply_text("❌ Error al obtener plantillas. Reintentá en unos segundos.")

async def ver_objetivos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /objetivos - Ver/crear objetivos semanales."""
    try:
        if not await verificar_usuario(update):
            return
        if objetivo_repo is None:
            logger.error("ver_objetivos: objetivo_repo is None")
            await update.message.reply_text("❌ Servicio no disponible. Reintentá en unos segundos.")
            return
        await handle_listar_objetivos(update, chat_id=str(update.message.chat_id))
    except Exception as e:
        logger.error("ver_objetivos_error", error=str(e), exc_info=True)
        await update.message.reply_text("❌ Error al obtener objetivos. Reintentá en unos segundos.")

async def ver_revision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /revision - Disparar revisión semanal manual."""
    try:
        if not await verificar_usuario(update):
            return
        if weekly_planning_service is None:
            logger.error("ver_revision: weekly_planning_service is None")
            await update.message.reply_text("❌ Servicio no disponible. Reintentá en unos segundos.")
            return
        await handle_revision_semanal(update, chat_id=str(update.message.chat_id))
    except Exception as e:
        logger.error("ver_revision_error", error=str(e), exc_info=True)
        await update.message.reply_text("❌ Error al generar revisión. Reintentá en unos segundos.")


def _build_confirmation_message(intent: ParsedIntent, task_id: int, calendar_event_id: Optional[str]) -> str:
    """Construye mensaje de confirmación bonito."""
    icons = {
        ActionType.EVENTO: "📅",
        ActionType.RECORDATORIO: "⏰",
        ActionType.NOTA: "📔",
    }
    icon = icons.get(intent.accion, "📝")

    parts = [f"{icon} Guardado como <b>{intent.accion.value}</b> (ID: {task_id})"]
    parts.append(f"📝 {intent.detalles}")

    if intent.fecha_hora:
        parts.append(f"📅 {formatear_fecha_arg(intent.fecha_hora.isoformat())}")

    if intent.recurrencia:
        parts.append(f"🔄 Recurrente: <code>{intent.recurrencia}</code>")

    if intent.prioridad == 1:
        parts.append("🔴 Prioridad: ALTA")
    elif intent.prioridad == -1:
        parts.append("🟢 Prioridad: BAJA")

    if intent.tags:
        parts.append(f"🏷️ Tags: #{' #'.join(intent.tags)}")

    if calendar_event_id:
        parts.append("☁️ Sincronizado con Google Calendar")

    return "\n".join(parts)


async def handle_deshacer(update: Update, chat_id: str):
    """Maneja DESHACER - borra última tarea."""
    ultima = await task_repo.get_last_task(chat_id)
    if not ultima:
        await update.message.reply_text("No encontré ningún registro reciente para deshacer.")
        return

    # Si tenía calendar_event_id, borrar de Calendar también
    if ultima.calendar_event_id:
        await calendar_service.delete_event(ultima.calendar_event_id)

    await task_repo.delete_by_id(ultima.id)

    mensaje = f"🗑️ Se deshizo tu última carga: [{ultima.tipo.value}] {ultima.detalles}"
    if ultima.tipo == TaskType.EVENTO and ultima.calendar_event_id:
        mensaje += "\n✅ También se eliminó de Google Calendar."
    await update.message.reply_text(mensaje)


async def handle_eliminar_fecha(update: Update, chat_id: str, fecha_hora: datetime.datetime):
    """Maneja ELIMINAR_FECHA - borra todo de un día."""
    if not fecha_hora:
        await update.message.reply_text("No pude identificar qué fecha querés borrar. Probá: 'Borrar todo el 25 de octubre'.")
        return

    fecha_str = fecha_hora.strftime("%Y-%m-%d")

    # Borrar de BD
    borrados = await task_repo.delete_by_date(chat_id, fecha_str)

    # TODO: Borrar de Calendar también (requiere buscar eventos de ese día)

    await update.message.reply_text(f"🗑️ Se eliminaron {borrados} registros programados para el {fecha_str}.")


async def handle_reagendar(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          chat_id: str, intent: ParsedIntent):
    """Maneja REAGENDAR - cambia fecha/hora de tarea existente."""
    if not intent.fecha_hora:
        await update.message.reply_text("No pude identificar la nueva fecha/hora. Probá: 'Cambia la reunión al miércoles a las 15hs'.")
        return

    # Buscar tarea a reagendar
    task = None
    if intent.tarea_original_id:
        task = await task_repo.get_task_by_id(intent.tarea_original_id)
    else:
        # Buscar por similitud en últimas tareas
        pendientes = await task_repo.get_pending(chat_id)
        for t in pendientes:
            if intent.detalles.lower() in t.detalles.lower() or t.detalles.lower() in intent.detalles.lower():
                task = t
                break

    if not task:
        await update.message.reply_text("No encontré la tarea a reagendar. Probá siendo más específico o usá /resumen para ver IDs.")
        return

    # Si es EVENTO, actualizar en Calendar
    old_calendar_id = task.calendar_event_id
    new_calendar_id = None

    if task.tipo == TaskType.EVENTO:
        start_dt = intent.fecha_hora
        end_dt = start_dt + datetime.timedelta(hours=1)

        # Verificar conflictos (excluyendo el propio evento)
        conflicts = await calendar_service.check_conflicts(start_dt, end_dt, exclude_event_id=old_calendar_id)
        if conflicts:
            conflict_names = [c.get('summary', 'Sin título') for c in conflicts[:3]]
            await update.message.reply_text(
                f"⚠️ Conflicto en nuevo horario: {', '.join(conflict_names)}",
                parse_mode=ParseMode.HTML
            )
            return

        if old_calendar_id:
            updated = await calendar_service.update_event(
                event_id=old_calendar_id,
                summary=task.detalles,
                start_dt=start_dt,
                end_dt=end_dt,
                recurrence=intent.recurrencia,
            )
            if updated:
                new_calendar_id = old_calendar_id
        else:
            # No tenía ID, crear nuevo
            created = await calendar_service.create_event(
                summary=task.detalles,
                start_dt=start_dt,
                end_dt=end_dt,
                recurrence=intent.recurrencia,
            )
            if created:
                new_calendar_id = created.get('id')

    # Actualizar en BD
    await task_repo.update_task(
        task_id=task.id,
        fecha_hora=intent.fecha_hora,
        recurrencia=intent.recurrencia,
        calendar_event_id=new_calendar_id,
    )

    # Reprogramar recordatorio si era RECORDATORIO
    if task.tipo == TaskType.RECORDATORIO:
        await reminder_service.cancel_reminders(context.job_queue, int(chat_id))
        if intent.fecha_hora:
            await reminder_service.schedule_reminder(
                context.job_queue, int(chat_id), task.detalles, intent.fecha_hora
            )

    await update.message.reply_text(
        f"🔄 <b>Reagendado:</b> {task.detalles}\n"
        f"📅 Nuevo: {formatear_fecha_arg(intent.fecha_hora.isoformat())}"
        + (f"\n🔄 Recurrencia: {intent.recurrencia}" if intent.recurrencia else "")
        + ("\n☁️ Sincronizado con Calendar" if new_calendar_id else ""),
        parse_mode=ParseMode.HTML
    )


async def handle_listar(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       chat_id: str, intent: ParsedIntent):
    """Maneja LISTAR - muestra agenda según fecha_hora (hoy, semana, etc)."""
    if intent.fecha_hora:
        # Usar fecha como referencia
        ref_date = intent.fecha_hora.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        ref_date = datetime.datetime.now(ZONA_HORARIA).replace(hour=0, minute=0, second=0, microsecond=0)

    # Determinar rango según detalles
    detalles_lower = intent.detalles.lower()
    if "semana" in detalles_lower or "7 día" in detalles_lower:
        end_date = ref_date + datetime.timedelta(days=7)
        title = "📅 Agenda de la Semana"
    else:
        end_date = ref_date + datetime.timedelta(days=1)
        title = "📅 Agenda del Día"

    tasks = await task_repo.get_tasks_by_date_range(chat_id, ref_date, end_date)
    events = await calendar_service.get_upcoming_events(max_results=20, time_min=ref_date)
    events_filtrados = [e for e in events if _event_in_range(e, ref_date, end_date)]

    await summary_service.send_custom_summary(
        context.bot, chat_id, tasks, events_filtrados, title
    )


async def handle_buscar(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       chat_id: str, intent: ParsedIntent):
    """Maneja BUSCAR - busca en tareas y notas."""
    query = intent.detalles
    tasks = await task_repo.search_tasks(chat_id, query)
    events = await calendar_service.get_upcoming_events(max_results=50)
    events_filtrados = [e for e in events if query.lower() in e.get('summary', '').lower()]

    await summary_service.send_custom_summary(
        context.bot, chat_id, tasks, events_filtrados, f"🔍 Resultados: '{query}'"
    )


def _event_starts_today(event: dict, today: datetime.datetime) -> bool:
    """Verifica si un evento de Calendar empieza hoy."""
    try:
        start = event['start'].get('dateTime', event['start'].get('date'))
        dt = datetime.datetime.fromisoformat(start.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZONA_HORARIA)
        return dt.date() == today.date()
    except Exception:
        return False


def _event_in_range(event: dict, start: datetime.datetime, end: datetime.datetime) -> bool:
    """Verifica si un evento está en el rango."""
    try:
        ev_start = event['start'].get('dateTime', event['start'].get('date'))
        dt = datetime.datetime.fromisoformat(ev_start.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZONA_HORARIA)
        return start <= dt < end
    except Exception:
        return False


# --- HANDLERS DE MENSAJES ---
async def recibir_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await procesar_peticion(update, context, update.message.text)


async def recibir_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler para notas de voz y audios."""
    if not await verificar_usuario(update):
        return

    # Debug: loguear tipo de mensaje
    msg = update.message
    logger.info("audio_handler_triggered",
                has_voice=bool(msg.voice),
                has_audio=bool(msg.audio),
                has_document=bool(msg.document))

    # Soportar voice (🎤), audio (📎 audio) y document audio
    voice = msg.voice or msg.audio
    if not voice:
        if msg.document and msg.document.mime_type and msg.document.mime_type.startswith('audio/'):
            voice = msg.document
        else:
            logger.warning("audio_no_voice_attribute", message_type=type(msg).__name__)
            await update.message.reply_text("❌ No detecté audio en el mensaje.")
            return

    archivo = await voice.get_file()
    # Usar tempfile para ruta writable en Render
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        ruta_audio = tmp.name

    try:
        await archivo.download_to_drive(ruta_audio)

        transcripcion = await ai_service.transcribe_audio(ruta_audio)
        if transcripcion:
            logger.info("audio_transcribed_ok", length=len(transcripcion))
            await procesar_peticion(update, context, transcripcion)
        else:
            logger.warning("audio_transcription_empty")
            await update.message.reply_text("❌ No pude transcribir el audio.")
    except Exception as e:
        logger.error("audio_processing_failed", error=str(e), exc_info=True)
        await update.message.reply_text("❌ Error procesando el audio.")
    finally:
        try:
            os.remove(ruta_audio)
        except Exception:
            pass


async def callback_completar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para botones de completar/borrar tareas y sub-tareas."""
    query = update.callback_query
    if str(query.message.chat_id) != settings.mi_telegram_id:
        return

    data = query.data
    await query.answer()

    if data.startswith("complete_"):
        task_id = int(data.split("_")[1])
        await task_repo.complete(task_id)
        await query.answer("¡Completada! ✅")

        # Actualizar teclado
        teclado_actual = query.message.reply_markup.inline_keyboard
        nuevo_teclado = [[btn] for fila in teclado_actual for btn in fila if btn.callback_data != data]

        if nuevo_teclado:
            await query.edit_message_reply_markup(InlineKeyboardMarkup(nuevo_teclado))
        else:
            await query.edit_message_text(text="¡Todas las tareas de esta lista están listas! 🎉")

    elif data.startswith("delete_"):
        task_id = int(data.split("_")[1])
        task = await task_repo.get_task_by_id(task_id)
        if task and task.calendar_event_id:
            await calendar_service.delete_event(task.calendar_event_id)
        await task_repo.delete_by_id(task_id)
        await query.answer("🗑️ Eliminada")

    elif data.startswith("subtask_"):
        # Formato: subtask_{task_id}_{subtask_id}
        parts = data.split("_")
        if len(parts) >= 3:
            task_id = int(parts[1])
            subtask_id = parts[2]
            success = await task_repo.complete_subtask(task_id, subtask_id)
            if success:
                await query.answer("¡Sub-tarea completada! ✅")
                # Refrescar el mensaje para mostrar el estado actualizado
                task = await task_repo.get_task_by_id(task_id)
                if task:
                    # Re-construir el mensaje con estado actualizado
                    pending_subs = task.get_pending_subtasks()
                    completed_subs = task.get_completed_subtasks()
                    total_subs = len(task.subtareas)

                    mensaje = f"☑️ <b>{task.detalles}</b> ({len(completed_subs)}/{total_subs})\n\n"

                    botones = []
                    for sub in pending_subs:
                        botones.append([
                            InlineKeyboardButton(
                                f"☑️ {sub.texto[:35]}",
                                callback_data=f"subtask_{task_id}_{sub.id}"
                            )
                        ])
                    for sub in completed_subs:
                        mensaje += f"  ~~{sub.texto}~~ ✅\n"

                    if botones:
                        teclado = InlineKeyboardMarkup(botones)
                        await query.edit_message_text(
                            text=mensaje,
                            reply_markup=teclado,
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        await query.edit_message_text(
                            text=mensaje + "\n✅ ¡Todas las sub-tareas completadas!",
                            parse_mode=ParseMode.HTML
                        )
            else:
                await query.answer("❌ No se pudo completar la sub-tarea")
        else:
            await query.answer("❌ Formato de callback inválido")


# --- RESUMEN DIARIO ---
async def enviar_resumen_diario(context: ContextTypes.DEFAULT_TYPE):
    """Job diario que envía el resumen matutino."""
    chat_id = settings.mi_telegram_id
    if not chat_id:
        return

    await summary_service.send_daily_summary(context.bot, chat_id)


# --- STARTUP / MAIN ---
async def post_init(application: Application):
    """Inicialización post-arranque: DB, servicios, jobs."""
    global ai_service, calendar_service, reminder_service, summary_service, weekly_planning_service, task_repo, plantilla_repo, objetivo_repo, revision_repo

    logger.info("application_starting")

    # Inicializar DB
    await init_db()

    # Crear servicios base
    ai_service = AIService()
    calendar_service = CalendarService()
    reminder_service = ReminderService()

    # Pool y repos
    from infrastructure.database.connection import get_pool
    pool = await get_pool()
    task_repo = TaskRepository(pool)
    plantilla_repo = PlantillaRepository(pool)
    objetivo_repo = ObjetivoRepository(pool)
    revision_repo = RevisionRepository(pool)

    summary_service = SummaryService(task_repo, calendar_service, ai_service)
    weekly_planning_service = WeeklyPlanningService(
        task_repo=task_repo,
        plantilla_repo=plantilla_repo,
        objetivo_repo=objetivo_repo,
        revision_repo=revision_repo,
        calendar_service=calendar_service,
        ai_service=ai_service,
    )

    # Job diario a las 6:30 AM - Aplicar plantilla diaria
    hora_plantilla = datetime.time(hour=6, minute=30, tzinfo=ZONA_HORARIA)
    application.job_queue.run_daily(
        lambda ctx: weekly_planning_service.apply_daily_template(settings.mi_telegram_id),
        time=hora_plantilla
    )

    # Job diario a las 6:50 AM (resumen matutino)
    hora_envio = datetime.time(hour=6, minute=50, tzinfo=ZONA_HORARIA)
    application.job_queue.run_daily(enviar_resumen_diario, time=hora_envio)

    # Job diario a las 18:00 (recordatorio vespertino)
    hora_vespertino = datetime.time(hour=18, minute=0, tzinfo=ZONA_HORARIA)
    application.job_queue.run_daily(
        lambda ctx: summary_service.send_evening_reminder(ctx.bot, settings.mi_telegram_id),
        time=hora_vespertino
    )

    # Job semanal: Domingo 10:00 AM - Revisión semanal
    from datetime import time
    hora_revision = time(hour=10, minute=0, tzinfo=ZONA_HORARIA)
    application.job_queue.run_daily(
        lambda ctx: weekly_planning_service.send_weekly_review(ctx.bot, settings.mi_telegram_id),
        time=hora_revision,
        days=(6,)  # Domingo = 6 (0=Lunes, 6=Domingo)
    )

    # Keep-alive: cada 5 min hace query simple para evitar spin-down en Render free tier
    application.job_queue.run_repeating(
        lambda ctx: pool.fetchval("SELECT 1"),
        interval=300,  # 5 minutos
        first=10,
        name="keep_alive_db"
    )

    logger.info("application_ready", services=["ai", "calendar", "reminder", "summary", "weekly_planning", "db"])


async def post_shutdown(application: Application):
    """Limpieza al apagar."""
    logger.info("application_shutting_down")
    await close_pool()


def main():
    """Punto de entrada principal."""
    app = Application.builder().token(settings.telegram_token).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CommandHandler("test", test_sistema))
    app.add_handler(CommandHandler("calendar_status", calendar_status))
    app.add_handler(CommandHandler("notas", ver_notas))
    app.add_handler(CommandHandler("hoy", ver_hoy))
    app.add_handler(CommandHandler("semana", ver_semana))
    app.add_handler(CommandHandler("buscar", buscar))
    app.add_handler(CommandHandler("tag", filtrar_tag))
    app.add_handler(CommandHandler(["pendientes", "tareas"], ver_pendientes))
    # /plantillas, /planillas, /planilla (singular y plural)
    app.add_handler(CommandHandler(["plantillas", "planillas", "planilla"], ver_plantillas))
    # /objetivos, /metas, /meta (singular y plural)
    app.add_handler(CommandHandler(["objetivos", "metas", "meta"], ver_objetivos))
    app.add_handler(CommandHandler("revision", ver_revision))
    app.add_handler(CommandHandler("resumen", lambda u, c: summary_service.send_daily_summary(c.bot, settings.mi_telegram_id)))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_texto))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.Document.AUDIO, recibir_audio))
    app.add_handler(CallbackQueryHandler(callback_completar, pattern="^(complete_|delete_|subtask_)"))

    # Error handler para evitar "No error handlers are registered"
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error("bot_error", error=str(context.error), exc_info=context.error)

    app.add_error_handler(error_handler)

    # Lifecycle hooks
    app.post_init = post_init
    app.post_shutdown = post_shutdown

    # Iniciar servidor web para health checks en hilo separado
    threading.Thread(target=iniciar_servidor_web, daemon=True).start()

    logger.info("bot_starting_polling")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()