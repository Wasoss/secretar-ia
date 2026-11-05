"""
Tests for templates command handlers - TDD approach.

Following TDD: write failing test first, then implement minimal code to pass.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from zoneinfo import ZoneInfo

from handlers.commands.templates import TemplatesCommandsHandler
from config.settings import settings


class TestTemplatesCommands:
    """Tests for templates command handlers."""

    @pytest.fixture
    def mock_update(self):
        """Mock Update object."""
        update = AsyncMock()
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
        return context

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from handlers.commands.templates import TemplatesCommandsHandler
        return TemplatesCommandsHandler()

    @pytest.mark.asyncio
    async def test_ver_plantillas_no_templates(self, handler, mock_update, mock_context):
        """Test /plantillas when no templates exist."""
        # Arrange: Mock the container's get_all_services to return a mock plantilla_repo
        mock_plantilla_repo = AsyncMock()
        mock_plantilla_repo.get_all.return_value = []

        # Patch the container's get_all_services method
        with patch.object(handler._container, 'get_all_services', new=AsyncMock(return_value={
            'plantilla_repo': AsyncMock(get_all=AsyncMock(return_value=[]))
        })):
            # Act
            await handler.ver_plantillas(mock_update, AsyncMock())

            # Assert
            mock_update.message.reply_text.assert_called_once()
            call_args = mock_update.message.reply_text.call_args
            assert "No tenés plantillas guardadas" in call_args.args[0]
            assert "Plantilla: cada día estudiar 2h, ejercicio" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_ver_plantillas_with_templates(self, handler, mock_update, mock_context):
        """Test /plantillas when templates exist."""
        # Arrange
        from unittest.mock import AsyncMock, MagicMock

        # Create mock plantilla
        mock_plantilla = MagicMock()
        mock_plantilla.id = 1
        mock_plantilla.nombre = "Rutina matutina"
        mock_plantilla.activa = True
        mock_plantilla.items = [
            {"texto": "estudiar 30min", "orden": 0},
            {"texto": "ejercicio 20min", "orden": 1},
            {"texto": "meditar 10min", "orden": 2},
        ]

        # Mock the container's get_all_services to return a mock plantilla_repo
        mock_plantilla_repo = AsyncMock()
        mock_plantilla_repo.get_all.return_value = [mock_plantilla]

        with patch.object(handler._container, 'get_all_services', new=AsyncMock(return_value={
            'plantilla_repo': mock_plantilla_repo
        })):
            # Act
            await handler.ver_plantillas(mock_update, AsyncMock())

            # Assert
            mock_update.message.reply_text.assert_called_once()
            call_args = mock_update.message.reply_text.call_args
            assert "Rutina matutina" in call_args.args[0]
            assert "ACTIVA" in call_args.args[0]
            assert "estudiar 30min" in call_args.args[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])