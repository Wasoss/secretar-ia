"""
Agenda command handlers: notas, hoy, semana, buscar, tag, pendientes.
"""
import datetime
import re
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from handlers.base import BaseHandler, handle_errors, require_auth
from utils.formatters import (
    formatear_fecha_arg,
    _event_starts_today,
    _event_in_range,
)
from config.logging import get_logger
from config.settings import settings

logger = get_logger(__name__)


class AgendaCommandsHandler(BaseHandler):
    """Handler for agenda-related commands."""

    @handle_errors
    async def ver_notas(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /notas - Ver solo notas."""
        if not await require_auth(update):
            return

        chat_id = str(update.message.chat_id)
        services = await self.get_services()
        task_repo = services['task_repo']

        notas = await task_repo.get_notes(chat_id)

        if not notas:
            await update.message.reply_text("📔 No tenés notas guardadas actualmente.")
            return

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        mensaje = "📔 <b>Tus Notas:</b>\n\n"
        botones = []
        for nota in notas:
            tag_str = f" #{' #'.join(nota.tags)}" if nota.tags else ""
            mensaje += f"○ {nota.detalles}{tag_str}\n"
            botones.append([InlineKeyboardButton(f"🗑️ {nota.detalles[:25]}", callback_data=f"delete_{nota.id}")])

        teclado = InlineKeyboardMarkup(botones)
        await update.message.reply_text(text=mensaje, reply_markup=teclado, parse_mode=ParseMode.HTML)

    @handle_errors
    async def ver_hoy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /hoy - Ver agenda de hoy."""
        if not await require_auth(update):
            return

        chat_id = str(update.message.chat_id)
        hoy = datetime.datetime.now(settings.tz).replace(hour=0, minute=0, second=0, microsecond=0)
        manana = hoy + datetime.timedelta(days=1)

        services = await self.get_services()
        task_repo = services['task_repo']
        calendar_service = services['calendar_service']
        summary_service = services['summary_service']

        tasks = await task_repo.get_tasks_by_date_range(chat_id, hoy, manana)
        events = await calendar_service.get_upcoming_events(max_results=10, time_min=hoy)

        # Filtrar eventos de hoy
        events_hoy = [e for e in events if _event_starts_today(e, hoy)]

        await summary_service.send_custom_summary(
            context.bot, chat_id, tasks, events_hoy, "📅 Agenda de Hoy"
        )

    @handle_errors
    async def ver_semana(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /semana - Ver agenda de la semana."""
        if not await require_auth(update):
            return

        chat_id = str(update.message.chat_id)
        hoy = datetime.datetime.now(settings.tz).replace(hour=0, minute=0, second=0, microsecond=0)
        en_una_semana = hoy + datetime.timedelta(days=7)

        services = await self.get_services()
        task_repo = services['task_repo']
        calendar_service = services['calendar_service']
        summary_service = services['summary_service']

        tasks = await task_repo.get_tasks_by_date_range(chat_id, hoy, en_una_semana)
        events = await calendar_service.get_upcoming_events(max_results=20, time_min=hoy)

        await summary_service.send_custom_summary(
            context.bot, chat_id, tasks, events, "📅 Agenda de la Semana"
        )

    @handle_errors
    async def buscar(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /buscar - Buscar en tareas y notas."""
        if not await require_auth(update):
            return

        chat_id = str(update.message.chat_id)
        query = " ".join(context.args) if context.args else ""

        if not query:
            await update.message.reply_text("Uso: /buscar <texto a buscar>")
            return

        services = await self.get_services()
        task_repo = services['task_repo']
        calendar_service = services['calendar_service']
        summary_service = services['summary_service']

        tasks = await task_repo.search_tasks(chat_id, query)
        # También buscar en calendar (limitado)
        events = await calendar_service.get_upcoming_events(max_results=50)
        events_filtrados = [e for e in events if query.lower() in e.get('summary', '').lower()]

        await summary_service.send_custom_summary(
            context.bot, chat_id, tasks, events_filtrados, f"🔍 Resultados: '{query}'"
        )

    @handle_errors
    async def filtrar_tag(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /tag - Filtrar tareas por tag."""
        if not await require_auth(update):
            return

        chat_id = str(update.message.chat_id)
        tag = " ".join(context.args) if context.args else ""

        if not tag:
            await update.message.reply_text("Uso: /tag <etiqueta>")
            return

        services = await self.get_services()
        task_repo = services['task_repo']
        summary_service = services['summary_service']

        tasks = await task_repo.get_tasks_by_tag(chat_id, tag.lower())
        await summary_service.send_custom_summary(
            context.bot, chat_id, tasks, [], f"🏷️ Tag: #{tag}"
        )

    @handle_errors
    async def ver_hoy_corto(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /hoy_corto - Vista compacta de la agenda de hoy (solo títulos)."""
        if not await require_auth(update):
            return

        chat_id = str(update.message.chat_id)
        hoy = datetime.datetime.now(settings.tz).replace(hour=0, minute=0, second=0, microsecond=0)
        manana = hoy + datetime.timedelta(days=1)

        services = await self.get_services()
        task_repo = services['task_repo']
        calendar_service = services['calendar_service']

        tasks = await task_repo.get_tasks_by_date_range(chat_id, hoy, manana)
        events = await calendar_service.get_upcoming_events(max_results=10, time_min=hoy)

        # Filtrar eventos de hoy
        events_hoy = [e for e in events if _event_starts_today(e, hoy)]

        if not tasks and not events_hoy:
            await update.message.reply_text("📭 Hoy no tenés nada agendado.")
            return

        mensaje = f"📅 <b>Hoy (compacto)</b> — {hoy.strftime('%d/%m/%Y')}\n\n"

        if tasks:
            mensaje += "<b>📝 Tareas:</b>\n"
            for task in tasks:
                hora = formatear_fecha_arg(task.fecha_hora.isoformat()) if task.fecha_hora else "Sin hora"
                tags_str = f" #{' #'.join(task.tags)}" if task.tags else ""
                prioridad_str = " 🔴" if task.prioridad == 1 else (" 🟢" if task.prioridad == -1 else "")
                mensaje += f"  • {hora} — {task.detalles}{tags_str}{prioridad_str}\n"

        if events_hoy:
            if tasks:
                mensaje += "\n"
            mensaje += "<b>📅 Eventos:</b>\n"
            for event in events_hoy:
                start = event['start'].get('dateTime', event['start'].get('date'))
                try:
                    dt = datetime.datetime.fromisoformat(start.replace('Z', '+00:00'))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=settings.tz)
                    hora = dt.strftime("%H:%M")
                except Exception:
                    hora = "?"
                mensaje += f"  • {hora} — {event.get('summary', 'Sin título')}\n"

        await update.message.reply_text(text=mensaje, parse_mode=ParseMode.HTML)

    @handle_errors
    async def buscar(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /buscar - Buscar en tareas y notas con filtros combinados.

        Ejemplos:
        - /buscar mañana
        - /buscar #trabajo
        - /buscar #trabajo mañana
        - /buscar "reunión con Juan"
        """
        if not await require_auth(update):
            return

        chat_id = str(update.message.chat_id)
        query = " ".join(context.args) if context.args else ""

        if not query:
            await update.message.reply_text(
                "Uso: /buscar <texto> [#tag1 #tag2 ...]\n"
                "Ejemplos:\n"
                "  /buscar mañana\n"
                "  /buscar #trabajo\n"
                "  /buscar #trabajo mañana\n"
                "  /buscar \"reunión con Juan\""
            )
            return

        # Parsear tags del query (formato #tag)
        tags = re.findall(r'#(\w+)', query)
        # Remover tags del query para búsqueda de texto
        query_texto = re.sub(r'#\w+', '', query).strip()

        services = await self.get_services()
        task_repo = services['task_repo']
        calendar_service = services['calendar_service']
        summary_service = services['summary_service']

        if tags:
            # Buscar por tags Y texto (intersección)
            tasks_por_tag = []
            for tag in tags:
                tasks_tag = await task_repo.get_tasks_by_tag(chat_id, tag.lower())
                tasks_por_tag.append(set(t.id for t in tasks_tag))

            # Intersección de IDs
            if tasks_por_tag:
                ids_comunes = set.intersection(*tasks_por_tag)
                tasks = [t for t in await task_repo.search_tasks(chat_id, query_texto) if t.id in ids_comunes]
            else:
                tasks = await task_repo.search_tasks(chat_id, query_texto)
        else:
            # Solo búsqueda por texto
            tasks = await task_repo.search_tasks(chat_id, query_texto)

        # También buscar en calendar (limitado)
        events = await calendar_service.get_upcoming_events(max_results=50)
        events_filtrados = [e for e in events if query_texto.lower() in e.get('summary', '').lower()]

        # Filtrar eventos por tags si se especificaron
        if tags:
            events_filtrados = [
                e for e in events_filtrados
                if any(tag.lower() in (e.get('description', '') or '').lower()
                       or tag.lower() in e.get('summary', '').lower()
                       for tag in tags)
            ]

        await summary_service.send_custom_summary(
            context.bot, chat_id, tasks, events_filtrados,
            f"🔍 Resultados: '{query}'"
        )

    @handle_errors
    async def filtrar_tag(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /tag - Filtrar tareas por tag(s).

        Ejemplos:
        - /tag trabajo
        - /tag trabajo urgente
        - /tag #trabajo #urgente
        """
        if not await require_auth(update):
            return

        chat_id = str(update.message.chat_id)
        args = " ".join(context.args) if context.args else ""

        if not args:
            await update.message.reply_text(
                "Uso: /tag <etiqueta> [etiqueta2 ...]\n"
                "Ejemplos:\n"
                "  /tag trabajo\n"
                "  /tag trabajo urgente\n"
                "  /tag #trabajo #urgente"
            )
            return

        # Parsear tags (con o sin #)
        tags = []
        for arg in context.args:
            tag = arg.lstrip('#').lower()
            if tag:
                tags.append(tag)

        if len(tags) == 1:
            # Un solo tag - usar método existente
            services = await self.get_services()
            task_repo = services['task_repo']
            summary_service = services['summary_service']
            tasks = await task_repo.get_tasks_by_tag(chat_id, tags[0])
            await summary_service.send_custom_summary(
                context.bot, chat_id, tasks, [], f"🏷️ Tag: #{tags[0]}"
            )
        else:
            # Múltiples tags - intersección
            services = await self.get_services()
            task_repo = services['task_repo']
            summary_service = services['summary_service']

            tasks_por_tag = []
            for tag in tags:
                tasks_tag = await task_repo.get_tasks_by_tag(chat_id, tag)
                tasks_por_tag.append(set(t.id for t in tasks_tag))

            if tasks_por_tag:
                ids_comunes = set.intersection(*tasks_por_tag)
                all_tasks = []
                for tag in tags:
                    all_tasks.extend(await task_repo.get_tasks_by_tag(chat_id, tag))
                # Filtrar por IDs comunes y eliminar duplicados
                tasks_dict = {t.id: t for t in all_tasks}
                tasks = [tasks_dict[tid] for tid in ids_comunes if tid in tasks_dict]
            else:
                tasks = []

            await summary_service.send_custom_summary(
                context.bot, chat_id, tasks, [], f"🏷️ Tags: #{' #'.join(tags)}"
            )

    @handle_errors
    async def ver_pendientes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /pendientes - Ver tareas diarias con sub-items para tachar."""
        if not await require_auth(update):
            return

        chat_id = str(update.message.chat_id)
        services = await self.get_services()
        task_repo = services['task_repo']

        daily_tasks = await task_repo.get_daily_tasks(chat_id)

        if not daily_tasks:
            await update.message.reply_text(
                "☑️ No tenés listas de tareas diarias activas.\n"
                "Crea una diciendo: <i>\"Lista de hoy: estudiar, preparar clases, limpiar\"</i>",
                parse_mode=ParseMode.HTML
            )
            return

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from utils.formatters import format_daily_task

        mensaje = "☑️ <b>Tareas diarias pendientes:</b>\n\n"
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

        if botones:
            teclado = InlineKeyboardMarkup(botones)
            await update.message.reply_text(
                text=mensaje,
                reply_markup=teclado,
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(
                text=mensaje + "\n✅ ¡Todas las sub-tareas completadas!",
                parse_mode=ParseMode.HTML
            )


agenda_commands = AgendaCommandsHandler()
ver_notas = agenda_commands.ver_notas
ver_hoy = agenda_commands.ver_hoy
ver_hoy_corto = agenda_commands.ver_hoy_corto
ver_semana = agenda_commands.ver_semana
buscar = agenda_commands.buscar
filtrar_tag = agenda_commands.filtrar_tag
ver_pendientes = agenda_commands.ver_pendientes