"""
UpdateEventUseCase - Caso de uso para actualizar eventos existentes.

Separa la lógica de negocio del framework Telegram.
Orquesta TaskRepository y CalendarService.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

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


class UpdateEventUseCase:
    """
    Caso de uso para actualizar eventos existentes.

    Responsabilidades:
    - Validar que la tarea sea un EVENTO
    - Actualizar en BD
    - Sincronizar con Google Calendar
    - Manejar conflictos y errores de Calendar sin bloquear actualización local
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
        task_id: int,
        nuevo_detalles: Optional[str] = None,
        nueva_fecha_hora: Optional[datetime] = None,
        nueva_recurrencia: Optional[str] = None,
        nueva_prioridad: Optional[int] = None,
        nuevos_tags: Optional[List[str]] = None,
    ) -> UseCaseResult:
        """
        Ejecuta la actualización de un evento.

        Args:
            user_id: ID del usuario (chat_id de Telegram)
            task_id: ID de la tarea a actualizar
            nuevo_detalles: Nuevo título/detalles (opcional)
            nueva_fecha_hora: Nueva fecha/hora (opcional)
            nueva_recurrencia: Nueva recurrencia RRULE (opcional)
            nueva_prioridad: Nueva prioridad (opcional)
            nuevos_tags: Nuevos tags (opcional)

        Returns:
            UseCaseResult con resultado de la operación
        """
        # Buscar tarea existente
        task = await self._task_repo.get_task_by_id(task_id)
        if not task:
            return UseCaseResult(
                success=False,
                error=f"Tarea {task_id} no encontrada"
            )

        # Validar que sea un EVENTO
        if task.tipo != TaskType.EVENTO:
            return UseCaseResult(
                success=False,
                error=f"La tarea {task_id} no es un evento (es {task.tipo.value})"
            )

        # Validar propiedad
        if task.telefono_id != user_id:
            return UseCaseResult(
                success=False,
                error="No tenés permiso para editar este evento"
            )

        # Preparar campos para actualizar (solo los que no son None)
        update_kwargs = {}
        if nuevo_detalles is not None:
            update_kwargs["detalles"] = nuevo_detalles
        if nueva_fecha_hora is not None:
            update_kwargs["fecha_hora"] = nueva_fecha_hora
        if nueva_recurrencia is not None:
            update_kwargs["recurrencia"] = nueva_recurrencia
        if nueva_prioridad is not None:
            update_kwargs["prioridad"] = nueva_prioridad
        if nuevos_tags is not None:
            update_kwargs["tags"] = nuevos_tags

        if not update_kwargs:
            return UseCaseResult(
                success=False,
                error="No hay campos para actualizar"
            )

        # 1. Actualizar en BD primero
        updated = await self._task_repo.update_task(task_id, **update_kwargs)
        if not updated:
            return UseCaseResult(
                success=False,
                error="No se pudo actualizar la tarea"
            )

        logger.info("event_updated_locally", task_id=task_id, user_id=user_id, fields=list(update_kwargs.keys()))

        # 2. Sincronizar con Google Calendar si tiene calendar_event_id
        calendar_event_id = None
        calendar_warning = ""

        if task.calendar_event_id:
            start_dt = nueva_fecha_hora if nueva_fecha_hora is not None else task.fecha_hora
            end_dt = start_dt + __import__('datetime').timedelta(hours=1)

            # Verificar conflictos (solo si cambia fecha/hora)
            if nueva_fecha_hora is not None or nueva_recurrencia is not None:
                try:
                    # Excluir el propio evento
                    conflicts = await self._calendar_service.check_conflicts(
                        start_dt, end_dt, exclude_event_id=task.calendar_event_id
                    )
                    if conflicts:
                        conflict_names = [c.get('summary', 'Sin título') for c in conflicts[:3]]
                        calendar_warning = f"\n⚠️ <b>Conflicto en Calendar</b>: {', '.join(conflict_names)}"
                except Exception as e:
                    logger.warning("conflict_check_failed", error=str(e))

            # Intentar actualizar en Calendar
            try:
                updated_event = await self._calendar_service.update_event(
                    event_id=task.calendar_event_id,
                    summary=nuevo_detalles if nuevo_detalles is not None else task.detalles,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    recurrence=nueva_recurrencia if nueva_recurrencia is not None else task.recurrencia,
                )
                if updated_event:
                    calendar_event_id = task.calendar_event_id
                    logger.info("calendar_event_updated", local_task_id=task_id, calendar_event_id=calendar_event_id)
                else:
                    calendar_warning += "\n⚠️ No se pudo sincronizar con Google Calendar."
            except Exception as e:
                logger.error("calendar_update_failed", error=str(e), task_id=task_id)
                error_msg = str(e)
                if "credenciales" in error_msg.lower() or "token" in error_msg.lower() or "oauth" in error_msg.lower():
                    calendar_warning += "\n⚠️ <b>Sin token OAuth válido</b> - Usá /calendar_status para detalles"
                elif "conflict" in error_msg.lower():
                    calendar_warning += "\n⚠️ Conflicto en Calendar"
                else:
                    calendar_warning += f"\n⚠️ Error Calendar: {error_msg[:80]}"

        # 3. Construir respuesta
        message = self._build_confirmation_message(task, update_kwargs, calendar_event_id)
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
        task,
        updated_fields: dict,
        calendar_event_id: Optional[str],
    ) -> str:
        """Construye mensaje de confirmación."""
        from utils.formatters import build_confirmation_message

        # Usar los valores actualizados o los originales
        detalles = updated_fields.get("detalles", task.detalles)
        fecha_hora = updated_fields.get("fecha_hora", task.fecha_hora)
        recurrencia = updated_fields.get("recurrencia", task.recurrencia)
        prioridad = updated_fields.get("prioridad", task.prioridad)
        tags = updated_fields.get("tags", task.tags)

        # Crear intent temporal para usar el formateador
        from application.services.ai_service import ActionType, ParsedIntent
        intent = ParsedIntent(
            accion=ActionType.EVENTO,
            detalles=detalles,
            fecha_hora=fecha_hora,
            recurrencia=recurrencia,
            prioridad=prioridad,
            tags=tags,
        )

        message = "🔄 <b>Evento actualizado</b>\n\n"
        message += build_confirmation_message(
            action=intent.accion,
            details=detalles,
            task_id=task.id,
            fecha_hora=fecha_hora,
            recurrencia=recurrencia,
            prioridad=prioridad,
            tags=tags,
            calendar_event_id=calendar_event_id,
        )

        # Cambiar el icono inicial
        message = message.replace("📅 Guardado como", "🔄 Actualizado")

        return message