"""
Weekly job handlers for Secretar-IA.
"""
from telegram.ext import ContextTypes
from config.settings import settings
from config.logging import get_logger

logger = get_logger(__name__)


async def send_weekly_review_job(context: ContextTypes.DEFAULT_TYPE):
    """Job semanal: Domingo 10:00 AM - Revisión semanal."""
    chat_id = settings.mi_telegram_id
    if not chat_id:
        return

    from infrastructure.di.container import get_container
    container = get_container()
    services = await container.get_all_services()
    weekly_planning_service = services['weekly_planning_service']

    await weekly_planning_service.send_weekly_review(context.bot, chat_id)