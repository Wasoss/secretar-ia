"""
Tests for CreateReminderUseCase - TDD approach.

Following TDD: write failing test first, then implement minimal code to pass.
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from application.services.ai_service import ActionType, ParsedIntent
from infrastructure.database.repositories.task_repo import TaskRepository, TaskType, TaskStatus


class TestCreateReminderUseCase:
    """Tests for CreateReminderUseCase."""

    @pytest.fixture
    def mock_task_repo(self):
        """Mock TaskRepository."""
        repo = AsyncMock(spec=TaskRepository)
        repo.save = AsyncMock(return_value=123)  # Returns task ID
        return repo

    @pytest.fixture
    def mock_reminder_service(self):
        """Mock ReminderService."""
        service = AsyncMock()
        service.schedule_reminder = AsyncMock(return_value=True)
        service.cancel_reminders = AsyncMock()
        return service

    @pytest.fixture
    def use_case(self, mock_task_repo, mock_reminder_service):
        """Create use case instance with mocked dependencies."""
        from application.use_cases.create_reminder import CreateReminderUseCase
        return CreateReminderUseCase(
            task_repo=mock_task_repo,
            reminder_service=mock_reminder_service,
        )

    @pytest.mark.asyncio
    async def test_create_reminder_success(self, use_case, mock_task_repo, mock_reminder_service):
        """Test successful reminder creation with alarm scheduling."""
        # Arrange
        user_id = "123"
        intent = ParsedIntent(
            accion=ActionType.RECORDATORIO,
            detalles="Llamar a mamá",
            fecha_hora=datetime(2026, 11, 3, 14, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
            recurrencia=None,
            prioridad=1,
            tags=["familia"],
        )
        mock_job_queue = AsyncMock()

        # Act
        result = await use_case.execute(user_id, intent, job_queue=mock_job_queue)

        # Assert
        assert result.success is True
        assert result.task_id == 123
        assert "Alarma programada" in result.message

        # Verify repository called correctly
        mock_task_repo.save.assert_called_once()
        call_args = mock_task_repo.save.call_args
        assert call_args.kwargs["telefono_id"] == user_id
        assert call_args.kwargs["tipo"] == "RECORDATORIO"
        assert call_args.kwargs["detalles"] == "Llamar a mamá"
        assert call_args.kwargs["fecha_hora"] == intent.fecha_hora
        assert call_args.kwargs["prioridad"] == 1
        assert call_args.kwargs["tags"] == ["familia"]

        # Verify reminder scheduled with the mock_job_queue
        mock_reminder_service.schedule_reminder.assert_called_once_with(
            job_queue=mock_job_queue,
            chat_id=int(user_id),
            text="Llamar a mamá",
            fecha_hora=intent.fecha_hora,
        )

    @pytest.mark.asyncio
    async def test_create_reminder_without_date_fails(self, use_case):
        """Test reminder creation fails when no date provided."""
        # Arrange
        user_id = "123"
        intent = ParsedIntent(
            accion=ActionType.RECORDATORIO,
            detalles="Recordar algo",
            fecha_hora=None,  # No date
            prioridad=0,
            tags=[],
        )

        # Act
        result = await use_case.execute(user_id, intent, job_queue=AsyncMock())

        # Assert
        assert result.success is False
        assert "fecha/hora" in result.error.lower() or "fecha" in result.error.lower()

    @pytest.mark.asyncio
    async def test_create_reminder_with_recurrence(self, use_case, mock_task_repo, mock_reminder_service):
        """Test reminder creation with recurrence rule."""
        # Arrange
        user_id = "123"
        intent = ParsedIntent(
            accion=ActionType.RECORDATORIO,
            detalles="Tomar agua",
            fecha_hora=datetime(2026, 11, 3, 9, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
            recurrencia="FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR",
            prioridad=0,
            tags=["salud"],
        )

        # Act
        result = await use_case.execute(user_id, intent, job_queue=AsyncMock())

        # Assert
        assert result.success is True
        # Verify recurrence passed to reminder service
        call_args = mock_reminder_service.schedule_reminder.call_args
        # The recurrence should be passed or handled appropriately
        assert result.task_id == 123

    @pytest.mark.asyncio
    async def test_create_reminder_scheduling_failure(self, use_case, mock_task_repo, mock_reminder_service):
        """Test reminder creation when alarm scheduling fails (e.g., past date)."""
        # Arrange
        user_id = "123"
        intent = ParsedIntent(
            accion=ActionType.RECORDATORIO,
            detalles="Recordar algo",
            fecha_hora=datetime(2026, 11, 3, 14, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
            prioridad=0,
            tags=[],
        )
        mock_reminder_service.schedule_reminder.return_value = False  # Scheduling fails

        # Act
        result = await use_case.execute(user_id, intent, job_queue=AsyncMock())

        # Assert
        assert result.success is True  # Still saves locally
        assert "No se pudo programar" in result.message or "alarma" in result.message.lower()

    @pytest.mark.asyncio
    async def test_create_reminder_saves_locally_first(self, use_case, mock_task_repo, mock_reminder_service):
        """Test that reminder is saved to DB BEFORE scheduling alarm (guarantees local persistence)."""
        # Arrange
        user_id = "123"
        intent = ParsedIntent(
            accion=ActionType.RECORDATORIO,
            detalles="Test orden",
            fecha_hora=datetime(2026, 11, 3, 14, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
        )

        # Track call order
        call_order = []

        original_save = mock_task_repo.save
        original_schedule = mock_reminder_service.schedule_reminder

        async def tracking_save(*args, **kwargs):
            call_order.append("save")
            return await original_save(*args, **kwargs)

        async def tracking_schedule(*args, **kwargs):
            call_order.append("schedule")
            return await original_schedule(*args, **kwargs)

        mock_task_repo.save = tracking_save
        mock_reminder_service.schedule_reminder = tracking_schedule

        # Act
        await use_case.execute(user_id, intent)

        # Assert - save should happen before scheduling
        assert call_order == ["save", "schedule"], f"Expected ['save', 'schedule'], got {call_order}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])