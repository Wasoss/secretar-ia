"""
Servicio de Resumen Diario - Genera y envía el resumen matutino.
"""
from typing import TYPE_CHECKING
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from config.settings import settings
from config.logging import get_logger
from infrastructure.database.repositories.task_repo import TaskRepository, Task

if TYPE_CHECKING:
    from application.services.calendar_service import CalendarService

logger = get_logger(__name__)


class SummaryService:
    """Servicio para generar y enviar resúmenes diarios."""

    def __init__(
        self,
        task_repo: TaskRepository,
        calendar_service: "CalendarService"
    ):
        self._task_repo = task_repo
        self._calendar_service = calendar_service

    async def send_daily_summary(self, bot: Bot, chat_id: str) -> None:
        """
        Envía el resumen diario al usuario.

        Args:
            bot: Instancia de Bot de Telegram
            chat_id: Chat ID del usuario
        """
        try:
            # Obtener datos en paralelo
            pending_tasks = await self._task_repo.get_pending(chat_id)
            calendar_events = await self._calendar_service.get_upcoming_events()

            if not pending_tasks and not calendar_events:
                await bot.send_message(
                    chat_id=chat_id,
                    text="¡Buen día! ☀️ No tenés tareas ni eventos próximos."
                )
                return

            mensaje = "¡Buen día! ☀️ Acá tenés tu resumen:\n\n"

            # Eventos de Calendar
            if calendar_events:
                mensaje += "📅 <b>Próximos eventos (Calendar):</b>\n"
                for evento in calendar_events:
                    inicio = evento['start'].get('dateTime', evento['start'].get('date'))
                    fecha_str = self._format_fecha(inicio)
                    mensaje += f"▷ {evento.get('summary', 'Sin título')} (<i>{fecha_str}</i>)\n"
                mensaje += "\n"

            # Tareas y notas pendientes
            if pending_tasks:
                mensaje += "📝 <b>Tareas y Notas pendientes:</b>\n"
                botones = []
                for tarea in pending_tasks:
                    fecha_str = f" (<i>{self._format_fecha(tarea.fecha_hora.isoformat())}</i>)" if tarea.fecha_hora else ""
                    mensaje += f"○ <b>[{tarea.tipo.value}]</b> {tarea.detalles}{fecha_str}\n"
                    # Usar prefijo único para completar
                    botones.append([
                        InlineKeyboardButton(
                            f"✅ {tarea.detalles[:25]}",
                            callback_data=f"complete_{tarea.id}"
                        )
                    ])

                teclado = InlineKeyboardMarkup(botones)
                await bot.send_message(
                    chat_id=chat_id,
                    text=mensaje,
                    reply_markup=teclado,
                    parse_mode=ParseMode.HTML
                )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text=mensaje,
                    parse_mode=ParseMode.HTML
                )

            logger.info("daily_summary_sent", chat_id=chat_id, tasks=len(pending_tasks), events=len(calendar_events))

        except Exception as e:
            logger.error("daily_summary_failed", chat_id=chat_id, error=str(e), exc_info=True)
            # Intentar notificar al usuario
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Hubo un error generando tu resumen diario."
                )
            except Exception:
                pass

    def _format_fecha(self, fecha_str: str) -> str:
        """Formatea fecha ISO a formato argentino."""
        try:
            clean = fecha_str.replace("T", " ")[:19]
            from datetime import datetime
            dt = datetime.fromisoformat(clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=settings.tz)
            return dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            return fecha_str