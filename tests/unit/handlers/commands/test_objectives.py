"""
Tests for objectives command handlers - TDD approach.

Following TDD: write failing test first, then implement minimal code to pass.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from handlers.commands.objectives import ObjectivesCommandsHandler
from config.settings import settings
from infrastructure.database.repositories.task_repo import TaskType, TaskStatus


def create_mock_update():
    """Create a properly mocked Update object."""
    from unittest.mock import MagicMock
    update = AsyncMock()
    update.effective_chat = MagicMock()
    update.effective_chat.id = settings.mi_telegram_id
    update.message = AsyncMock()
    update.message.reply_text = AsyncMock()
    update.message.chat_id = settings.mi_telegram_id
    return update


class TestObjectivesCommands:
    """Tests for objectives command handlers."""

    @pytest.fixture
    def mock_context(self):
        """Mock Context object."""
        context = AsyncMock()
        context.bot_data = {}
        return context

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from handlers.commands.objectives import ObjectivesCommandsHandler
        return ObjectivesCommandsHandler()

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
    async def test_ver_objetivos_success(self, handler):
        """Test /objetivos command success."""
        update = self.create_mock_update()
        mock_objetivo_repo = AsyncMock()
        mock_objetivos = [
            MagicMock(id=1, descripcion="Estudiar 10h/semana", objetivo_valor=10, objetivo_unidad="horas", valor_actual=5, semana_inicio="2026-11-02", completado=False),
            MagicMock(id=2, descripcion="Leer 2 libros/mes", objetivo_valor=2, objetivo_unidad="libros", valor_actual=1, semana_inicio="2026-11-02", completado=False),
        ]
        mock_objetivo_repo = AsyncMock()
        mock_objetivo_repo.get_active.return_value = mock_objetivos

        services = {'objetivo_repo': mock_objetivo_repo}
        handler.get_services = AsyncMock(return_value=services)

        await handler.ver_objetivos(self.create_mock_update(), AsyncMock())

    @pytest.mark.asyncio
    async def test_ver_objetivos_empty(self, handler):
        """Test /objetivos when no objectives exist."""
        update = self.create_mock_update()
        mock_objetivo_repo = AsyncMock()
        mock_objetivo_repo.get_active.return_value = []

        services = {'objetivo_repo': mock_objetivo_repo}
        handler.get_services = AsyncMock(return_value=services)

        await handler.ver_objetivos(self.create_mock_update(), AsyncMock())

    @pytest.mark.asyncio
    async def test_ver_revision_success(self, handler):
        """Test /revision command success."""
        update = self.create_mock_update()
        services = {
            'task_repo': AsyncMock(),
            'calendar_service': AsyncMock(),
            'objetivo_repo': AsyncMock(),
            'revision_repo': AsyncMock(),
            'plantilla_repo': AsyncMock(),
            'weekly_planning_service': AsyncMock(),
        }
        handler.get_services = AsyncMock(return_value=services)

        await handler.ver_revision(self.create_mock_update(), AsyncMock())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])