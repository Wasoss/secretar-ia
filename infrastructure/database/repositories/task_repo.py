"""
Repositorio de tareas/notas - Capa de acceso a datos.

Encapsula todas las queries SQL relacionadas con tareas.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from enum import Enum
import asyncpg

from config.logging import get_logger

logger = get_logger(__name__)


class TaskType(str, Enum):
    """Tipos de tareas soportados."""
    EVENTO = "EVENTO"
    RECORDATORIO = "RECORDATORIO"
    NOTA = "NOTA"


class TaskStatus(str, Enum):
    """Estados posibles de una tarea."""
    PENDIENTE = "PENDIENTE"
    COMPLETADO = "COMPLETADO"


@dataclass(slots=True)
class Task:
    """Entidad de dominio para una tarea/nota."""
    id: int
    telefono_id: str
    tipo: TaskType
    detalles: str
    fecha_hora: Optional[datetime]
    estado: TaskStatus
    creado_en: datetime
    actualizado_en: datetime


class TaskRepository:
    """Repositorio para operaciones CRUD de tareas."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def save(
        self,
        telefono_id: str,
        tipo: TaskType,
        detalles: str,
        fecha_hora: Optional[datetime] = None,
        estado: TaskStatus = TaskStatus.PENDIENTE,
    ) -> int:
        """
        Guarda una nueva tarea.

        Args:
            telefono_id: ID del usuario (chat_id de Telegram)
            tipo: Tipo de tarea (EVENTO, RECORDATORIO, NOTA)
            detalles: Descripción de la tarea
            fecha_hora: Fecha/hora opcional (aware datetime)
            estado: Estado inicial (default: PENDIENTE)

        Returns:
            ID de la tarea creada
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO tareas (telefono_id, tipo, detalles, fecha_hora, estado)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
            """, telefono_id, tipo.value, detalles, fecha_hora, estado.value)

        task_id = row["id"]
        logger.info("task_saved", task_id=task_id, tipo=tipo.value, telefono_id=telefono_id)
        return task_id

    async def get_pending(self, telefono_id: str) -> list[Task]:
        """Obtiene todas las tareas pendientes de un usuario."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, telefono_id, tipo, detalles, fecha_hora, estado, creado_en, actualizado_en
                FROM tareas
                WHERE telefono_id = $1 AND estado = $2
                ORDER BY fecha_hora NULLS LAST, creado_en
            """, telefono_id, TaskStatus.PENDIENTE.value)

        return [self._row_to_task(row) for row in rows]

    async def get_notes(self, telefono_id: str) -> list[Task]:
        """Obtiene solo notas (sin fecha) pendientes de un usuario."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, telefono_id, tipo, detalles, fecha_hora, estado, creado_en, actualizado_en
                FROM tareas
                WHERE telefono_id = $1 AND tipo = $2 AND estado = $3
                ORDER BY creado_en DESC
            """, telefono_id, TaskType.NOTA.value, TaskStatus.PENDIENTE.value)

        return [self._row_to_task(row) for row in rows]

    async def get_last_task(self, telefono_id: str) -> Optional[Task]:
        """Obtiene la última tarea creada por el usuario (para deshacer)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, telefono_id, tipo, detalles, fecha_hora, estado, creado_en, actualizado_en
                FROM tareas
                WHERE telefono_id = $1
                ORDER BY id DESC
                LIMIT 1
            """, telefono_id)

        return self._row_to_task(row) if row else None

    async def complete(self, task_id: int) -> bool:
        """
        Marca una tarea como completada.

        Returns:
            True si se actualizó, False si no existía
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE tareas
                SET estado = $1, actualizado_en = NOW()
                WHERE id = $2 AND estado = $3
            """, TaskStatus.COMPLETADO.value, task_id, TaskStatus.PENDIENTE.value)

        updated = result == "UPDATE 1"
        if updated:
            logger.info("task_completed", task_id=task_id)
        else:
            logger.warning("task_complete_not_found_or_already_done", task_id=task_id)
        return updated

    async def delete_by_id(self, task_id: int) -> bool:
        """
        Elimina una tarea por ID.

        Returns:
            True si se eliminó, False si no existía
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute("DELETE FROM tareas WHERE id = $1", task_id)

        deleted = result == "DELETE 1"
        if deleted:
            logger.info("task_deleted", task_id=task_id)
        return deleted

    async def delete_by_date(self, telefono_id: str, date_str: str) -> int:
        """
        Elimina todas las tareas de un usuario para una fecha específica.

        Args:
            telefono_id: ID del usuario
            date_str: Fecha en formato 'YYYY-MM-DD'

        Returns:
            Número de tareas eliminadas
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM tareas
                WHERE telefono_id = $1
                AND fecha_hora >= $2::timestamptz
                AND fecha_hora < ($2::timestamptz + INTERVAL '1 day')
            """, telefono_id, date_str)

        # asyncpg devuelve "DELETE N"
        count = int(result.split()[-1]) if result.startswith("DELETE") else 0
        logger.info("tasks_deleted_by_date", telefono_id=telefono_id, date=date_str, count=count)
        return count

    def _row_to_task(self, row: asyncpg.Record) -> Task:
        """Convierte un record de asyncpg a entidad Task."""
        return Task(
            id=row["id"],
            telefono_id=row["telefono_id"],
            tipo=TaskType(row["tipo"]),
            detalles=row["detalles"],
            fecha_hora=row["fecha_hora"],
            estado=TaskStatus(row["estado"]),
            creado_en=row["creado_en"],
            actualizado_en=row["actualizado_en"],
        )