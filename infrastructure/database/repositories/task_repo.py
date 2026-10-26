"""
Repositorio de tareas/notas - Capa de acceso a datos.

Encapsula todas las queries SQL relacionadas con tareas.
Versión mejorada con:
- Soporte para recurrencia (RRULE)
- Prioridad y tags
- Sincronización con Google Calendar (calendar_event_id)
- Búsqueda full-text
- Listado con filtros
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
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
    # Nuevos campos
    recurrencia: Optional[str] = None
    prioridad: int = 0
    tags: List[str] = None
    calendar_event_id: Optional[str] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


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
        recurrencia: Optional[str] = None,
        prioridad: int = 0,
        tags: Optional[List[str]] = None,
        calendar_event_id: Optional[str] = None,
    ) -> int:
        """
        Guarda una nueva tarea.

        Args:
            telefono_id: ID del usuario (chat_id de Telegram)
            tipo: Tipo de tarea (EVENTO, RECORDATORIO, NOTA)
            detalles: Descripción de la tarea
            fecha_hora: Fecha/hora opcional (aware datetime)
            estado: Estado inicial (default: PENDIENTE)
            recurrencia: RRULE string opcional
            prioridad: -1 (baja), 0 (normal), 1 (alta)
            tags: Lista de tags
            calendar_event_id: ID de evento en Google Calendar

        Returns:
            ID de la tarea creada
        """
        if tags is None:
            tags = []

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO tareas (
                    telefono_id, tipo, detalles, fecha_hora, estado,
                    recurrencia, prioridad, tags, calendar_event_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
            """, telefono_id, tipo.value, detalles, fecha_hora, estado.value,
                recurrencia, prioridad, tags, calendar_event_id)

        task_id = row["id"]
        logger.info("task_saved", task_id=task_id, tipo=tipo.value,
                   telefono_id=telefono_id, has_recurrence=bool(recurrencia))
        return task_id

    async def get_pending(self, telefono_id: str) -> List[Task]:
        """Obtiene todas las tareas pendientes de un usuario."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, telefono_id, tipo, detalles, fecha_hora, estado,
                       creado_en, actualizado_en, recurrencia, prioridad, tags, calendar_event_id
                FROM tareas
                WHERE telefono_id = $1 AND estado = $2
                ORDER BY
                    CASE WHEN prioridad = 1 THEN 0 ELSE 1 END,
                    fecha_hora NULLS LAST,
                    creado_en
            """, telefono_id, TaskStatus.PENDIENTE.value)

        return [self._row_to_task(row) for row in rows]

    async def get_notes(self, telefono_id: str) -> List[Task]:
        """Obtiene solo notas (sin fecha) pendientes de un usuario."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, telefono_id, tipo, detalles, fecha_hora, estado,
                       creado_en, actualizado_en, recurrencia, prioridad, tags, calendar_event_id
                FROM tareas
                WHERE telefono_id = $1 AND tipo = $2 AND estado = $3
                ORDER BY creado_en DESC
            """, telefono_id, TaskType.NOTA.value, TaskStatus.PENDIENTE.value)

        return [self._row_to_task(row) for row in rows]

    async def get_last_task(self, telefono_id: str) -> Optional[Task]:
        """Obtiene la última tarea creada por el usuario (para deshacer)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, telefono_id, tipo, detalles, fecha_hora, estado,
                       creado_en, actualizado_en, recurrencia, prioridad, tags, calendar_event_id
                FROM tareas
                WHERE telefono_id = $1
                ORDER BY id DESC
                LIMIT 1
            """, telefono_id)

        return self._row_to_task(row) if row else None

    async def get_task_by_id(self, task_id: int) -> Optional[Task]:
        """Obtiene una tarea por su ID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, telefono_id, tipo, detalles, fecha_hora, estado,
                       creado_en, actualizado_en, recurrencia, prioridad, tags, calendar_event_id
                FROM tareas
                WHERE id = $1
            """, task_id)

        return self._row_to_task(row) if row else None

    async def get_tasks_by_date_range(
        self,
        telefono_id: str,
        start_date: datetime,
        end_date: datetime,
        estado: Optional[TaskStatus] = None
    ) -> List[Task]:
        """Obtiene tareas en un rango de fechas."""
        async with self._pool.acquire() as conn:
            if estado:
                rows = await conn.fetch("""
                    SELECT id, telefono_id, tipo, detalles, fecha_hora, estado,
                           creado_en, actualizado_en, recurrencia, prioridad, tags, calendar_event_id
                    FROM tareas
                    WHERE telefono_id = $1 AND estado = $2
                    AND fecha_hora >= $3 AND fecha_hora < $4
                    ORDER BY fecha_hora, creado_en
                """, telefono_id, estado.value, start_date, end_date)
            else:
                rows = await conn.fetch("""
                    SELECT id, telefono_id, tipo, detalles, fecha_hora, estado,
                           creado_en, actualizado_en, recurrencia, prioridad, tags, calendar_event_id
                    FROM tareas
                    WHERE telefono_id = $1
                    AND fecha_hora >= $2 AND fecha_hora < $3
                    ORDER BY fecha_hora, creado_en
                """, telefono_id, start_date, end_date)

        return [self._row_to_task(row) for row in rows]

    async def search_tasks(
        self,
        telefono_id: str,
        query: str,
        estado: Optional[TaskStatus] = None,
        limit: int = 20
    ) -> List[Task]:
        """
        Busca tareas por texto en detalles (full-text simple).
        """
        async with self._pool.acquire() as conn:
            if estado:
                rows = await conn.fetch("""
                    SELECT id, telefono_id, tipo, detalles, fecha_hora, estado,
                           creado_en, actualizado_en, recurrencia, prioridad, tags, calendar_event_id
                    FROM tareas
                    WHERE telefono_id = $1 AND estado = $2
                    AND (detalles ILIKE $3 OR tags && string_to_array($3, ' '))
                    ORDER BY
                        CASE WHEN prioridad = 1 THEN 0 ELSE 1 END,
                        fecha_hora NULLS LAST,
                        creado_en DESC
                    LIMIT $4
                """, telefono_id, estado.value, f"%{query}%", limit)
            else:
                rows = await conn.fetch("""
                    SELECT id, telefono_id, tipo, detalles, fecha_hora, estado,
                           creado_en, actualizado_en, recurrencia, prioridad, tags, calendar_event_id
                    FROM tareas
                    WHERE telefono_id = $1
                    AND (detalles ILIKE $2 OR tags && string_to_array($2, ' '))
                    ORDER BY
                        CASE WHEN prioridad = 1 THEN 0 ELSE 1 END,
                        fecha_hora NULLS LAST,
                        creado_en DESC
                    LIMIT $3
                """, telefono_id, f"%{query}%", limit)

        return [self._row_to_task(row) for row in rows]

    async def get_tasks_by_tag(
        self,
        telefono_id: str,
        tag: str,
        estado: Optional[TaskStatus] = None
    ) -> List[Task]:
        """Obtiene tareas filtradas por tag."""
        async with self._pool.acquire() as conn:
            if estado:
                rows = await conn.fetch("""
                    SELECT id, telefono_id, tipo, detalles, fecha_hora, estado,
                           creado_en, actualizado_en, recurrencia, prioridad, tags, calendar_event_id
                    FROM tareas
                    WHERE telefono_id = $1 AND estado = $2
                    AND $3 = ANY(tags)
                    ORDER BY fecha_hora NULLS LAST, creado_en
                """, telefono_id, estado.value, tag.lower())
            else:
                rows = await conn.fetch("""
                    SELECT id, telefono_id, tipo, detalles, fecha_hora, estado,
                           creado_en, actualizado_en, recurrencia, prioridad, tags, calendar_event_id
                    FROM tareas
                    WHERE telefono_id = $1
                    AND $2 = ANY(tags)
                    ORDER BY fecha_hora NULLS LAST, creado_en
                """, telefono_id, tag.lower())

        return [self._row_to_task(row) for row in rows]

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

        count = int(result.split()[-1]) if result.startswith("DELETE") else 0
        logger.info("tasks_deleted_by_date", telefono_id=telefono_id, date=date_str, count=count)
        return count

    async def update_task(
        self,
        task_id: int,
        detalles: Optional[str] = None,
        fecha_hora: Optional[datetime] = None,
        recurrencia: Optional[str] = None,
        prioridad: Optional[int] = None,
        tags: Optional[List[str]] = None,
        calendar_event_id: Optional[str] = None,
    ) -> bool:
        """
        Actualiza campos de una tarea existente.

        Returns:
            True si se actualizó, False si no existía
        """
        # Construir query dinámicamente
        fields = []
        values = []
        param_num = 1

        if detalles is not None:
            fields.append(f"detalles = ${param_num}")
            values.append(detalles)
            param_num += 1
        if fecha_hora is not None:
            fields.append(f"fecha_hora = ${param_num}")
            values.append(fecha_hora)
            param_num += 1
        if recurrencia is not None:
            fields.append(f"recurrencia = ${param_num}")
            values.append(recurrencia)
            param_num += 1
        if prioridad is not None:
            fields.append(f"prioridad = ${param_num}")
            values.append(prioridad)
            param_num += 1
        if tags is not None:
            fields.append(f"tags = ${param_num}")
            values.append(tags)
            param_num += 1
        if calendar_event_id is not None:
            fields.append(f"calendar_event_id = ${param_num}")
            values.append(calendar_event_id)
            param_num += 1

        if not fields:
            return False

        fields.append(f"actualizado_en = NOW()")
        values.append(task_id)

        query = f"UPDATE tareas SET {', '.join(fields)} WHERE id = ${param_num}"

        async with self._pool.acquire() as conn:
            result = await conn.execute(query, *values)

        updated = result == "UPDATE 1"
        if updated:
            logger.info("task_updated", task_id=task_id, fields=list(fields))
        else:
            logger.warning("task_update_not_found", task_id=task_id)
        return updated

    async def get_recurring_tasks(self, telefono_id: str) -> List[Task]:
        """Obtiene tareas con recurrencia activa."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, telefono_id, tipo, detalles, fecha_hora, estado,
                       creado_en, actualizado_en, recurrencia, prioridad, tags, calendar_event_id
                FROM tareas
                WHERE telefono_id = $1 AND estado = $2 AND recurrencia IS NOT NULL
                ORDER BY fecha_hora NULLS LAST, creado_en
            """, telefono_id, TaskStatus.PENDIENTE.value)

        return [self._row_to_task(row) for row in rows]

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
            recurrencia=row["recurrencia"],
            prioridad=row["prioridad"] or 0,
            tags=row["tags"] or [],
            calendar_event_id=row["calendar_event_id"],
        )