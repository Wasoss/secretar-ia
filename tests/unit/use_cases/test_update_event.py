"""
Tests for UpdateEventUseCase - TDD approach.

Following TDD: write failing test first, then implement minimal code to pass.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from application.services.ai_service import ActionType, ParsedIntent
from infrastructure.database.repositories.task_repo import TaskRepository, TaskType, TaskStatus


class TestUpdateEventUseCase:
    """Tests for UpdateEventUseCase."""

    @pytest.fixture
    def mock_task_repo(self):
        """Mock TaskRepository."""
        repo = AsyncMock(spec=TaskRepository)
        repo.get_task_by_id = AsyncMock()
        repo.update_task = AsyncMock(return_value=True)
        return repo

    @pytest.fixture
    def mock_calendar_service(self):
        """Mock CalendarService."""
        service = AsyncMock()
        service.update_event = AsyncMock(return_value={"id": "cal_event_123"})
        service.check_conflicts = AsyncMock(return_value=[])
        return service

    @pytest.fixture
    def use_case(self, mock_task_repo, mock_calendar_service):
        """Create use case instance with mocked dependencies."""
        from application.use_cases.update_event import UpdateEventUseCase
        return UpdateEventUseCase(
            task_repo=mock_task_repo,
            calendar_service=mock_calendar_service,
        )

    @pytest.mark.asyncio
    async def test_update_event_success(self, use_case, mock_task_repo, mock_calendar_service):
        """Test successful event update."""
        # Arrange
        user_id = "123"
        task_id = 456
        existing_task = MagicMock()
        existing_task.id = task_id
        existing_task.telefono_id = user_id
        existing_task.tipo = TaskType.EVENTO
        existing_task.detalles = "Reunión original"
        existing_task.fecha_hora = datetime(2026, 11, 3, 14, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))
        existing_task.recurrencia = None
        existing_task.prioridad = 0
        existing_task.tags = ["trabajo"]
        existing_task.calendar_event_id = "cal_event_123"
        existing_task.subtareas = []

        mock_task_repo.get_task_by_id.return_value = existing_task
        mock_task_repo.update_task.return_value = True

        # Act
        result = await use_case.execute(
            user_id=user_id,
            task_id=task_id,
            nuevo_detalles="Reunión actualizada",
            nueva_fecha_hora=datetime(2026, 11, 4, 15, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
            nueva_recurrencia="FREQ=WEEKLY;BYDAY=MO",
            nueva_prioridad=1,
            nuevos_tags=["trabajo", "importante"],
        )

        # Assert
        assert result.success is True
        assert result.task_id == task_id
        assert result.calendar_event_id == "cal_event_123"
        assert "Actualizado" in result.message

        # Verify repository update called
        mock_task_repo.update_task.assert_called_once()
        call_args = mock_task_repo.update_task.call_args
        # task_id is passed as positional argument (args[0]), rest as kwargs
        assert call_args.args[0] == task_id
        assert call_args.kwargs["detalles"] == "Reunión actualizada"
        assert call_args.kwargs["fecha_hora"] == datetime(2026, 11, 4, 15, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))
        assert call_args.kwargs["recurrencia"] == "FREQ=WEEKLY;BYDAY=MO"
        assert call_args.kwargs["prioridad"] == 1
        assert call_args.kwargs["tags"] == ["trabajo", "importante"]

        # Verify calendar update called
        mock_calendar_service.update_event.assert_called_once()
        cal_args = mock_calendar_service.update_event.call_args
        assert cal_args.kwargs["event_id"] == "cal_event_123"
        assert cal_args.kwargs["summary"] == "Reunión actualizada"

    @pytest.mark.asyncio
    async def test_update_event_not_found(self, use_case, mock_task_repo):
        """Test event update fails when task not found."""
        # Arrange
        user_id = "123"
        task_id = 999
        mock_task_repo.get_task_by_id.return_value = None

        # Act
        result = await use_case.execute(
            user_id=user_id,
            task_id=task_id,
            nuevo_detalles="Nuevo título",
        )

        # Assert
        assert result.success is False
        assert "no encontrada" in result.error.lower()

    @pytest.mark.asyncio
    async def test_update_event_wrong_type(self, use_case, mock_task_repo):
        """Test event update fails when task is not an EVENTO."""
        # Arrange
        user_id = "123"
        task_id = 456
        existing_task = MagicMock()
        existing_task.id = task_id
        existing_task.tipo = TaskType.NOTA  # Not an EVENTO
        existing_task.telefono_id = "123"

        mock_task_repo.get_task_by_id.return_value = existing_task

        # Act
        result = await use_case.execute(
            user_id=user_id,
            task_id=task_id,
            nuevo_detalles="Nuevo título",
        )

        # Assert
        assert result.success is False
        assert "evento" in result.error.lower()

    @pytest.mark.asyncio
    async def test_update_event_calendar_conflict_warning(self, use_case, mock_task_repo, mock_calendar_service):
        """Test event update with calendar conflict returns warning but updates locally."""
        # Arrange
        user_id = "123"
        task_id = 456
        existing_task = MagicMock()
        existing_task.id = task_id
        existing_task.telefono_id = user_id
        existing_task.tipo = TaskType.EVENTO
        existing_task.detalles = "Reunión original"
        existing_task.fecha_hora = datetime(2026, 11, 3, 14, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))
        existing_task.recurrencia = None
        existing_task.prioridad = 0
        existing_task.tags = []
        existing_task.calendar_event_id = "cal_event_123"
        existing_task.subtareas = []

        mock_task_repo.get_task_by_id.return_value = existing_task
        mock_task_repo.update_task.return_value = True

        # Simulate conflict
        mock_calendar_service.check_conflicts.return_value = [
            {"summary": "Otra reunión", "start": {"dateTime": "2026-11-03T14:00:00"}}
        ]
        mock_calendar_service.update_event.return_value = None  # Fails due to conflict

        # Act
        result = await use_case.execute(
            user_id=user_id,
            task_id=task_id,
            nueva_fecha_hora=datetime(2026, 11, 3, 14, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
        )

        # Assert
        assert result.success is True  # Still updates locally
        assert "Conflicto" in result.message or "conflicto" in result.message.lower()

    @pytest.mark.asyncio
    async def test_update_event_calendar_sync_failure(self, use_case, mock_task_repo, mock_calendar_service):
        """Test event update when calendar sync fails (token expired, etc.)."""
        # Arrange
        user_id = "123"
        task_id = 456
        existing_task = MagicMock()
        existing_task.id = task_id
        existing_task.telefono_id = user_id
        existing_task.tipo = TaskType.EVENTO
        existing_task.detalles = "Reunión test"
        existing_task.fecha_hora = datetime(2026, 11, 3, 14, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))
        existing_task.calendar_event_id = "cal_event_123"
        existing_task.subtareas = []

        mock_task_repo.get_task_by_id.return_value = existing_task
        mock_task_repo.update_task.return_value = True
        mock_calendar_service.update_event.side_effect = Exception("Token expired")

        # Act
        result = await use_case.execute(
            user_id=user_id,
            task_id=task_id,
            nuevo_detalles="Reunión actualizada",
        )

        # Assert
        assert result.success is True  # Still updates locally
        # Check for error message in result.message (case insensitive)
        msg_lower = result.message.lower()
        assert "token" in msg_lower or "calendar" in msg_lower or "sincroniz" in msg_lower

    @pytest.mark.asyncio
    async def test_update_event_partial_update(self, use_case, mock_task_repo, mock_calendar_service):
        """Test event update with only some fields changed."""
        # Arrange
        user_id = "123"
        task_id = 456
        existing_task = MagicMock()
        existing_task.id = task_id
        existing_task.telefono_id = user_id
        existing_task.tipo = TaskType.EVENTO
        existing_task.detalles = "Reunión original"
        existing_task.fecha_hora = datetime(2026, 11, 3, 14, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))
        existing_task.recurrencia = None
        existing_task.prioridad = 0
        existing_task.tags = ["trabajo"]
        existing_task.calendar_event_id = "cal_event_123"
        existing_task.subtareas = []

        mock_task_repo.get_task_by_id.return_value = existing_task
        mock_task_repo.update_task.return_value = True

        # Act - only change title
        result = await use_case.execute(
            user_id=user_id,
            task_id=task_id,
            nuevo_detalles="Solo cambio título",
        )

        # Assert
        assert result.success is True
        call_args = mock_task_repo.update_task.call_args
        assert call_args.kwargs["detalles"] == "Solo cambio título"
        # Other fields should remain unchanged (not passed in update_kwargs)
        assert "fecha_hora" not in call_args.kwargs  # Not passed
        assert "recurrencia" not in call_args.kwargs  # Not passed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])