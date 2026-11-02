"""
CreateEventUseCase - Caso de uso para crear eventos.

Separa la lógica de negocio del framework Telegram.
Orquesta TaskRepository y CalendarService.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from application.services.ai_service import ActionType, ParsedIntent
from infrastructure.database.repositories.task_repo import TaskRepository, TaskType, TaskStatus
from application.services.calendar_service import CalendarService
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


class CreateEventUseCase:
    """
    Caso de uso para crear eventos.

    Responsabilidades:
    - Validar que el evento tenga fecha/hora
    - Guardar en BD (persistencia local garantizada)
    - Sincronizar con Google Calendar
    - Manejar conflictos y errores de Calendar sin bloquear guardado local
    """

    def __init__(
        self,
        task_repo: TaskRepository,
        calendar_service: CalendarService,
    ):
        self._task_repo = task_repo
        self._calendar_service = calendar_service

    async def execute(
        self,
        user_id: str,
        intent: ParsedIntent,
    ) -> UseCaseResult:
        """
        Ejecuta la creación de un evento.

        Args:
            user_id: ID del usuario (chat_id de Telegram)
            intent: Intención parseada por la IA

        Returns:
            UseCaseResult con resultado de la operación
        """
        # Validación: EVENTO requiere fecha/hora
        if not intent.fecha_hora:
            return UseCaseResult(
                success=False,
                error="Evento sin fecha/hora. Para agendar en Calendar necesitás día y hora."
            )

        # 1. Guardar SIEMPRE en BD primero (garantiza persistencia local)
        task_id = await self._task_repo.save(
            telefono_id=user_id,
            tipo=TaskType.EVENTO,
            detalles=intent.detalles,
            fecha_hora=intent.fecha_hora,
            recurrencia=intent.recurrencia,
            prioridad=intent.prioridad,
            tags=intent.tags,
            calendar_event_id=None,  # Se actualiza después si sincroniza
        )

        logger.info("event_saved_locally", task_id=task_id, user_id=user_id)

        # 2. Intentar sincronizar con Google Calendar
        calendar_event_id = None
        calendar_warning = ""

        start_dt = intent.fecha_hora
        end_dt = start_dt + __import__('datetime').timedelta(hours=1)

        # Verificar conflictos (solo avisar, no bloquear)
        try:
            conflicts = await self._calendar_service.check_conflicts(start_dt, end_dt)
            if conflicts:
                conflict_names = [c.get('summary', 'Sin título') for c in conflicts[:3]]
                calendar_warning = f"\n⚠️ <b>Conflicto en Calendar</b>: {', '.join(conflict_names)}"
        except Exception as e:
            logger.warning("conflict_check_failed", error=str(e))

        # Intentar crear en Calendar
        try:
            created_event = await self._calendar_service.create_event(
                summary=intent.detalles,
                start_dt=start_dt,
                end_dt=end_dt,
                recurrence=intent.recurrencia,
            )
            if created_event:
                calendar_event_id = created_event.get('id')
                # Actualizar BD con calendar_event_id
                await self._task_repo.update_task(task_id, calendar_event_id=calendar_event_id)
                logger.info("calendar_event_synced", local_task_id=task_id, calendar_event_id=calendar_event_id)
            else:
                calendar_warning += "\n⚠️ No se pudo sincronizar con Google Calendar."
        except Exception as e:
            logger.error("calendar_sync_failed", error=str(e), task_id=task_id)
            error_msg = str(e)
            if "credenciales" in error_msg.lower() or "token" in error_msg.lower() or "oauth" in error_msg.lower():
                calendar_warning += "\n⚠️ <b>Sin token OAuth válido</b> - Usá /calendar_status para detalles"
            elif "conflict" in error_msg.lower():
                calendar_warning += "\n⚠️ Conflicto en Calendar"
            else:
                calendar_warning += f"\n⚠️ Error Calendar: {error_msg[:80]}"

        # 3. Construir respuesta
        message = self._build_confirmation_message(intent, task_id, calendar_event_id)
        if calendar_warning:
            message += calendar_warning

        return UseCaseResult(
            success=True,
            task_id=task_id,
            calendar_event_id=calendar_event_id,
            message=message,
        )

    def _build_confirmation_message(
        self,
        intent: ParsedIntent,
        task_id: int,
        calendar_event_id: Optional[str],
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
            calendar_event_id=calendar_event_id,
        )