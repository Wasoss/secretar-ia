"""
CreateDailyTaskUseCase - Caso de uso para crear tareas diarias con subtareas.

Separa la lógica de negocio del framework Telegram.
Orquesta TaskRepository (sin CalendarService ni ReminderService).
"""
import re
from dataclasses import dataclass
from typing import Optional, List

from application.services.ai_service import ActionType, ParsedIntent
from infrastructure.database.repositories.task_repo import TaskRepository, TaskType, TaskStatus, SubTask
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


def parse_subtasks(text: str) -> List[SubTask]:
    """
    Parsea los sub-items del texto (separados por comas, "y", saltos de línea, punto y coma).

    Args:
        text: Texto con los items separados

    Returns:
        Lista de SubTask con IDs únicos, texto, completado=False, orden
    """
    import uuid

    # Separadores comunes: coma, "y", salto de línea, punto y coma
    items = re.split(r'[,;\n]|\s+y\s+', text)
    items = [item.strip() for item in items if item.strip()]

    if not items:
        return []

    subtareas = []
    for i, item in enumerate(items):
        subtareas.append(SubTask(
            id=str(uuid.uuid4())[:8],  # ID corto
            texto=item,
            completado=False,
            orden=i
        ))

    return subtareas


class CreateDailyTaskUseCase:
    """
    Caso de uso para crear tareas diarias con subtareas (TAREA_DIARIA).

    Responsabilidades:
    - Parsear el texto en subtareas (soporta comas, "y", saltos de línea, punto y coma)
    - Guardar en BD con subtareas JSON
    - NO sincronizar con Calendar (las tareas diarias no van a Calendar)
    - NO programar alarma (las tareas diarias no tienen alarma)
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
        Ejecuta la creación de una tarea diaria.

        Args:
            user_id: ID del usuario (chat_id de Telegram)
            intent: Intención parseada por la IA

        Returns:
            UseCaseResult con resultado de la operación
        """
        # Parsear sub-items del texto
        subtareas = parse_subtasks(intent.detalles)

        if not subtareas:
            return UseCaseResult(
                success=False,
                error="No pude identificar los items de la lista. Probá: \"Lista de hoy: estudiar, preparar clases, limpiar\""
            )

        # Guardar en BD con subtareas
        from infrastructure.database.repositories.task_repo import TaskType, TaskStatus

        task_id = await self._task_repo.save(
            telefono_id=user_id,
            tipo=TaskType.TAREA_DIARIA,
            detalles=intent.detalles,  # Título de la lista
            fecha_hora=None,  # Sin fecha específica, es para hoy
            estado=TaskStatus.PENDIENTE,
            prioridad=intent.prioridad,
            tags=intent.tags,
            calendar_event_id=None,  # No va a Calendar
            subtareas=subtareas,
        )

        logger.info("daily_task_saved_locally", task_id=task_id, user_id=user_id, subtasks_count=len(subtareas))

        # Construir respuesta
        message = self._build_confirmation_message(intent, task_id, subtareas)

        return UseCaseResult(
            success=True,
            task_id=task_id,
            message=message,
        )

    def _build_confirmation_message(
        self,
        intent: ParsedIntent,
        task_id: int,
        subtareas: List[SubTask],
    ) -> str:
        """Construye mensaje de confirmación con botones para tachar."""
        from utils.formatters import build_confirmation_message

        # Usar el formateador pero adaptado para tareas diarias
        message = f"☑️ <b>Lista diaria creada</b> (ID: {task_id})\n"
        message += f"📝 {intent.detalles}\n\n"

        for sub in subtareas:
            message += f"  ☐ {sub.texto}\n"

        message += f"\n📋 Total: {len(subtareas)} items"
        if intent.prioridad == 1:
            message += " 🔴"
        elif intent.prioridad == -1:
            message += " 🟢"
        if intent.tags:
            message += f" #{' #'.join(intent.tags)}"

        return message