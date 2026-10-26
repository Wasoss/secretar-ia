"""
Servicio de Resumen Diario - Genera y envía el resumen matutino.
Versión mejorada con:
- Sugerencias proactivas basadas en IA
- Mejor formateo
- Soporte para tareas recurrentes
"""
from typing import TYPE_CHECKING, List, Optional
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from config.settings import settings
from config.logging import get_logger
from infrastructure.database.repositories.task_repo import TaskRepository, Task

if TYPE_CHECKING:
    from application.services.calendar_service import CalendarService
    from application.services.ai_service import AIService

logger = get_logger(__name__)


class SummaryService:
    """Servicio para generar y enviar resúmenes diarios."""

    def __init__(
        self,
        task_repo: TaskRepository,
        calendar_service: "CalendarService",
        ai_service: Optional["AIService"] = None,
    ):
        self._task_repo = task_repo
        self._calendar_service = calendar_service
        self._ai_service = ai_service

    async def send_daily_summary(self, bot: Bot, chat_id: str) -> None:
        """
        Envía el resumen diario al usuario con sugerencia proactiva.

        Args:
            bot: Instancia de Bot de Telegram
            chat_id: Chat ID del usuario
        """
        try:
            # Obtener datos en paralelo
            pending_tasks = await self._task_repo.get_pending(chat_id)
            calendar_events = await self._calendar_service.get_upcoming_events(max_results=5)

            if not pending_tasks and not calendar_events:
                await bot.send_message(
                    chat_id=chat_id,
                    text="¡Buen día! ☀️ No tenés tareas ni eventos próximos."
                )
                # Aun así intentar sugerencia proactiva
                await self._send_proactive_suggestion(bot, chat_id, [], [])
                return

            mensaje = "¡Buen día! ☀️ Acá tenés tu resumen:\n\n"

            # Eventos de Calendar
            if calendar_events:
                mensaje += "📅 <b>Próximos eventos (Calendar):</b>\n"
                for evento in calendar_events:
                    inicio = evento['start'].get('dateTime', evento['start'].get('date'))
                    fecha_str = self._format_fecha(inicio)
                    # Mostrar si es recurrente
                    rec_indicator = " 🔄" if evento.get('recurrence') else ""
                    mensaje += f"▷ {evento.get('summary', 'Sin título')} (<i>{fecha_str}</i>){rec_indicator}\n"
                mensaje += "\n"

            # Tareas y notas pendientes
            if pending_tasks:
                mensaje += "📝 <b>Tareas y Notas pendientes:</b>\n"
                botones = []
                for tarea in pending_tasks:
                    # Indicadores visuales
                    priority_indicator = " 🔴" if tarea.prioridad == 1 else " 🟢" if tarea.prioridad == -1 else ""
                    rec_indicator = " 🔄" if tarea.recurrencia else ""
                    tag_str = f" #{' #'.join(tarea.tags)}" if tarea.tags else ""

                    fecha_str = f" (<i>{self._format_fecha(tarea.fecha_hora.isoformat())}</i>)" if tarea.fecha_hora else ""
                    mensaje += f"○ <b>[{tarea.tipo.value}]</b> {tarea.detalles}{fecha_str}{priority_indicator}{rec_indicator}{tag_str}\n"

                    # Botón para completar (usar prefijo único)
                    botones.append([
                        InlineKeyboardButton(
                            f"✅ {tarea.detalles[:30]}",
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

            logger.info("daily_summary_sent", chat_id=chat_id,
                       tasks=len(pending_tasks), events=len(calendar_events))

            # Enviar sugerencia proactiva si hay IA disponible
            await self._send_proactive_suggestion(bot, chat_id, pending_tasks, calendar_events)

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

    async def _send_proactive_suggestion(
        self,
        bot: Bot,
        chat_id: str,
        pending_tasks: List[Task],
        calendar_events: List[dict]
    ) -> None:
        """Envía sugerencia proactiva generada por IA."""
        if not self._ai_service:
            return

        try:
            suggestion = await self._ai_service.generate_proactive_suggestion(
                pending_tasks, calendar_events
            )
            if suggestion:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"💡 <i>{suggestion}</i>",
                    parse_mode=ParseMode.HTML
                )
        except Exception as e:
            logger.error("proactive_suggestion_send_failed", error=str(e))

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

    async def send_custom_summary(
        self,
        bot: Bot,
        chat_id: str,
        tasks: List[Task],
        events: List[dict],
        title: str = "Resumen"
    ) -> None:
        """Envía un resumen personalizado (para comandos LISTAR, BUSCAR)."""
        try:
            if not tasks and not events:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"{title}: No hay resultados."
                )
                return

            mensaje = f"📋 <b>{title}:</b>\n\n"

            if events:
                mensaje += "📅 <b>Eventos:</b>\n"
                for evento in events:
                    inicio = evento['start'].get('dateTime', evento['start'].get('date'))
                    fecha_str = self._format_fecha(inicio)
                    rec_indicator = " 🔄" if evento.get('recurrence') else ""
                    mensaje += f"▷ {evento.get('summary', 'Sin título')} (<i>{fecha_str}</i>){rec_indicator}\n"
                mensaje += "\n"

            if tasks:
                mensaje += "📝 <b>Tareas:</b>\n"
                for tarea in tasks:
                    priority_indicator = " 🔴" if tarea.prioridad == 1 else " 🟢" if tarea.prioridad == -1 else ""
                    rec_indicator = " 🔄" if tarea.recurrencia else ""
                    tag_str = f" #{' #'.join(tarea.tags)}" if tarea.tags else ""
                    fecha_str = f" (<i>{self._format_fecha(tarea.fecha_hora.isoformat())}</i>)" if tarea.fecha_hora else ""
                    mensaje += f"○ <b>[{tarea.tipo.value}]</b> {tarea.detalles}{fecha_str}{priority_indicator}{rec_indicator}{tag_str}\n"

            await bot.send_message(
                chat_id=chat_id,
                text=mensaje,
                parse_mode=ParseMode.HTML
            )

        except Exception as e:
            logger.error("custom_summary_failed", chat_id=chat_id, error=str(e))