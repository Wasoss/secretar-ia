"""
Template command handlers: plantillas.
"""
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from handlers.base import BaseHandler, handle_errors, require_auth
from config.logging import get_logger

logger = get_logger(__name__)


class TemplatesCommandsHandler(BaseHandler):
    """Handler for template-related commands."""

    @handle_errors
    async def ver_plantillas(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /plantillas - Ver/gestionar plantillas."""
        if not await require_auth(update):
            return

        chat_id = str(update.message.chat_id)
        services = await self.get_services()
        plantilla_repo = services['plantilla_repo']

        try:
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
            logger.error("ver_plantillas_error", error=str(e), exc_info=True)
            await update.message.reply_text("❌ Error al obtener plantillas. Reintentá en unos segundos.")


templates_commands = TemplatesCommandsHandler()
ver_plantillas = templates_commands.ver_plantillas