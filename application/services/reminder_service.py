"""
Servicio de Recordatorios - Programa y envía alarmas usando job_queue de python-telegram-bot.
"""
import datetime
from typing import Optional
from telegram.ext import JobQueue

from config.settings import settings
from config.logging import get_logger

logger = get_logger(__name__)


class ReminderService:
    """Servicio para programar y gestionar recordatorios/alarmas."""

    async def schedule_reminder(
        self,
        job_queue: JobQueue,
        chat_id: int,
        details: str,
        when: datetime.datetime,
    ) -> bool:
        """
        Programa un recordatorio para una fecha/hora futura.

        Args:
            job_queue: JobQueue de la aplicación de Telegram
            chat_id: Chat ID donde enviar el recordatorio
            details: Texto del recordatorio
            when: Fecha/hora del recordatorio (debe ser timezone-aware)

        Returns:
            True si se programó correctamente
        """
        if when.tzinfo is None:
            when = when.replace(tzinfo=settings.tz)
        elif when.tzinfo != settings.tz:
            when = when.astimezone(settings.tz)

        now = datetime.datetime.now(settings.tz)

        if when <= now:
            logger.warning("reminder_in_past", when=when.isoformat(), now=now.isoformat())
            return False

        wait_seconds = (when - now).total_seconds()

        try:
            job_queue.run_once(
                self._send_reminder,
                when=wait_seconds,
                chat_id=chat_id,
                data=details,
                name=f"reminder_{chat_id}_{when.timestamp()}"
            )
            logger.info("reminder_scheduled", chat_id=chat_id, when=when.isoformat(), wait_seconds=wait_seconds)
            return True
        except Exception as e:
            logger.error("reminder_schedule_failed", error=str(e), exc_info=True)
            return False

    async def _send_reminder(self, context):
        """Callback ejecutado cuando llega la hora del recordatorio."""
        try:
            chat_id = context.job.chat_id
            details = context.job.data

            from telegram.constants import ParseMode
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⏰ <b>¡RECORDATORIO!</b>\n\nEs hora de: {details}",
                parse_mode=ParseMode.HTML
            )
            logger.info("reminder_sent", chat_id=chat_id, details=details[:50])
        except Exception as e:
            logger.error("reminder_send_failed", error=str(e), exc_info=True)

    async def cancel_reminders(self, job_queue: JobQueue, chat_id: int) -> int:
        """
        Cancela todos los recordatorios pendientes de un usuario.

        Returns:
            Número de jobs cancelados
        """
        jobs = job_queue.get_jobs_by_name(f"reminder_{chat_id}_")
        count = 0
        for job in jobs:
            job.schedule_removal()
            count += 1
        if count:
            logger.info("reminders_cancelled", chat_id=chat_id, count=count)
        return count