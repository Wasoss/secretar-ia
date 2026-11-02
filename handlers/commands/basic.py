"""
Basic command handlers: start, ajuda, status, ping, test.
"""
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from handlers.base import BaseHandler, handle_errors, require_auth
from utils.formatters import build_confirmation_message
from config.logging import get_logger

logger = get_logger(__name__)


class BasicCommandsHandler(BaseHandler):
    """Handler for basic bot commands."""

    @handle_errors
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /start - Bienvenida y registro de chat_id."""
        if not await require_auth(update):
            return

        # Guardar chat_id para jobs
        context.job_queue.run_once(self._guardar_chat_id, 1, data=str(update.message.chat_id))

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

    async def _guardar_chat_id(self, context: ContextTypes.DEFAULT_TYPE):
        """Guarda el chat_id en bot_data para jobs programados."""
        context.bot_data['chat_id'] = context.job.data

    @handle_errors
    async def ajuda(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /ayuda - Guía de funciones."""
        if not await require_auth(update):
            return

        texto = (
            "🤖 <b>Guía de Secretar-IA</b>\n\n"
            "📅 <b>Eventos (Google Calendar):</b>\n\n"
            "  <i>\"Reunión el martes a las 15hs\"</i>\n"
            "  <i>\"Cita dentista el 20/01 a las 10:30\"</i>\n"
            "  <i>\"Clase yoga cada lunes a las 19hs\"</i> (recurrente)\n\n"
            "⏰ <b>Recordatorios (alarmas locales):</b>\n\n"
            "  <i>\"Recordame llamar a mamá a las 18hs\"</i>\n"
            "  <i>\"Avisame tomar pastillas cada 8hs\"</i> (recurrente)\n\n"
            "📔 <b>Notas (sin fecha):</b>\n\n"
            "  <i>\"Anotá la clave wifi es 1234\"</i>\n"
            "  <i>\"Idea: regalo para Ana - libro\"</i>\n\n"
            "☑️ <b>Tareas diarias (lista con sub-items):</b>\n\n"
            "  <i>\"Lista de hoy: estudiar lógica, preparar clases, limpiar\"</i>\n"
            "  → Se crea una lista con checkboxes para tachar individualmente\n\n"
            "🔧 <b>Gestión avanzada:</b>\n\n"
            "  <i>\"Cambia la reunión al miércoles 16hs\"</i> (reagendar)\n"
            "  <i>\"Borrar todo del 25 de octubre\"</i>\n"
            "  <i>\"Deshacer\"</i> (borra último)\n\n"
            "📋 <b>Comandos:</b>\n\n"
            "  /resumen — Resumen matutino (eventos hoy/mañana + tareas)\n"
            "  /pendientes — Ver tareas diarias con sub-items para tachar\n"
            "  /notas — Consultar notas guardadas\n"
            "  /hoy — Ver agenda de hoy\n"
            "  /semana — Ver agenda de la semana\n"
            "  /buscar <texto> — Buscar en notas/eventos\n"
            "  /tag <etiqueta> — Filtrar por tag\n"
            "  /ayuda — Esta guía\n"
            "  /test — Diagnóstico del sistema\n\n"
            "💡 <b>Tips:</b> Usá #tag para organizar. "
            "Palabras clave: <i>urgente</i> (prioridad alta), "
            "<i>no apura</i> (baja).\n"
            "Para lista diaria: decí <i>\"Lista de hoy: ...\"</i> o <i>\"Tareas de hoy: ...\"</i>"
        )
        if update.message:
            await update.message.reply_text(texto, parse_mode=ParseMode.HTML)
        else:
            logger.warning("ayuda_called_without_message")

    @handle_errors
    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /status - Estado rápido del bot."""
        if not await require_auth(update):
            return
        await update.message.reply_text("✅ Bot operativo")

    @handle_errors
    async def ping(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /ping - Test simple de conectividad."""
        if not await require_auth(update):
            return
        await update.message.reply_text("🏓 Pong! Bot funcionando correctamente.")

    @handle_errors
    async def test_sistema(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /test - Diagnóstico del sistema."""
        if not await require_auth(update):
            return

        chat_id = str(update.effective_chat.id)
        try:
            services = await self.get_services()
            task_repo = services['task_repo']
            calendar_service = services['calendar_service']
            ai_service = services['ai_service']

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
                f"   └ Modelo: {ai_service._client._model if ai_ok else 'N/A'}"
            )
            await update.message.reply_text(resultado, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error("test_sistema_failed", error=str(e), exc_info=True)
            await update.message.reply_text(f"❌ Error en test:\n<code>{e}</code>", parse_mode=ParseMode.HTML)


# Instance for easy import
basic_commands = BasicCommandsHandler()

# Export handler functions for registration
start = basic_commands.start
ajuda = basic_commands.ajuda
status = basic_commands.status
ping = basic_commands.ping
test_sistema = basic_commands.test_sistema