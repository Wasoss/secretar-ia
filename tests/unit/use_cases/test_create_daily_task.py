"""
Tests for CreateDailyTaskUseCase - TDD approach.

Following TDD: write failing test first, then implement minimal code to pass.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from application.services.ai_service import ActionType, ParsedIntent
from infrastructure.database.repositories.task_repo import TaskRepository, TaskType, TaskStatus, SubTask


class TestCreateDailyTaskUseCase:
    """Tests for CreateDailyTaskUseCase."""

    @pytest.fixture
    def mock_task_repo(self):
        """Mock TaskRepository."""
        repo = AsyncMock(spec=TaskRepository)
        repo.save = AsyncMock(return_value=123)  # Returns task ID
        return repo

    @pytest.fixture
    def use_case(self, mock_task_repo):
        """Create use case instance with mocked dependencies."""
        from application.use_cases.create_daily_task import CreateDailyTaskUseCase
        return CreateDailyTaskUseCase(task_repo=mock_task_repo)

    @pytest.mark.asyncio
    async def test_create_daily_task_success(self, use_case, mock_task_repo):
        """Test successful daily task creation with subtasks."""
        # Arrange
        user_id = "123"
        intent = ParsedIntent(
            accion=ActionType.TAREA_DIARIA,
            detalles="estudiar lógica, preparar clases, limpiar",
            fecha_hora=None,  # Daily tasks don't have specific date
            prioridad=1,
            tags=["estudio", "casa"],
        )

        # Act
        result = await use_case.execute(user_id, intent)

        # Assert
        assert result.success is True
        assert result.task_id == 123
        assert "Lista diaria creada" in result.message

        # Verify repository called correctly
        mock_task_repo.save.assert_called_once()
        call_args = mock_task_repo.save.call_args
        assert call_args.kwargs["telefono_id"] == user_id
        assert call_args.kwargs["tipo"] == "TAREA_DIARIA"
        assert call_args.kwargs["detalles"] == "estudiar lógica, preparar clases, limpiar"
        assert call_args.kwargs["fecha_hora"] is None
        assert call_args.kwargs["prioridad"] == 1
        assert call_args.kwargs["tags"] == ["estudio", "casa"]
        assert call_args.kwargs["calendar_event_id"] is None
        # Verify subtasks were parsed and passed
        assert "subtareas" in call_args.kwargs
        subtareas = call_args.kwargs["subtareas"]
        assert len(subtareas) == 3
        assert subtareas[0].texto == "estudiar lógica"
        assert subtareas[1].texto == "preparar clases"
        assert subtareas[2].texto == "limpiar"

    @pytest.mark.asyncio
    async def test_create_daily_task_with_newlines(self, use_case, mock_task_repo):
        """Test daily task creation with newline-separated items."""
        # Arrange
        user_id = "123"
        intent = ParsedIntent(
            accion=ActionType.TAREA_DIARIA,
            detalles="estudiar\npreparar clases\nlimpiar",
            fecha_hora=None,
            prioridad=0,
            tags=["test"],
        )

        # Act
        result = await use_case.execute(user_id, intent)

        # Assert
        assert result.success is True
        call_args = mock_task_repo.save.call_args
        subtareas = call_args.kwargs["subtareas"]
        assert len(subtareas) == 3
        assert subtareas[0].texto == "estudiar"
        assert subtareas[1].texto == "preparar clases"
        assert subtareas[2].texto == "limpiar"

    @pytest.mark.asyncio
    async def test_create_daily_task_with_y_separator(self, use_case, mock_task_repo):
        """Test daily task creation with 'y' separator."""
        # Arrange
        user_id = "123"
        intent = ParsedIntent(
            accion=ActionType.TAREA_DIARIA,
            detalles="estudiar y preparar clases y limpiar",
            fecha_hora=None,
            prioridad=0,
            tags=[],
        )

        # Act
        result = await use_case.execute(user_id, intent)

        # Assert
        assert result.success is True
        call_args = mock_task_repo.save.call_args
        subtareas = call_args.kwargs["subtareas"]
        assert len(subtareas) == 3
        assert subtareas[0].texto == "estudiar"
        assert subtareas[1].texto == "preparar clases"
        assert subtareas[2].texto == "limpiar"

    @pytest.mark.asyncio
    async def test_create_daily_task_with_semicolon(self, use_case, mock_task_repo):
        """Test daily task creation with semicolon separator."""
        # Arrange
        user_id = "123"
        intent = ParsedIntent(
            accion=ActionType.TAREA_DIARIA,
            detalles="estudiar; preparar clases; limpiar",
            fecha_hora=None,
            prioridad=0,
            tags=[],
        )

        # Act
        result = await use_case.execute(user_id, intent)

        # Assert
        assert result.success is True
        call_args = mock_task_repo.save.call_args
        subtareas = call_args.kwargs["subtareas"]
        assert len(subtareas) == 3

    @pytest.mark.asyncio
    async def test_create_daily_task_no_calendar_sync(self, use_case, mock_task_repo):
        """Test that daily tasks don't attempt Calendar sync."""
        # Arrange
        user_id = "123"
        intent = ParsedIntent(
            accion=ActionType.TAREA_DIARIA,
            detalles="tareas del día",
            fecha_hora=None,
            prioridad=0,
            tags=[],
        )

        # Act
        result = await use_case.execute(user_id, intent)

        # Assert
        assert result.success is True
        assert "Calendar" not in result.message

    @pytest.mark.asyncio
    async def test_create_daily_task_saves_locally_only(self, use_case, mock_task_repo):
        """Test that daily task only saves to DB (no external sync)."""
        # Arrange
        user_id = "123"
        intent = ParsedIntent(
            accion=ActionType.TAREA_DIARIA,
            detalles="solo BD",
            fecha_hora=None,
        )

        # Track calls
        call_order = []

        original_save = mock_task_repo.save

        async def tracking_save(*args, **kwargs):
            call_order.append("save")
            return await original_save(*args, **kwargs)

        mock_task_repo.save = tracking_save

        # Act
        await use_case.execute(user_id, intent)

        # Assert - only save should be called (no external sync)
        assert call_order == ["save"], f"Expected ['save'], got {call_order}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])