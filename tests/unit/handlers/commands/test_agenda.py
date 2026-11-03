"""
Tests for agenda command handlers - TDD approach.

Following TDD: write failing test first, then implement minimal code to pass.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config.settings import settings


# Mock settings.mi_telegram_id for all tests
@pytest.fixture(autouse=True)
def mock_settings():
    """Mock settings.mi_telegram_id for tests."""
    with patch.object(settings, 'mi_telegram_id', '123456789'):
        yield


@pytest.fixture
def mock_update():
    """Mock Update object."""
    update = AsyncMock()
    update.effective_chat = AsyncMock()
    type(update.effective_chat).id = PropertyMock(return_value="123456789")
    update.message = AsyncMock()
    update.message.reply_text = AsyncMock()
    update.message.chat_id = "123456789"
    return update

@pytest.fixture
def mock_context():
    """Mock Context object."""
    context = AsyncMock()
    context.job_queue = AsyncMock()
    context.args = []
    return context

@pytest.fixture
def mock_services():
    """Create mock services."""
    mock_task_repo = AsyncMock()
    mock_calendar = AsyncMock()
    mock_summary = AsyncMock()
    return mock_task_repo, mock_calendar, AsyncMock()

@pytest.fixture
def handler(mock_services):
    """Create handler instance with mocked services."""
    from handlers.commands.agenda import AgendaCommandsHandler
    handler = AgendaCommandsHandler()
    mock_task_repo, mock_calendar, mock_summary = mock_services
    handler.get_services = AsyncMock(return_value={
        'task_repo': mock_services[0],
        'calendar_service': mock_services[1],
        'summary_service': mock_services[2],
    })
    return handler


class TestAgendaCommands:
    """Tests for agenda command handlers."""

    @pytest.mark.asyncio
    async def test_ver_notas_success(self, handler, mock_update, mock_context, mock_services):
        """Test /notas command with notes."""
        # Arrange
        mock_update.effective_chat.id = "123456789"
        mock_task_repo = mock_services[0]

        # Mock notes
        mock_nota = MagicMock()
        mock_nota.id = 1
        mock_nota.detalles = "Clave wifi es 1234"
        mock_nota.tags = ["wifi", "casa"]
        mock_services[0].get_notes.return_value = [mock_nota]

        # Act
        await handler.ver_notas(mock_update, mock_context)

        # Assert
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        message_text = call_args.args[0] if call_args.args else call_args.kwargs.get('text', '')
        assert "Clave wifi es 1234" in message_text
        assert "#wifi #casa" in message_text

    @pytest.mark.asyncio
    async def test_ver_notas_empty(self, handler, mock_update, mock_context, mock_services):
        """Test /notas command with no notes."""
        # Arrange
        mock_update.effective_chat.id = "123456789"
        mock_services[0].get_notes.return_value = []

        # Act
        await handler.ver_notas(mock_update, mock_context)

        # Assert
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        message_text = call_args.args[0] if call_args.args else call_args.kwargs.get('text', '')
        assert "No tenés notas guardadas" in message_text

    @pytest.mark.asyncio
    async def test_ver_hoy_success(self, handler, mock_update, mock_context, mock_services):
        """Test /hoy command."""
        # Arrange
        mock_update.effective_chat.id = "123456789"

        mock_task = MagicMock()
        mock_task.id = 1
        mock_task.detalles = "Reunión hoy"
        mock_task.fecha_hora = datetime.now().replace(hour=14, minute=0, second=0, microsecond=0)
        mock_task.prioridad = 0
        mock_task.tags = []

        mock_services[0].get_tasks_by_date_range.return_value = [MagicMock()]
        mock_services[0].get_tasks_by_date_range.return_value[0].id = 1
        mock_services[0].get_tasks_by_date_range.return_value[0].detalles = "Reunión hoy"
        mock_services[0].get_tasks_by_date_range.return_value[0].fecha_hora = datetime.now().replace(hour=14)
        mock_services[0].get_tasks_by_date_range.return_value[0].prioridad = 0
        mock_services[0].get_tasks_by_date_range.return_value[0].tags = []

        mock_services[1].get_upcoming_events.return_value = [{
            'summary': 'Evento Calendar',
            'start': {'dateTime': datetime.now().replace(hour=15).isoformat()}
        }]

        # Act
        await handler.ver_hoy(mock_update, mock_context)

        # Assert
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_ver_semana_success(self, handler, mock_update, mock_context, mock_services):
        """Test /semana command."""
        mock_update.effective_chat.id = "123456789"
        mock_services[0].get_tasks_by_date_range.return_value = []
        mock_services[1].get_upcoming_events.return_value = []

        await handler.ver_semana(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_buscar_simple(self, handler, mock_update, mock_context, mock_services):
        """Test /buscar with simple query."""
        mock_update.effective_chat.id = "123456789"
        mock_context.args = ["reunión"]

        mock_services[0].search_tasks.return_value = []
        mock_services[1].get_upcoming_events.return_value = []

        await handler.buscar(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_buscar_with_tags(self, handler, mock_update, mock_context, mock_services):
        """Test /buscar with tags."""
        mock_update.effective_chat.id = "123456789"
        mock_context.args = ["#trabajo", "reunión"]

        mock_services[0].search_tasks.return_value = [MagicMock(id=1, detalles="Reunión trabajo")]
        mock_services[0].get_tasks_by_tag.return_value = [MagicMock(id=1, detalles="Reunión trabajo")]

        await handler.buscar(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_filtrar_tag_single(self, handler, mock_update, mock_context, mock_services):
        """Test /tag with single tag."""
        mock_update.effective_chat.id = "123456789"
        mock_context.args = ["trabajo"]

        mock_services[0].get_tasks_by_tag.return_value = [MagicMock()]

        await handler.filtrar_tag(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        mock_services[0].get_tasks_by_tag.assert_called_once()

    @pytest.mark.asyncio
    async def test_filtrar_tag_multiple(self, handler, mock_update, mock_context, mock_services):
        """Test /tag with multiple tags (intersection)."""
        mock_update.effective_chat.id = "123456789"
        mock_context.args = ["trabajo", "urgente"]

        mock_services[0].get_tasks_by_tag.side_effect = [
            [MagicMock(id=1, detalles="Tarea trabajo urgente")],  # trabajo
            [MagicMock(id=1, detalles="Tarea trabajo urgente")],  # urgente
        ]

        await handler.filtrar_tag(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        assert mock_services[0].get_tasks_by_tag.call_count == 2

    @pytest.mark.asyncio
    async def test_ver_pendientes_empty(self, handler, mock_update, mock_context, mock_services):
        """Test /pendientes with no daily tasks."""
        mock_update.effective_chat.id = "123456789"

        mock_services[0].get_daily_tasks.return_value = []

        await handler.ver_pendientes(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        message_text = call_args.args[0] if call_args.args else call_args.kwargs.get('text', '')
        assert "No tenés listas de tareas diarias" in message_text

    @pytest.mark.asyncio
    async def test_ver_hoy_corto(self, handler, mock_update, mock_context, mock_services):
        """Test /hoy_corto command."""
        mock_update.effective_chat.id = "123456789"
        mock_services[0].get_tasks_by_date_range.return_value = []
        mock_services[1].get_upcoming_events.return_value = []

        await handler.ver_hoy_corto(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        message_text = call_args.args[0] if call_args.args else call_args.kwargs.get('text', '')
        assert "compacto" in message_text.lower() or "Hoy" in message_text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])