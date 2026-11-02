"""
Objectives command handlers: objetivos, revision.
"""
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from handlers.base import BaseHandler, handle_errors, require_auth
from config.logging import get_logger

logger = get_logger(__name__)


class ObjectivesCommandsHandler(BaseHandler):
    """Handler for objectives and review commands."""

    @handle_errors
    async def ver_objetivos(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /objetivos - Ver/crear objetivos semanales."""
        if not await require_auth(update):
            return

        chat_id = str(update.message.chat_id)
        services = await self.get_services()
        objetivo_repo = services['objetivo_repo']

        try:
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
            logger.error("ver_objetivos_error", error=str(e), exc_info=True)
            await update.message.reply_text("❌ Error al obtener objetivos. Reintentá en unos segundos.")

    @handle_errors
    async def ver_revision(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /revision - Disparar revisión semanal manual."""
        if not await require_auth(update):
            return

        chat_id = str(update.message.chat_id)
        services = await self.get_services()
        weekly_planning_service = services['weekly_planning_service']

        try:
            await weekly_planning_service.send_weekly_review(
                bot=update._bot,
                chat_id=chat_id
            )
        except Exception as e:
            logger.error("ver_revision_error", error=str(e), exc_info=True)
            await update.message.reply_text("❌ Error al generar revisión. Reintentá en unos segundos.")


objectives_commands = ObjectivesCommandsHandler()
ver_objetivos = objectives_commands.ver_objetivos
ver_revision = objectives_commands.ver_revision