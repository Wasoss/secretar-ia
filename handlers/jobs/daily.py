"""
Daily job handlers for Secretar-IA.
"""
from telegram.ext import ContextTypes
from config.settings import settings
from config.logging import get_logger

logger = get_logger(__name__)


async def enviar_resumen_diario(context: ContextTypes.DEFAULT_TYPE):
    """Job diario que envía el resumen matutino."""
    chat_id = settings.mi_telegram_id
    if not chat_id:
        return

    from infrastructure.di.container import get_container
    container = get_container()
    services = await container.get_all_services()
    summary_service = services['summary_service']

    await summary_service.send_daily_summary(context.bot, chat_id)


async def apply_daily_template_job(context: ContextTypes.DEFAULT_TYPE):
    """Job diario que aplica la plantilla diaria a las 6:30 AM."""
    chat_id = settings.mi_telegram_id
    if not chat_id:
        return

    from infrastructure.di.container import get_container
    container = get_container()
    services = await container.get_all_services()
    weekly_planning_service = services['weekly_planning_service']

    await weekly_planning_service.apply_daily_template(chat_id)


async def send_evening_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """Job diario que envía recordatorio vespertino a las 18:00."""
    chat_id = settings.mi_telegram_id
    if not chat_id:
        return

    from infrastructure.di.container import get_container
    container = get_container()
    services = await container.get_all_services()
    summary_service = services['summary_service']

    await summary_service.send_evening_reminder(context.bot, chat_id)