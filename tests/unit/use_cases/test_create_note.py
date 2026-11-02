"""
Tests for CreateNoteUseCase - TDD approach.

Following TDD: write failing test first, then implement minimal code to pass.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from application.services.ai_service import ActionType, ParsedIntent
from infrastructure.database.repositories.task_repo import TaskRepository, TaskType, TaskStatus


class TestCreateNoteUseCase:
    """Tests for CreateNoteUseCase."""

    @pytest.fixture
    def mock_task_repo(self):
        """Mock TaskRepository."""
        repo = AsyncMock(spec=TaskRepository)
        repo.save = AsyncMock(return_value=123)  # Returns task ID
        return repo

    @pytest.fixture
    def use_case(self, mock_task_repo):
        """Create use case instance with mocked dependencies."""
        from application.use_cases.create_note import CreateNoteUseCase
        return CreateNoteUseCase(task_repo=mock_task_repo)

    @pytest.mark.asyncio
    async def test_create_note_success(self, use_case, mock_task_repo):
        """Test successful note creation."""
        # Arrange
        user_id = "123"
        intent = ParsedIntent(
            accion=ActionType.NOTA,
            detalles="Clave wifi es 1234",
            fecha_hora=None,  # Notes don't require date
            prioridad=0,
            tags=["wifi", "clave"],
        )

        # Act
        result = await use_case.execute(user_id, intent)

        # Assert
        assert result.success is True
        assert result.task_id == 123
        assert "Guardado como" in result.message

        # Verify repository called correctly
        mock_task_repo.save.assert_called_once()
        call_args = mock_task_repo.save.call_args
        assert call_args.kwargs["telefono_id"] == user_id
        assert call_args.kwargs["tipo"] == "NOTA"
        assert call_args.kwargs["detalles"] == "Clave wifi es 1234"
        assert call_args.kwargs["fecha_hora"] is None  # Notes have no date
        assert call_args.kwargs["prioridad"] == 0
        assert call_args.kwargs["tags"] == ["wifi", "clave"]
        assert call_args.kwargs["calendar_event_id"] is None  # Notes don't go to Calendar

    @pytest.mark.asyncio
    async def test_create_note_with_priority_and_tags(self, use_case, mock_task_repo):
        """Test note creation with priority and tags."""
        # Arrange
        user_id = "123"
        intent = ParsedIntent(
            accion=ActionType.NOTA,
            detalles="Idea: regalo para Ana - libro",
            fecha_hora=None,
            prioridad=-1,  # Low priority
            tags=["ideas", "regalos"],
        )

        # Act
        result = await use_case.execute(user_id, intent)

        # Assert
        assert result.success is True
        assert result.task_id == 123

        # Verify repository called with correct priority and tags
        call_args = mock_task_repo.save.call_args
        assert call_args.kwargs["prioridad"] == -1
        assert call_args.kwargs["tags"] == ["ideas", "regalos"]

    @pytest.mark.asyncio
    async def test_create_note_no_calendar_sync(self, use_case, mock_task_repo):
        """Test that notes don't attempt Calendar sync."""
        # Arrange
        user_id = "123"
        intent = ParsedIntent(
            accion=ActionType.NOTA,
            detalles="Nota sin fecha",
            fecha_hora=None,
            prioridad=0,
            tags=[],
        )

        # Act
        result = await use_case.execute(user_id, intent)

        # Assert
        assert result.success is True
        # Notes should not have calendar_event_id
        assert "Calendar" not in result.message
        assert "calendar_event_id" not in result.message.lower() or "calendar" not in result.message.lower()

    @pytest.mark.asyncio
    async def test_create_note_saves_locally(self, use_case, mock_task_repo):
        """Test that note is saved to DB."""
        # Arrange
        user_id = "123"
        intent = ParsedIntent(
            accion=ActionType.NOTA,
            detalles="Test note",
            fecha_hora=None,
            prioridad=0,
            tags=[],
        )

        # Act
        result = await use_case.execute(user_id, intent)

        # Assert
        assert result.success is True
        assert result.task_id == 123
        mock_task_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_note_saves_locally_only(self, use_case, mock_task_repo):
        """Test that note only saves to DB (no external sync)."""
        # Arrange
        user_id = "123"
        intent = ParsedIntent(
            accion=ActionType.NOTA,
            detalles="Solo BD",
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