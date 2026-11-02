"""
Callback handlers for completing/deleting tasks and subtasks.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from handlers.base import BaseHandler, handle_errors
from config.settings import settings
from config.logging import get_logger
from utils.formatters import format_daily_task

logger = get_logger(__name__)


class CompletionCallbackHandler(BaseHandler):
    """Handler for callback queries: complete, delete, subtask."""

    @handle_errors
    async def callback_completar(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Callback para botones de completar/borrar tareas y sub-tareas."""
        query = update.callback_query
        if str(query.message.chat_id) != settings.mi_telegram_id:
            return

        data = query.data
        await query.answer()

        services = await self.get_services()
        task_repo = services['task_repo']
        calendar_service = services['calendar_service']

        if data.startswith("complete_"):
            await self._handle_complete(query, data, task_repo)

        elif data.startswith("delete_"):
            await self._handle_delete(query, data, task_repo, calendar_service)

        elif data.startswith("subtask_"):
            await self._handle_subtask(query, data, task_repo)

    async def _handle_complete(self, query, data: str, task_repo):
        """Handle complete_ callback."""
        task_id = int(data.split("_")[1])
        await task_repo.complete(task_id)
        await query.answer("¡Completada! ✅")

        # Actualizar teclado
        teclado_actual = query.message.reply_markup.inline_keyboard
        nuevo_teclado = [[btn] for fila in teclado_actual for btn in fila if btn.callback_data != data]

        if nuevo_teclado:
            await query.edit_message_reply_markup(InlineKeyboardMarkup(nuevo_teclado))
        else:
            await query.edit_message_text(text="¡Todas las tareas de esta lista están listas! 🎉")

    async def _handle_delete(self, query, data: str, task_repo, calendar_service):
        """Handle delete_ callback."""
        task_id = int(data.split("_")[1])
        task = await task_repo.get_task_by_id(task_id)
        if task and task.calendar_event_id:
            await calendar_service.delete_event(task.calendar_event_id)
        await task_repo.delete_by_id(task_id)
        await query.answer("🗑️ Eliminada")

    async def _handle_subtask(self, query, data: str, task_repo):
        """Handle subtask_ callback."""
        # Formato: subtask_{task_id}_{subtask_id}
        parts = data.split("_")
        if len(parts) >= 3:
            task_id = int(parts[1])
            subtask_id = parts[2]
            success = await task_repo.complete_subtask(task_id, subtask_id)
            if success:
                await query.answer("¡Sub-tarea completada! ✅")
                # Refrescar el mensaje para mostrar el estado actualizado
                task = await task_repo.get_task_by_id(task_id)
                if task:
                    # Re-construir el mensaje con estado actualizado
                    pending_subs = task.get_pending_subtasks()
                    completed_subs = task.get_completed_subtasks()
                    total_subs = len(task.subtareas)

                    mensaje = f"☑️ <b>{task.detalles}</b> ({len(completed_subs)}/{total_subs})\n\n"

                    botones = []
                    for sub in pending_subs:
                        botones.append([
                            InlineKeyboardButton(
                                f"☑️ {sub.texto[:35]}",
                                callback_data=f"subtask_{task_id}_{sub.id}"
                            )
                        ])
                    for sub in completed_subs:
                        mensaje += f"  ~~{sub.texto}~~ ✅\n"

                    if botones:
                        teclado = InlineKeyboardMarkup(botones)
                        await query.edit_message_text(
                            text=mensaje,
                            reply_markup=teclado,
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        await query.edit_message_text(
                            text=mensaje + "\n✅ ¡Todas las sub-tareas completadas!",
                            parse_mode=ParseMode.HTML
                        )
            else:
                await query.answer("❌ No se pudo completar la sub-tarea")
        else:
            await query.answer("❌ Formato de callback inválido")


completion_callback = CompletionCallbackHandler()
callback_completar = completion_callback.callback_completar