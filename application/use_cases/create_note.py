"""
CreateNoteUseCase - Caso de uso para crear notas.

Separa la lógica de negocio del framework Telegram.
Orquesta TaskRepository (sin CalendarService ni ReminderService).
"""
from dataclasses import dataclass
from typing import Optional

from application.services.ai_service import ActionType, ParsedIntent
from infrastructure.database.repositories.task_repo import TaskRepository, TaskType, TaskStatus
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


class CreateNoteUseCase:
    """
    Caso de uso para crear notas (información sin fecha).

    Responsabilidades:
    - Guardar en BD (persistencia local garantizada)
    - NO sincronizar con Calendar (las notas no van a Calendar)
    - NO programar alarma (las notas no tienen alarma)
    """

    def __init__(
        self,
        task_repo: TaskRepository,
    ):
        self._task_repo = task_repo

    async def execute(
        self,
        user_id: str,
        intent: ParsedIntent,
    ) -> UseCaseResult:
        """
        Ejecuta la creación de una nota.

        Args:
            user_id: ID del usuario (chat_id de Telegram)
            intent: Intención parseada por la IA

        Returns:
            UseCaseResult con resultado de la operación
        """
        # Validación: NOTA no requiere fecha/hora (es opcional)
        # Las notas pueden tener fecha_hora si el usuario la especifica, pero no es obligatoria

        # Guardar en BD
        from infrastructure.database.repositories.task_repo import TaskType, TaskStatus

        task_id = await self._task_repo.save(
            telefono_id=user_id,
            tipo=TaskType.NOTA,
            detalles=intent.detalles,
            fecha_hora=intent.fecha_hora,  # Puede ser None
            recurrencia=intent.recurrencia,
            prioridad=intent.prioridad,
            tags=intent.tags,
            calendar_event_id=None,  # Las notas no van a Calendar
        )

        logger.info("note_saved_locally", task_id=task_id, user_id=user_id)

        # Construir respuesta
        message = self._build_confirmation_message(intent, task_id)

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