"""
Tests for basic command handlers - TDD approach.

Following TDD: write failing test first, then implement minimal code to pass.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from zoneinfo import ZoneInfo

from handlers.commands.basic import BasicCommandsHandler
from config.settings import settings


class TestBasicCommands:
    """Tests for basic command handlers."""

    @pytest.fixture
    def mock_update(self):
        """Mock Update object."""
        update = AsyncMock()
        update.effective_chat.id = 123
        update.message = AsyncMock()
        update.message.reply_text = AsyncMock()
        update.message.chat_id = 123
        return update

    @pytest.fixture
    def mock_context(self):
        """Mock Context object."""
        context = AsyncMock()
        context.job_queue = AsyncMock()
        context.job_queue.run_once = AsyncMock()
        context.bot_data = {}
        return context

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return BasicCommandsHandler()

    @pytest.mark.asyncio
    async def test_start_command_success(self, handler, mock_update, mock_context):
        """Test /start command with authorized user."""
        # Arrange
        mock_update.effective_chat.id = settings.mi_telegram_id

        # Act
        await handler.start(mock_update, mock_context)

        # Assert
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "Hola. Soy tu Secretar-IA" in call_args.args[0]
        assert "Secretar-IA" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_start_command_unauthorized(self, handler, mock_update, mock_context):
        """Test /start command with unauthorized user."""
        # Arrange
        mock_update.effective_chat.id = 999  # Different from settings.mi_telegram_id

        # Act
        await handler.start(mock_update, mock_context)

        # Assert
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "Acceso denegado" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_start_saves_chat_id(self, handler, mock_update, mock_context):
        """Test that /start saves chat_id in job_queue."""
        # Arrange
        mock_update.effective_chat.id = settings.mi_telegram_id
        mock_update.message.chat_id = 123

        # Act
        await handler.start(mock_update, mock_context)

        # Assert - job_queue.run_once should have been called
        mock_context.job_queue.run_once.assert_called_once()
        call_args = mock_context.job_queue.run_once.call_args
        # First arg should be the callback function, second should be when (1 second)
        assert call_args.args[1] == 1
        assert call_args.kwargs.get('data') == '123'

    @pytest.mark.asyncio
    async def test_ajuda_command_success(self, handler, mock_update, mock_context):
        """Test /ayuda command with authorized user."""
        # Arrange
        mock_update.effective_chat.id = settings.mi_telegram_id

        # Act
        await handler.ajuda(mock_update, mock_context)

        # Assert
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "Guía de Secretar-IA" in call_args.args[0]
        assert "Eventos (Google Calendar)" in call_args.args[0]
        assert "Recordatorios" in call_args.args[0]
        assert "Notas" in call_args.args[0]
        assert "Tareas diarias" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_ajuda_command_unauthorized(self, handler, mock_update, mock_context):
        """Test /ayuda command with unauthorized user."""
        # Arrange
        mock_update.effective_chat.id = 999

        # Act
        await handler.ajuda(mock_update, mock_context)

        # Assert
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "Acceso denegado" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_status_command(self, handler, mock_update, mock_context):
        """Test /status command."""
        # Arrange
        mock_update.effective_chat.id = settings.mi_telegram_id

        # Act
        await handler.status(mock_update, mock_context)

        # Assert
        mock_update.message.reply_text.assert_called_once_with("✅ Bot operativo")

    @pytest.mark.asyncio
    async def test_ping_command(self, handler, mock_update, mock_context):
        """Test /ping command."""
        # Arrange
        mock_update.effective_chat.id = settings.mi_telegram_id

        # Act
        await handler.ping(mock_update, mock_context)

        # Assert
        mock_update.message.reply_text.assert_called_once_with("🏓 Pong! Bot funcionando correctamente.")

    @pytest.mark.asyncio
    async def test_test_sistema_command(self, handler, mock_update, mock_context):
        """Test /test command."""
        # Arrange
        mock_update.effective_chat.id = settings.mi_telegram_id

        # Mock services by patching the handler's get_services method
        mock_task_repo = AsyncMock()
        mock_task_repo.get_pending = AsyncMock(return_value=[MagicMock()])

        mock_calendar = AsyncMock()
        mock_calendar.get_upcoming_events = AsyncMock(return_value=[MagicMock()])

        mock_ai = AsyncMock()
        mock_ai.is_available = MagicMock(return_value=True)
        mock_ai._client = MagicMock()
        mock_ai._client._model = "test-model"

        # Patch the handler's get_services method directly
        original_get_services = handler.get_services
        handler.get_services = AsyncMock(return_value={
            'task_repo': mock_task_repo,
            'calendar_service': mock_calendar,
            'ai_service': mock_ai,
        })

        try:
            # Act
            await handler.test_sistema(mock_update, mock_context)

            # Assert
            mock_update.message.reply_text.assert_called_once()
            call_args = mock_update.message.reply_text.call_args
            assert "Diagnóstico del Sistema" in call_args.args[0]
            assert "Base de datos" in call_args.args[0]
            assert "Google Calendar" in call_args.args[0]
            assert "Motor IA" in call_args.args[0]
        finally:
            handler.get_services = original_get_services


if __name__ == "__main__":
    pytest.main([__file__, "-v"])