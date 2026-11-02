"""
CreateReminderUseCase - Caso de uso para crear recordatorios.

Separa la lógica de negocio del framework Telegram.
Orquesta TaskRepository y ReminderService.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from application.services.ai_service import ActionType, ParsedIntent
from infrastructure.database.repositories.task_repo import TaskRepository, TaskType, TaskStatus
from application.services.reminder_service import ReminderService
from config.settings import settings
from config.logging import get_logger

logger = get_logger(__name__)


@dataclass
class UseCaseResult:
    """Resultado de un caso de uso."""
    success: bool
    task_id: Optional[int] = None
    calendar_event_id: Optional[str] = None
    message: str = ""
    error: str = ""


class CreateReminderUseCase:
    """
    Caso de uso para crear recordatorios (alarmas locales).

    Responsabilidades:
    - Validar que el recordatorio tenga fecha/hora
    - Guardar en BD (persistencia local garantizada)
    - Programar alarma local via ReminderService
    - Manejar fallos de programación sin bloquear guardado local
    """

    def __init__(
        self,
        task_repo: TaskRepository,
        reminder_service: ReminderService,
    ):
        self._task_repo = task_repo
        self._reminder_service = reminder_service

    async def execute(
        self,
        user_id: str,
        intent: ParsedIntent,
        job_queue=None,
    ) -> UseCaseResult:
        """
        Ejecuta la creación de un recordatorio.

        Args:
            user_id: ID del usuario (chat_id de Telegram)
            intent: Intención parseada por la IA

        Returns:
            UseCaseResult con resultado de la operación
        """
        # Validación: RECORDATORIO requiere fecha/hora
        if not intent.fecha_hora:
            return UseCaseResult(
                success=False,
                error="Recordatorio sin fecha/hora. Para programar una alarma necesitás día y hora."
            )

        # 1. Guardar SIEMPRE en BD primero (garantiza persistencia local)
        from infrastructure.database.repositories.task_repo import TaskType, TaskStatus

        task_id = await self._task_repo.save(
            telefono_id=user_id,
            tipo=TaskType.RECORDATORIO,
            detalles=intent.detalles,
            fecha_hora=intent.fecha_hora,
            recurrencia=intent.recurrencia,
            prioridad=intent.prioridad,
            tags=intent.tags,
            calendar_event_id=None,  # Los recordatorios no van a Calendar
        )

        logger.info("reminder_saved_locally", task_id=task_id, user_id=user_id)

        # 2. Intentar programar alarma local
        reminder_warning = ""
        alarm_scheduled = False

        try:
            alarm_scheduled = await self._reminder_service.schedule_reminder(
                job_queue=job_queue,  # Se pasa desde el handler con context.job_queue
                chat_id=int(user_id),
                text=intent.detalles,
                fecha_hora=intent.fecha_hora,
            )
            if alarm_scheduled:
                logger.info("reminder_alarm_scheduled", task_id=task_id, user_id=user_id)
            else:
                logger.warning("reminder_alarm_scheduling_failed", task_id=task_id, user_id=user_id)
                reminder_warning = "\n⚠️ No se pudo programar la alarma (¿fecha pasada?)."
        except Exception as e:
            logger.error("reminder_scheduling_failed", error=str(e), task_id=task_id)
            reminder_warning = f"\n⚠️ Error programando alarma: {str(e)[:80]}"

        # 3. Construir respuesta
        message = self._build_confirmation_message(intent, task_id)
        if reminder_warning:
            message += reminder_warning
        elif alarm_scheduled:
            message += " ⏰ Alarma programada."

        return UseCaseResult(
            success=True,
            task_id=task_id,
            message=message,
        )

    def _build_confirmation_message(
        self,
        intent: ParsedIntent,
        task_id: int,
    ) -> str:
        """Construye mensaje de confirmación."""
        from utils.formatters import build_confirmation_message
        return build_confirmation_message(
            action=intent.accion,
            details=intent.detalles,
            task_id=task_id,
            fecha_hora=intent.fecha_hora,
            recurrencia=intent.recurrencia,
            prioridad=intent.prioridad,
            tags=intent.tags,
            calendar_event_id=None,
        )