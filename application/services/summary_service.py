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
        Envía el resumen diario al usuario (6:50 AM).
        Muestra eventos HOY/MAÑANA, pendientes por tipo, y listas diarias con progreso.

        Args:
            bot: Instancia de Bot de Telegram
            chat_id: Chat ID del usuario
        """
        try:
            from datetime import datetime, timedelta
            from collections import defaultdict

            # Calcular rango: hoy 00:00 hasta mañana 23:59
            hoy = datetime.now(settings.tz).replace(hour=0, minute=0, second=0, microsecond=0)
            manana = hoy + timedelta(days=1)
            pasado_manana = hoy + timedelta(days=2)

            # Obtener datos en paralelo
            pending_tasks = await self._task_repo.get_pending(chat_id)
            daily_tasks = await self._task_repo.get_daily_tasks(chat_id)
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
                    events_hoy.append(evento)

            if not pending_tasks and not daily_tasks and not events_hoy and not events_manana:
                await bot.send_message(
                    chat_id=chat_id,
                    text="☀️ <b>Buen día</b>\n\nSin actividades programadas para hoy ni mañana.",
                    parse_mode=ParseMode.HTML
                )
                return

            mensaje = "☀️ <b>Buen día — Resumen matutino</b>\n\n"

            # ===== EVENTOS HOY =====
            if events_hoy:
                mensaje += "📅 <b>Hoy</b>\n"
                for evento in events_hoy:
                    inicio = evento['start'].get('dateTime', evento['start'].get('date'))
                    fecha_str = self._format_fecha(inicio)
                    rec_indicator = " 🔄" if evento.get('recurrence') else ""
                    mensaje += f"  ▷ {evento.get('summary', 'Sin título')} — <i>{fecha_str}</i>{rec_indicator}\n"
                mensaje += "\n"

            # ===== EVENTOS MAÑANA =====
            if events_manana:
                mensaje += "📅 <b>Mañana</b>\n"
                for evento in events_manana:
                    inicio = evento['start'].get('dateTime', evento['start'].get('date'))
                    fecha_str = self._format_fecha(inicio)
                    rec_indicator = " 🔄" if evento.get('recurrence') else ""
                    mensaje += f"  ▷ {evento.get('summary', 'Sin título')} — <i>{fecha_str}</i>{rec_indicator}\n"
                mensaje += "\n"

            # ===== TAREAS PENDIENTES - Por tipo =====
            if pending_tasks:
                tareas_por_tipo = defaultdict(list)
                for t in pending_tasks:
                    tareas_por_tipo[t.tipo].append(t)

                botones = []
                iconos = {'EVENTO': '📅', 'RECORDATORIO': '⏰', 'NOTA': '📔'}

                for tipo, tareas in tareas_por_tipo.items():
                    icono = iconos.get(tipo.value, '📝')
                    mensaje += f"{icono} <b>{tipo.value}s</b>\n"
                    for tarea in tareas:
                        priority_indicator = " 🔴" if tarea.prioridad == 1 else " 🟢" if tarea.prioridad == -1 else ""
                        rec_indicator = " 🔄" if tarea.recurrencia else ""
                        tag_str = f" #{' #'.join(tarea.tags)}" if tarea.tags else ""
                        fecha_str = f" — <i>{self._format_fecha(tarea.fecha_hora.isoformat())}</i>" if tarea.fecha_hora else ""
                        mensaje += f"  ☐ {tarea.detalles}{fecha_str}{priority_indicator}{rec_indicator}{tag_str}\n"
                        botones.append([InlineKeyboardButton(f"✅ {tarea.detalles[:30]}", callback_data=f"complete_{tarea.id}")])
                    mensaje += "\n"

            # ===== LISTAS DIARIAS con sub-items =====
            if daily_tasks:
                mensaje += "☑️ <b>Listas de hoy</b>\n"
                for tarea in daily_tasks:
                    pending_subs = tarea.get_pending_subtasks()
                    completed_subs = tarea.get_completed_subtasks()
                    total_subs = len(tarea.subtareas)
                    progress = f" ({len(completed_subs)}/{total_subs})" if total_subs > 0 else ""

                    mensaje += f"  ▷ <b>{tarea.detalles}</b>{progress}\n"
                    for sub in pending_subs:
                        botones.append([InlineKeyboardButton(f"☑️ {sub.texto[:35]}", callback_data=f"subtask_{tarea.id}_{sub.id}")])
                    for sub in completed_subs:
                        mensaje += f"    ~~{sub.texto}~~ ✅\n"
                mensaje += "\n"

            # Cierre conciso
            if events_hoy or tasks_hoy := [t for t in pending_tasks if t.fecha_hora and t.fecha_hora < manana]:
                mensaje += "—\nOrganice su jornada según prioridad."

            if botones:
                teclado = InlineKeyboardMarkup(botones)
                await bot.send_message(chat_id=chat_id, text=mensaje, reply_markup=teclado, parse_mode=ParseMode.HTML)
            else:
                await bot.send_message(chat_id=chat_id, text=mensaje, parse_mode=ParseMode.HTML)

            logger.info("daily_summary_sent", chat_id=chat_id,
                       tasks=len(pending_tasks), daily_tasks=len(daily_tasks),
                       events=len(events_hoy) + len(events_manana))

            await self._send_proactive_suggestion(bot, chat_id, pending_tasks, calendar_events)

        except Exception as e:
            logger.error("daily_summary_failed", chat_id=chat_id, error=str(e), exc_info=True)
            try:
                await bot.send_message(chat_id=chat_id, text="⚠️ Error generando resumen diario.")
            except Exception:
                pass
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
        Solo muestra items PENDIENTES (no completados).

        Args:
            bot: Instancia de Bot de Telegram
            chat_id: Chat ID del usuario
        """
        try:
            from datetime import datetime, timedelta

            # Calcular fin de día (23:59)
            hoy = datetime.now(settings.tz).replace(hour=0, minute=0, second=0, microsecond=0)
            fin_dia = hoy + timedelta(days=1) - timedelta(seconds=1)

            # Obtener tareas diarias (solo sus sub-items pendientes)
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

            # Contar solo PENDIENTES
            pending_subtasks_total = sum(len(t.get_pending_subtasks()) for t in daily_tasks)
            total_pending = pending_subtasks_total + len(tasks_hoy) + len(events_hoy)

            if total_pending == 0:
                await bot.send_message(
                    chat_id=chat_id,
                    text="🌆 <b>Recordatorio vespertino</b>\n\n✅ No hay actividades pendientes para hoy.",
                    parse_mode=ParseMode.HTML
                )
                return

            mensaje = "🌆 <b>Recordatorio vespertino</b>\n"
            mensaje += "Actividades pendientes para completar hoy:\n\n"

            # Sub-tareas pendientes de listas diarias
            if daily_tasks:
                for tarea in daily_tasks:
                    pending_subs = tarea.get_pending_subtasks()
                    if pending_subs:
                        mensaje += f"\n☑️ <b>{tarea.detalles}</b>\n"
                        for sub in pending_subs:
                            mensaje += f"  ☐ {sub.texto}\n"

            # Tareas y recordatorios pendientes para hoy
            if tasks_hoy:
                mensaje += "\n📝 <b>Pendientes con hora:</b>\n"
                for tarea in tasks_hoy:
                    fecha_str = f" — <i>{self._format_fecha(tarea.fecha_hora.isoformat())}</i>" if tarea.fecha_hora else ""
                    priority = " 🔴" if tarea.prioridad == 1 else " 🟢" if tarea.prioridad == -1 else ""
                    mensaje += f"  ☐ {tarea.detalles}{fecha_str}{priority}\n"

            # Eventos restantes de hoy
            if events_hoy:
                mensaje += "\n📅 <b>Eventos:</b>\n"
                for evento in events_hoy:
                    inicio = evento['start'].get('dateTime', evento['start'].get('date'))
                    fecha_str = self._format_fecha(inicio)
                    mensaje += f"  ▷ {evento.get('summary', 'Sin título')} — <i>{fecha_str}</i>\n"

            mensaje += "\n—\nQuedan <b>pocas horas</b>. Priorice lo urgente."

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
                    text="⚠️ Error generando recordatorio vespertino."
                )
            except Exception:
                pass