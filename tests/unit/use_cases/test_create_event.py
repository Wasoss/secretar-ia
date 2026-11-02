"""
Tests for CreateEventUseCase - TDD approach.

Following TDD: write failing test first, then implement minimal code to pass.
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from application.services.ai_service import ActionType, ParsedIntent
from infrastructure.database.repositories.task_repo import TaskRepository, TaskType, TaskStatus


class TestCreateEventUseCase:
    """Tests for CreateEventUseCase."""

    @pytest.fixture
    def mock_task_repo(self):
        """Mock TaskRepository."""
        repo = AsyncMock(spec=TaskRepository)
        repo.save = AsyncMock(return_value=123)  # Returns task ID
        repo.update_task = AsyncMock(return_value=True)
        return repo

    @pytest.fixture
    def mock_calendar_service(self):
        """Mock CalendarService."""
        service = AsyncMock()
        service.create_event = AsyncMock(return_value={"id": "cal_event_123"})
        service.check_conflicts = AsyncMock(return_value=[])
        return service

    @pytest.fixture
    def use_case(self, mock_task_repo, mock_calendar_service):
        """Create use case instance with mocked dependencies."""
        # Import here to avoid circular imports during test discovery
        from application.use_cases.create_event import CreateEventUseCase
        return CreateEventUseCase(
            task_repo=mock_task_repo,
            calendar_service=mock_calendar_service,
        )

    @pytest.mark.asyncio
    async def test_create_event_success(self, use_case, mock_task_repo, mock_calendar_service):
        """Test successful event creation with calendar sync."""
        # Arrange
        user_id = "user_123"
        intent = ParsedIntent(
            accion=ActionType.EVENTO,
            detalles="Reunión con Juan",
            fecha_hora=datetime(2026, 11, 3, 14, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
            recurrencia=None,
            prioridad=1,
            tags=["trabajo"],
        )

        # Act
        result = await use_case.execute(user_id, intent)

        # Assert
        assert result.success is True
        assert result.task_id == 123
        assert result.calendar_event_id == "cal_event_123"
        assert "Sincronizado con Google Calendar" in result.message

        # Verify repository called correctly
        mock_task_repo.save.assert_called_once()
        call_args = mock_task_repo.save.call_args
        assert call_args.kwargs["telefono_id"] == user_id
        assert call_args.kwargs["tipo"] == TaskType.EVENTO
        assert call_args.kwargs["detalles"] == "Reunión con Juan"
        assert call_args.kwargs["fecha_hora"] == intent.fecha_hora
        assert call_args.kwargs["prioridad"] == 1
        assert call_args.kwargs["tags"] == ["trabajo"]

        # Verify calendar sync
        mock_calendar_service.create_event.assert_called_once()
        mock_task_repo.update_task.assert_called_once_with(123, calendar_event_id="cal_event_123")

    @pytest.mark.asyncio
    async def test_create_event_without_date_fails(self, use_case):
        """Test event creation fails when no date provided."""
        # Arrange
        user_id = "user_123"
        intent = ParsedIntent(
            accion=ActionType.EVENTO,
            detalles="Reunión sin fecha",
            fecha_hora=None,  # No date
            prioridad=0,
            tags=[],
        )

        # Act
        result = await use_case.execute(user_id, intent)

        # Assert
        assert result.success is False
        assert "fecha/hora" in result.error.lower() or "fecha" in result.error.lower()

    @pytest.mark.asyncio
    async def test_create_event_calendar_conflict_warning(self, use_case, mock_task_repo, mock_calendar_service):
        """Test event creation with calendar conflict returns warning but saves locally."""
        # Arrange
        user_id = "user_123"
        intent = ParsedIntent(
            accion=ActionType.EVENTO,
            detalles="Reunión conflictiva",
            fecha_hora=datetime(2026, 11, 3, 14, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
            prioridad=0,
            tags=[],
        )
        # Simulate conflict
        mock_calendar_service.check_conflicts.return_value = [
            {"summary": "Otra reunión", "start": {"dateTime": "2026-11-03T14:00:00"}}
        ]
        mock_calendar_service.create_event.return_value = None  # Sync fails due to conflict

        # Act
        result = await use_case.execute(user_id, intent)

        # Assert
        assert result.success is True  # Still saves locally
        assert "Conflicto en Calendar" in result.message or "conflicto" in result.message.lower()

    @pytest.mark.asyncio
    async def test_create_event_calendar_sync_failure(self, use_case, mock_task_repo, mock_calendar_service):
        """Test event creation when calendar sync fails (token expired, etc.)."""
        # Arrange
        user_id = "user_123"
        intent = ParsedIntent(
            accion=ActionType.EVENTO,
            detalles="Reunión test",
            fecha_hora=datetime(2026, 11, 3, 14, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
            prioridad=0,
            tags=[],
        )
        mock_calendar_service.create_event.side_effect = Exception("Token expired")

        # Act
        result = await use_case.execute(user_id, intent)

        # Assert
        assert result.success is True  # Still saves locally
        # Check case-insensitively for error keywords
        msg_lower = result.message.lower()
        assert "token" in msg_lower or "calendar" in msg_lower or "sincroniz" in msg_lower

    @pytest.mark.asyncio
    async def test_create_event_with_recurrence(self, use_case, mock_task_repo, mock_calendar_service):
        """Test event creation with recurrence rule."""
        # Arrange
        user_id = "user_123"
        intent = ParsedIntent(
            accion=ActionType.EVENTO,
            detalles="Clase yoga semanal",
            fecha_hora=datetime(2026, 11, 3, 19, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
            recurrencia="FREQ=WEEKLY;BYDAY=MO",
            prioridad=0,
            tags=["salud"],
        )

        # Act
        result = await use_case.execute(user_id, intent)

        # Assert
        assert result.success is True
        # Verify recurrence passed to calendar
        call_args = mock_calendar_service.create_event.call_args
        assert call_args.kwargs["recurrence"] == "FREQ=WEEKLY;BYDAY=MO"

    @pytest.mark.asyncio
    async def test_create_event_saves_locally_first(self, use_case, mock_task_repo, mock_calendar_service):
        """Test that event is saved to DB BEFORE calendar sync (guarantees local persistence)."""
        # Arrange
        user_id = "user_123"
        intent = ParsedIntent(
            accion=ActionType.EVENTO,
            detalles="Test orden",
            fecha_hora=datetime(2026, 11, 3, 14, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
        )

        # Track call order
        call_order = []

        original_save = mock_task_repo.save
        original_calendar = mock_calendar_service.create_event

        async def tracking_save(*args, **kwargs):
            call_order.append("save")
            return await original_save(*args, **kwargs)

        async def tracking_calendar(*args, **kwargs):
            call_order.append("calendar")
            return await original_calendar(*args, **kwargs)

        mock_task_repo.save = tracking_save
        mock_calendar_service.create_event = tracking_calendar

        # Act
        await use_case.execute(user_id, intent)

        # Assert - save should happen before calendar
        assert call_order == ["save", "calendar"], f"Expected ['save', 'calendar'], got {call_order}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])