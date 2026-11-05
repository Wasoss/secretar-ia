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


async def keep_alive_bot_job(context: ContextTypes.DEFAULT_TYPE):
    """Job cada 2 min para mantener vivo el bot de Telegram y evitar spin-down en Render free tier."""
    try:
        chat_id = settings.mi_telegram_id
        if not chat_id:
            return

        # Enviar un "typing" action o un getMe para mantener la conexión viva
        from infrastructure.di.container import get_container
        container = get_container()
        services = await container.get_all_services()
        ai_service = services['ai_service']

        if ai_service.is_available():
            # Hacer una llamada ligera a la API de Telegram para mantener la conexión viva
            # Usamos getMe que es ligero y no envía mensajes
            await ai_service._client._client.get("https://api.telegram.org/bot" + settings.telegram_token.split(":")[0] + ":" + settings.telegram_token.split(":")[1] + "/getMe")
            logger.debug("keep_alive_bot_ok")
    except Exception as e:
        logger.warning("keep_alive_bot_failed", error=str(e))