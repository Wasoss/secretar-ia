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
        Muestra eventos de HOY y MAÑANA, tareas pendientes y tareas diarias.

        Args:
            bot: Instancia de Bot de Telegram
            chat_id: Chat ID del usuario
        """
        try:
            from datetime import datetime, timedelta

            # Calcular rango: hoy 00:00 hasta mañana 23:59
            hoy = datetime.now(settings.tz).replace(hour=0, minute=0, second=0, microsecond=0)
            manana = hoy + timedelta(days=1)
            pasado_manana = hoy + timedelta(days=2)

            # Obtener datos en paralelo
            pending_tasks = await self._task_repo.get_pending(chat_id)
            daily_tasks = await self._task_repo.get_daily_tasks(chat_id)

            # Eventos de hoy y mañana
            calendar_events = await self._calendar_service.get_upcoming_events(max_results=10, time_min=hoy)

            # Filtrar eventos de hoy y mañana
            events_hoy = []
            events_manana = []
            for evento in calendar_events:
                inicio = evento['start'].get('dateTime', evento['start'].get('date'))
                try:
                    dt = datetime.fromisoformat(inicio.replace('Z', '+00:00'))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=settings.tz)
                    if dt < manana:
                        events_hoy.append(evento)
                    elif dt < pasado_manana:
                        events_manana.append(evento)
                except Exception:
                    events_hoy.append(evento)  # Por defecto a hoy si hay error

            if not pending_tasks and not daily_tasks and not events_hoy and not events_manana:
                await bot.send_message(
                    chat_id=chat_id,
                    text="¡Buen día! ☀️ No tenés tareas ni eventos para hoy ni mañana."
                )
                return

            mensaje = "¡Buen día! ☀️ Acá tenés tu resumen:\n\n"

            # Eventos de HOY
            if events_hoy:
                mensaje += "📅 <b>Eventos de HOY:</b>\n"
                for evento in events_hoy:
                    inicio = evento['start'].get('dateTime', evento['start'].get('date'))
                    fecha_str = self._format_fecha(inicio)
                    rec_indicator = " 🔄" if evento.get('recurrence') else ""
                    mensaje += f"▷ {evento.get('summary', 'Sin título')} (<i>{fecha_str}</i>){rec_indicator}\n"
                mensaje += "\n"

            # Eventos de MAÑANA
            if events_manana:
                mensaje += "📅 <b>Eventos de MAÑANA:</b>\n"
                for evento in events_manana:
                    inicio = evento['start'].get('dateTime', evento['start'].get('date'))
                    fecha_str = self._format_fecha(inicio)
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

            # Tareas diarias (TAREA_DIARIA) con sub-items
            if daily_tasks:
                if pending_tasks:
                    mensaje += "\n"
                mensaje += "☑️ <b>Tareas diarias de hoy:</b>\n"
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

            if pending_tasks or daily_tasks:
                if botones:
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
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text=mensaje,
                    parse_mode=ParseMode.HTML
                )

            logger.info("daily_summary_sent", chat_id=chat_id,
                       tasks=len(pending_tasks), daily_tasks=len(daily_tasks),
                       events=len(events_hoy) + len(events_manana))

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

    async def send_evening_reminder(self, bot: Bot, chat_id: str) -> None:
        """
        Envía recordatorio vespertino (18:00) con actividades pendientes del día.

        Args:
            bot: Instancia de Bot de Telegram
            chat_id: Chat ID del usuario
        """
        try:
            from datetime import datetime, timedelta

            # Calcular fin de día (23:59)
            hoy = datetime.now(settings.tz).replace(hour=0, minute=0, second=0, microsecond=0)
            fin_dia = hoy + timedelta(days=1) - timedelta(seconds=1)

            # Obtener tareas diarias pendientes
            daily_tasks = await self._task_repo.get_daily_tasks(chat_id)

            # Tareas/recordatorios pendientes para hoy
            pending_tasks = await self._task_repo.get_pending(chat_id)
            tasks_hoy = [t for t in pending_tasks if t.fecha_hora and t.fecha_hora <= fin_dia]

            # Eventos restantes de hoy
            calendar_events = await self._calendar_service.get_upcoming_events(max_results=10, time_min=hoy)
            events_hoy = []
            for evento in calendar_events:
                inicio = evento['start'].get('dateTime', evento['start'].get('date'))
                try:
                    dt = datetime.fromisoformat(inicio.replace('Z', '+00:00'))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=settings.tz)
                    if dt <= fin_dia:
                        events_hoy.append(evento)
                except Exception:
                    pass

            # Verificar si hay algo pendiente
            pending_subtasks_total = sum(len(t.get_pending_subtasks()) for t in daily_tasks)
            total_pending = pending_subtasks_total + len(tasks_hoy) + len(events_hoy)

            if total_pending == 0:
                await bot.send_message(
                    chat_id=chat_id,
                    text="🌆 ¡Buenas tardes! ✅ Día completado. No tenés actividades pendientes."
                )
                return

            mensaje = "🌆 <b>Recordatorio vespertino (18:00)</b>\n"
            mensaje += "Actividades pendientes para completar hoy:\n\n"

            # Sub-tareas pendientes de listas diarias
            if daily_tasks:
                mensaje += "☑️ <b>Listas diarias:</b>\n"
                for tarea in daily_tasks:
                    pending_subs = tarea.get_pending_subtasks()
                    if pending_subs:
                        mensaje += f"  ▷ <b>{tarea.detalles}</b>:\n"
                        for sub in pending_subs:
                            mensaje += f"    ☐ {sub.texto}\n"
                        mensaje += "\n"

            # Tareas/recordatorios pendientes para hoy
            if tasks_hoy:
                mensaje += "📝 <b>Tareas y recordatorios de hoy:</b>\n"
                for tarea in tasks_hoy:
                    fecha_str = f" (<i>{self._format_fecha(tarea.fecha_hora.isoformat())}</i>)" if tarea.fecha_hora else ""
                    priority = " 🔴" if tarea.prioridad == 1 else " 🟢" if tarea.prioridad == -1 else ""
                    mensaje += f"  ☐ <b>[{tarea.tipo.value}]</b> {tarea.detalles}{fecha_str}{priority}\n"
                mensaje += "\n"

            # Eventos restantes de hoy
            if events_hoy:
                mensaje += "📅 <b>Eventos de hoy:</b>\n"
                for evento in events_hoy:
                    inicio = evento['start'].get('dateTime', evento['start'].get('date'))
                    fecha_str = self._format_fecha(inicio)
                    mensaje += f"  ▷ {evento.get('summary', 'Sin título')} (<i>{fecha_str}</i>)\n"
                mensaje += "\n"

            mensaje += "💪 ¡A darle a las pendientes!"

            await bot.send_message(
                chat_id=chat_id,
                text=mensaje,
                parse_mode=ParseMode.HTML
            )

            logger.info("evening_reminder_sent", chat_id=chat_id,
                       daily_tasks=len(daily_tasks), tasks=len(tasks_hoy), events=len(events_hoy))

        except Exception as e:
            logger.error("evening_reminder_failed", chat_id=chat_id, error=str(e), exc_info=True)
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Hubo un error generando el recordatorio vespertino."
                )
            except Exception:
                pass