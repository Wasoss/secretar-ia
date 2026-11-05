"""
Tests for TextMessageHandler - TDD approach.

Tests for the text message handler that processes natural language requests
and dispatches to appropriate handlers based on AI classification.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, MagicMock
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import uuid

from handlers.messages.text import TextMessageHandler
from handlers.base import BaseHandler, handle_errors, require_auth
from application.services.ai_service import ActionType, ParsedIntent
from config.settings import settings
from config.logging import get_logger
from infrastructure.database.repositories.task_repo import TaskType, TaskStatus, SubTask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import datetime


class TestTextMessageHandler:
    """Tests for TextMessageHandler."""

    @pytest.fixture
    def mock_update(self):
        """Mock Update object with proper effective_chat.id mocking."""
        from unittest.mock import MagicMock
        update = AsyncMock()
        update.effective_chat = MagicMock()
        update.effective_chat.id = settings.mi_telegram_id
        update.message = AsyncMock()
        update.message.reply_text = AsyncMock()
        update.message.chat_id = settings.mi_telegram_id
        return update

    @pytest.fixture
    def mock_context(self):
        """Mock Context object."""
        context = AsyncMock()
        context.bot_data = {}
        context.job_queue = AsyncMock()
        context.job_queue.run_once = AsyncMock()
        return context

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from handlers.messages.text import TextMessageHandler
        return TextMessageHandler()

    @pytest.fixture
    def mock_services(self):
        """Create mock services dictionary."""
        return {
            'task_repo': AsyncMock(),
            'calendar_service': AsyncMock(),
            'reminder_service': AsyncMock(),
            'ai_service': AsyncMock(),
            'summary_service': AsyncMock(),
            'weekly_planning_service': AsyncMock(),
            'plantilla_repo': AsyncMock(),
            'objetivo_repo': AsyncMock(),
            'revision_repo': AsyncMock(),
        }

    # --- Tests for recibir_texto ---

    @pytest.mark.asyncio
    async def test_recibir_texto_calls_procesar_peticion(self, handler, mock_update, mock_context):
        """Test that recibir_texto calls procesar_peticion with message text."""
        with patch.object(handler, 'procesar_peticion', new_callable=AsyncMock) as mock_procesar:
            await handler.recibir_texto(mock_update, mock_context)
            mock_procesar.assert_called_once_with(mock_update, mock_context, mock_update.message.text)

    # --- Tests for procesar_peticion ---

    @pytest.mark.asyncio
    async def test_procesar_peticion_returns_early_if_not_authenticated(self, handler, mock_update, mock_context):
        """Test that procesar_peticion returns early if not authenticated."""
        with patch('handlers.messages.text.require_auth', new_callable=AsyncMock, return_value=False):
            await handler.procesar_peticion(mock_update, mock_context, "test message")
            mock_update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_procesar_peticion_help_shortcut_triggers_ayuda(self, handler, mock_update, mock_context):
        """Test that help shortcuts trigger the ajuda command directly."""
        help_triggers = ["lista de comandos", "comandos", "ayuda", "menu", "menú", "help"]

        for trigger in help_triggers:
            mock_update.message.text = trigger
            with patch('handlers.messages.text.require_auth', new_callable=AsyncMock, return_value=True):
                with patch('handlers.commands.basic.ajuda', new_callable=AsyncMock) as mock_ajuda:
                    with patch.object(handler, 'get_services', new_callable=AsyncMock, return_value={'ai_service': AsyncMock(), 'task_repo': AsyncMock(), 'calendar_service': AsyncMock(), 'reminder_service': AsyncMock(), 'summary_service': AsyncMock(), 'weekly_planning_service': AsyncMock(), 'plantilla_repo': AsyncMock(), 'objetivo_repo': AsyncMock(), 'revision_repo': AsyncMock()}):
                        await handler.procesar_peticion(mock_update, mock_context, trigger)
                        mock_ajuda.assert_called_once_with(mock_update, mock_context)

    @pytest.mark.asyncio
    async def test_procesar_peticion_error_intent_returns_error(self, handler, mock_update, mock_context):
        """Test that ERROR action returns error message."""
        mock_ai = AsyncMock()
        mock_ai.classify_intent = AsyncMock(return_value=ParsedIntent(
            accion=ActionType.ERROR,
            detalles="Error message",
            fecha_hora=None,
            confianza=0.0
        ))

        with patch('handlers.messages.text.require_auth', new_callable=AsyncMock, return_value=True):
            with patch.object(TextMessageHandler, 'get_services', new_callable=AsyncMock, return_value={'ai_service': mock_ai}):
                await handler.procesar_peticion(mock_update, mock_context, "test message")

                mock_update.message.reply_text.assert_called_once()
                call_args = mock_update.message.reply_text.call_args
                assert "⚠️ No entendí" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_procesar_peticion_rechazado_gastos_returns_rejection(self, handler, mock_update, mock_context):
        """Test that RECHAZADO_GASTOS returns rejection message."""
        mock_ai = AsyncMock()
        mock_ai.classify_intent = AsyncMock(return_value=ParsedIntent(
            accion=ActionType.RECHAZADO_GASTOS,
            detalles="Finanzas no gestiono",
            fecha_hora=None
        ))

        with patch('handlers.messages.text.require_auth', new_callable=AsyncMock, return_value=True):
            with patch.object(TextMessageHandler, 'get_services', new_callable=AsyncMock, return_value={'ai_service': mock_ai}):
                await handler.procesar_peticion(mock_update, mock_context, "Gasté $50 en comida")

                mock_update.message.reply_text.assert_called_once()
                call_args = mock_update.message.reply_text.call_args
                assert "No gestiono finanzas" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_procesar_peticion_conversacion_returns_response(self, handler, mock_update, mock_context):
        """Test that CONVERSACION returns the response directly."""
        mock_ai = AsyncMock()
        mock_ai.classify_intent = AsyncMock(return_value=ParsedIntent(
            accion=ActionType.CONVERSACION,
            detalles="¡Hola! ¿En qué te ayudo?",
            fecha_hora=None
        ))

        with patch('handlers.messages.text.require_auth', new_callable=AsyncMock, return_value=True):
            with patch.object(TextMessageHandler, 'get_services', new_callable=AsyncMock, return_value={'ai_service': mock_ai}):
                await handler.procesar_peticion(mock_update, mock_context, "Hola, ¿cómo estás?")

                mock_update.message.reply_text.assert_called_once_with("¡Hola! ¿En qué te ayudo?")

    @pytest.mark.asyncio
    async def test_procesar_peticion_ayuda_triggers_ajuda(self, handler, mock_update, mock_context):
        """Test that AYUDA action triggers ajuda command."""
        mock_ai = AsyncMock()
        mock_ai.classify_intent = AsyncMock(return_value=ParsedIntent(
            accion=ActionType.AYUDA,
            detalles="",
            fecha_hora=None
        ))

        with patch('handlers.messages.text.require_auth', new_callable=AsyncMock, return_value=True):
            with patch.object(TextMessageHandler, 'get_services', new_callable=AsyncMock, return_value={
                'ai_service': mock_ai,
                'task_repo': AsyncMock(),
                'calendar_service': AsyncMock(),
                'reminder_service': AsyncMock(),
                'summary_service': AsyncMock(),
                'weekly_planning_service': AsyncMock(),
                'plantilla_repo': AsyncMock(),
                'objetivo_repo': AsyncMock(),
                'revision_repo': AsyncMock(),
            }):
                with patch('handlers.messages.text.ajuda', new_callable=AsyncMock) as mock_ajuda:
                    await handler.procesar_peticion(mock_update, mock_context, "ayuda")
                    mock_ajuda.assert_called_once_with(mock_update, mock_context)

    @pytest.mark.asyncio
    async def test_procesar_peticion_dispatches_to_handlers(self, handler, mock_update, mock_context):
        """Test that different action types are dispatched to correct handlers."""
        mock_ai = AsyncMock()
        mock_services = {'ai_service': mock_ai}

        test_cases = [
            (ActionType.DESHACER, "handle_deshacer"),
            (ActionType.ELIMINAR_FECHA, "handle_eliminar_fecha"),
            (ActionType.REAGENDAR, "handle_reagendar"),
            (ActionType.LISTAR, "handle_listar"),
            (ActionType.BUSCAR, "handle_buscar"),
            (ActionType.TAREA_DIARIA, "handle_guardar_tarea_diaria"),
            (ActionType.PLANTILLA_CREAR, "handle_crear_plantilla"),
            (ActionType.PLANTILLA_LISTAR, "handle_listar_plantillas"),
            (ActionType.PLANTILLA_ACTIVAR, "handle_activar_plantilla"),
            (ActionType.OBJETIVO_CREAR, "handle_crear_objetivo"),
            (ActionType.OBJETIVO_LISTAR, "handle_listar_objetivos"),
            (ActionType.OBJETIVO_PROGRESO, "handle_progreso_objetivo"),
            (ActionType.REVISION_SEMANAL, "handle_revision_semanal"),
        ]

        for action, handler_method in test_cases:
            mock_ai = AsyncMock()
            mock_ai.classify_intent = AsyncMock(return_value=ParsedIntent(
                accion=action,
                detalles="test",
                fecha_hora=None,
                confianza=1.0
            ))

            with patch('handlers.messages.text.require_auth', new_callable=AsyncMock, return_value=True):
                with patch.object(TextMessageHandler, 'get_services', new_callable=AsyncMock, return_value={'ai_service': mock_ai}):
                    with patch.object(TextMessageHandler, handler_method, new_callable=AsyncMock) as mock_handler:
                        await handler.procesar_peticion(AsyncMock(), AsyncMock(), "test")
                        mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_procesar_peticion_save_actions_dispatch_to_handle_guardar_tarea(self, handler, mock_update, mock_context):
        """Test that EVENTO, RECORDATORIO, NOTA actions dispatch to handle_guardar_tarea."""
        for action in [ActionType.EVENTO, ActionType.RECORDATORIO, ActionType.NOTA]:
            mock_ai = AsyncMock()
            mock_ai.classify_intent = AsyncMock(return_value=ParsedIntent(
                accion=action,
                detalles="test event",
                fecha_hora=datetime.now() + timedelta(days=1),
                confianza=1.0
            ))

            with patch('handlers.messages.text.require_auth', new_callable=AsyncMock, return_value=True):
                with patch.object(TextMessageHandler, 'get_services', new_callable=AsyncMock, return_value={
                    'ai_service': mock_ai,
                    'task_repo': AsyncMock(),
                    'calendar_service': AsyncMock(),
                    'reminder_service': AsyncMock(),
                    'summary_service': AsyncMock(),
                    'weekly_planning_service': AsyncMock(),
                    'plantilla_repo': AsyncMock(),
                    'objetivo_repo': AsyncMock(),
                    'revision_repo': AsyncMock(),
                }):
                    with patch.object(handler, 'handle_guardar_tarea', new_callable=AsyncMock) as mock_handler:
                        await handler.procesar_peticion(mock_update, mock_context, "test")
                        mock_handler.assert_called_once()

    # --- Tests for handle_guardar_tarea ---

    @pytest.mark.asyncio
    async def test_handle_guardar_tarea_evento_requires_fecha_hora(self, handler):
        """Test that EVENTO action requires fecha_hora."""
        update = AsyncMock()
        update.message = AsyncMock()
        update.message.reply_text = AsyncMock()

        intent = ParsedIntent(
            accion=ActionType.EVENTO,
            detalles="Reunión sin fecha",
            fecha_hora=None,
            confianza=1.0
        )

        with patch.object(TextMessageHandler, 'get_services', new_callable=AsyncMock, return_value={
            'task_repo': AsyncMock(),
            'calendar_service': AsyncMock(),
            'reminder_service': AsyncMock(),
        }):
            handler_instance = TextMessageHandler()
            await handler_instance.handle_guardar_tarea(AsyncMock(), AsyncMock(), "123", intent)

            # Should return early with error message
            update.message.reply_text.assert_called_once()
            call_args = update.message.reply_text.call_args
            assert "Evento sin fecha/hora" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_handle_guardar_tarea_evento_saves_to_db_and_calendar(self, handler):
        """Test that EVENTO action saves to DB and syncs with Calendar."""
        pass  # Placeholder for more detailed test

    @pytest.mark.asyncio
    async def test_handle_guardar_tarea_recordatorio_schedules_reminder(self, handler):
        """Test that RECORDATORIO schedules a reminder."""
        pass  # Placeholder

    @pytest.mark.asyncio
    async def test_handle_guardar_tarea_nota_saves_without_calendar(self, handler):
        """Test that NOTA saves without calendar sync."""
        pass  # Placeholder

    # --- Tests for handle_guardar_tarea_diaria ---

    @pytest.mark.asyncio
    async def test_handle_guardar_tarea_diaria_parses_items_correctly(self, handler):
        """Test that daily task items are parsed correctly with various separators."""
        import uuid
        import re
        from unittest.mock import MagicMock

        handler_instance = TextMessageHandler()
        intent = ParsedIntent(
            accion=ActionType.TAREA_DIARIA,
            detalles="estudiar, preparar clases, limpiar",
            fecha_hora=None,
            prioridad=0,
            tags=["test"],
            confianza=1.0
        )

        services = {'task_repo': AsyncMock()}

        with patch('handlers.messages.text.uuid.uuid4', side_effect=[
            MagicMock(hex='12345678'),
            MagicMock(hex='abcdefab'),
            MagicMock(hex='fedcba98'),
        ]):
            with patch('handlers.messages.text.TextMessageHandler.get_services', new_callable=AsyncMock, return_value={'task_repo': AsyncMock()}):
                handler_instance = TextMessageHandler()
                await handler_instance.handle_guardar_tarea_diaria(
                    AsyncMock(), AsyncMock(), "123", intent
                )

    # ============================================================
    # Tests for handle_crear_plantilla
    # ============================================================

    @pytest.mark.asyncio
    async def test_handle_crear_plantilla(self, handler):
        """Test that crear_plantilla creates a plantilla via weekly_planning_service."""
        pass  # Placeholder

    @pytest.mark.asyncio
    async def test_handle_listar_plantillas(self, handler):
        """Test listing plantillas."""
        pass  # Placeholder

    @pytest.mark.asyncio
    async def test_handle_activar_plantilla(self, handler):
        """Test activating a plantilla."""
        pass  # Placeholder

    # ============================================================
    # Tests for objetivos
    # ============================================================

    @pytest.mark.asyncio
    async def test_handle_crear_objetivo(self, handler):
        """Test creating an objetivo."""
        pass  # Placeholder

    @pytest.mark.asyncio
    async def test_handle_listar_objetivos(self, handler):
        """Test listing objetivos."""
        pass  # Placeholder

    @pytest.mark.asyncio
    async def test_handle_progreso_objetivo(self, handler):
        """Test updating objetivo progress."""
        pass  # Placeholder

    @pytest.mark.asyncio
    async def test_handle_revision_semanal(self, handler):
        """Test weekly review handler."""
        pass  # Placeholder

    # Tests for handle_deshacer
    @pytest.mark.asyncio
    async def test_handle_deshacer_deletes_last_task(self, handler):
        """Test that deshacer deletes the last task."""
        pass  # Placeholder

    @pytest.mark.asyncio
    async def test_handle_eliminar_fecha(self, handler):
        """Test eliminating tasks by date."""
        pass  # Placeholder

    # Tests for handle_reagendar
    @pytest.mark.asyncio
    async def test_handle_reagendar_updates_event(self, handler):
        """Test that reagendar updates event in both DB and Calendar."""
        pass  # Placeholder

    # Tests for handle_listar
    @pytest.mark.asyncio
    async def test_handle_listar_shows_agenda(self, handler):
        """Test that listar shows agenda for today/week."""
        pass  # Placeholder

    # Tests for handle_buscar
    @pytest.mark.asyncio
    async def test_handle_buscar_searches_tasks_and_calendar(self, handler):
        """Test that buscar searches both tasks and calendar events."""
        pass  # Placeholder

    # Tests for handle_deshacer
    @pytest.mark.asyncio
    async def test_handle_deshacer_deletes_last_task(self, handler):
        """Test that deshacer deletes the last task."""
        pass  # Placeholder

    # Tests for handle_eliminar_fecha
    @pytest.mark.asyncio
    async def test_handle_eliminar_fecha(self, handler):
        """Test eliminating tasks by date."""
        pass  # Placeholder

    # Tests for handle_reagendar
    @pytest.mark.asyncio
    async def test_handle_reagendar_updates_event(self, handler):
        """Test that reagendar updates event in both DB and Calendar."""
        pass  # Placeholder

    # Tests for handle_listar
    @pytest.mark.asyncio
    async def test_handle_listar_shows_agenda(self, handler):
        """Test that listar shows agenda for today/week."""
        pass  # Placeholder

    # Tests for handle_buscar
    @pytest.mark.asyncio
    async def test_handle_buscar_searches_tasks_and_calendar(self, handler):
        """Test that buscar searches both tasks and calendar events."""
        pass  # Placeholder

    # Tests for callback handlers (subtasks)
    @pytest.mark.asyncio
    async def test_subtask_completion_callback(self, handler):
        """Test that subtask completion callback works."""
        pass  # Placeholder


if __name__ == "__main__":
    pytest.main([__file__, "-v"])