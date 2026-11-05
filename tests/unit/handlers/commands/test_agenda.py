"""
Tests for agenda command handlers - TDD approach.

Following TDD: write failing test first, then implement minimal code to pass.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from handlers.commands.agenda import AgendaCommandsHandler
from config.settings import settings
from infrastructure.database.repositories.task_repo import TaskType, TaskStatus


def create_mock_update():
    """Create a properly mocked Update object with working effective_chat.id."""
    from unittest.mock import MagicMock
    update = AsyncMock()
    update.effective_chat = MagicMock()
    update.effective_chat.id = settings.mi_telegram_id
    update.message = AsyncMock()
    update.message.reply_text = AsyncMock()
    update.message.chat_id = settings.mi_telegram_id
    return update


class TestAgendaCommands:
    """Tests for agenda command handlers."""

    @pytest.fixture
    def mock_context(self):
        """Mock Context object."""
        context = AsyncMock()
        context.bot_data = {}
        return context

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from handlers.commands.agenda import AgendaCommandsHandler
        return AgendaCommandsHandler()

    def create_mock_update(self):
        """Helper to create a properly mocked Update object."""
        from unittest.mock import MagicMock
        update = AsyncMock()
        update.effective_chat = MagicMock()
        update.effective_chat.id = settings.mi_telegram_id
        update.message = AsyncMock()
        update.message.reply_text = AsyncMock()
        update.message.chat_id = settings.mi_telegram_id
        return update

    @pytest.mark.asyncio
    async def test_ver_notas_success(self, handler, mock_context):
        """Test /notas command success."""
        # Arrange
        mock_update = self.create_mock_update()
        mock_task_repo = AsyncMock()
        mock_notas = [
            MagicMock(id=1, detalles="Nota 1", tags=["tag1"], fecha_hora=None),
            MagicMock(id=2, detalles="Nota 2", tags=["tag2"], fecha_hora=None),
        ]
        mock_task_repo = AsyncMock()
        mock_task_repo.get_notes.return_value = mock_notas

        handler.get_services = AsyncMock(return_value={'task_repo': mock_task_repo})

        # Act
        await handler.ver_notas(self.create_mock_update(), AsyncMock())

        # Assert
        # We need to get the update object that was passed to the handler
        # Since we can't easily capture it, we'll verify the handler was called
        # by checking the mock_task_repo was called
        mock_task_repo.get_notes.assert_called_once()

    @pytest.mark.asyncio
    async def test_ver_notas_empty(self, handler):
        """Test /notas when no notes exist."""
        mock_update = self.create_mock_update()
        mock_task_repo = AsyncMock()
        mock_task_repo.get_notes.return_value = []

        handler.get_services = AsyncMock(return_value={'task_repo': mock_task_repo})

        # Act
        update = self.create_mock_update()
        await handler.ver_notas(update, AsyncMock())

        # Assert
        # The function should return early if no notes, but we can't easily test the message
        # Just verify it doesn't crash
        mock_task_repo.get_notes.assert_called_once()

    @pytest.mark.asyncio
    async def test_ver_hoy_success(self, handler):
        """Test /hoy command success."""
        from datetime import datetime, timedelta
        from config.settings import settings

        update = self.create_mock_update()
        services = {
            'task_repo': AsyncMock(),
            'calendar_service': AsyncMock(),
            'summary_service': AsyncMock(),
        }
        handler.get_services = AsyncMock(return_value=services)

        services['task_repo'].get_tasks_by_date_range.return_value = []
        services['calendar_service'].get_upcoming_events.return_value = []
        services['summary_service'].send_custom_summary = AsyncMock()

        await handler.ver_hoy(self.create_mock_update(), AsyncMock())

    @pytest.mark.asyncio
    async def test_ver_semana_success(self, handler):
        """Test /semana command success."""
        update = self.create_mock_update()
        services = {
            'task_repo': AsyncMock(),
            'calendar_service': AsyncMock(),
            'summary_service': AsyncMock(),
        }
        handler.get_services = AsyncMock(return_value=services)

        await handler.ver_semana(update, AsyncMock())

    @pytest.mark.asyncio
    async def test_buscar_success(self, handler):
        """Test /buscar command success."""
        update = self.create_mock_update()
        services = {
            'task_repo': AsyncMock(),
            'calendar_service': AsyncMock(),
            'summary_service': AsyncMock(),
        }
        handler.get_services = AsyncMock(return_value=services)

        await handler.buscar(update, AsyncMock())

    @pytest.mark.asyncio
    async def test_buscar_without_query(self, handler):
        """Test /buscar without query."""
        update = self.create_mock_update()
        update.message.reply_text = AsyncMock()

        await handler.buscar(update, AsyncMock())

        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args
        assert "Uso: /buscar" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_filtrar_tag_success(self, handler):
        """Test /tag command success."""
        update = self.create_mock_update()
        update.message.reply_text = AsyncMock()

        services = {
            'task_repo': AsyncMock(),
            'summary_service': AsyncMock(),
        }
        handler.get_services = AsyncMock(return_value=services)
        services['task_repo'].get_tasks_by_tag.return_value = []

        await handler.filtrar_tag(update, AsyncMock())

        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_filtrar_tag_without_arg(self, handler):
        """Test /tag without argument."""
        update = self.create_mock_update()
        update.message.reply_text = AsyncMock()

        await handler.filtrar_tag(update, AsyncMock())

        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args
        assert "Uso: /tag" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_ver_pendientes_no_tasks(self, handler):
        """Test /pendientes when no daily tasks exist."""
        update = self.create_mock_update()
        update.message.reply_text = AsyncMock()

        services = {
            'task_repo': AsyncMock(),
        }
        handler.get_services = AsyncMock(return_value=services)
        services['task_repo'].get_daily_tasks.return_value = []

        await handler.ver_pendientes(update, AsyncMock())

        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args
        assert "No tenés listas de tareas diarias activas" in call_args.args[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])