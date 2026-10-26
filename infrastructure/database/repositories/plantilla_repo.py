"""
Repositorio de plantillas diarias - Capa de acceso a datos.

Encapsula queries para plantillas de tareas diarias.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any
import asyncpg
import json
import uuid

from config.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class PlantillaDiaria:
    """Entidad de dominio para una plantilla diaria."""
    id: int
    telefono_id: str
    nombre: str
    items: List[Dict[str, Any]]  # [{"texto": "...", "orden": 0}, ...]
    activa: bool
    creado_en: datetime
    actualizado_en: datetime


class PlantillaRepository:
    """Repositorio para plantillas diarias."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def save(
        self,
        telefono_id: str,
        nombre: str,
        items: List[Dict[str, Any]],
        activa: bool = True,
    ) -> int:
        """
        Guarda una nueva plantilla (o actualiza si ya existe con ese nombre).

        Args:
            telefono_id: ID del usuario
            nombre: Nombre de la plantilla (ej: "Día laboral")
            items: Lista de items [{"texto": "estudiar 2h", "orden": 0}, ...]
            activa: Si es la plantilla activa por defecto

        Returns:
            ID de la plantilla
        """
        items_json = json.dumps(items)

        # Si se marca como activa, desactivar otras del mismo usuario
        if activa:
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    UPDATE plantillas_diarias
                    SET activa = FALSE, actualizado_en = NOW()
                    WHERE telefono_id = $1 AND activa = TRUE
                """, telefono_id)

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO plantillas_diarias (telefono_id, nombre, items_json, activa)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (telefono_id, nombre) DO UPDATE SET
                    items_json = EXCLUDED.items_json,
                    activa = EXCLUDED.activa,
                    actualizado_en = NOW()
                RETURNING id
            """, telefono_id, nombre, items_json, activa)

        plantilla_id = row["id"]
        logger.info("plantilla_saved", plantilla_id=plantilla_id, nombre=nombre,
                   telefono_id=telefono_id, items_count=len(items))
        return plantilla_id

    async def get_active(self, telefono_id: str) -> Optional[PlantillaDiaria]:
        """Obtiene la plantilla activa del usuario."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, telefono_id, nombre, items_json, activa, creado_en, actualizado_en
                FROM plantillas_diarias
                WHERE telefono_id = $1 AND activa = TRUE
                LIMIT 1
            """, telefono_id)

        return self._row_to_plantilla(row) if row else None

    async def get_all(self, telefono_id: str) -> List[PlantillaDiaria]:
        """Obtiene todas las plantillas del usuario."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, telefono_id, nombre, items_json, activa, creado_en, actualizado_en
                FROM plantillas_diarias
                WHERE telefono_id = $1
                ORDER BY activa DESC, creado_en DESC
            """, telefono_id)

        return [self._row_to_plantilla(row) for row in rows]

    async def get_by_id(self, plantilla_id: int) -> Optional[PlantillaDiaria]:
        """Obtiene una plantilla por ID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, telefono_id, nombre, items_json, activa, creado_en, actualizado_en
                FROM plantillas_diarias
                WHERE id = $1
            """, plantilla_id)

        return self._row_to_plantilla(row) if row else None

    async def set_active(self, telefono_id: str, plantilla_id: int) -> bool:
        """Marca una plantilla como activa (desactiva las demás)."""
        async with self._pool.acquire() as conn:
            # Verificar que pertenece al usuario
            row = await conn.fetchrow("""
                SELECT id FROM plantillas_diarias
                WHERE id = $1 AND telefono_id = $2
            """, plantilla_id, telefono_id)

            if not row:
                return False

            # Desactivar todas y activar la seleccionada
            await conn.execute("""
                UPDATE plantillas_diarias
                SET activa = FALSE, actualizado_en = NOW()
                WHERE telefono_id = $1
            """, telefono_id)

            await conn.execute("""
                UPDATE plantillas_diarias
                SET activa = TRUE, actualizado_en = NOW()
                WHERE id = $1
            """, plantilla_id)

        logger.info("plantilla_activated", plantilla_id=plantilla_id, telefono_id=telefono_id)
        return True

    async def delete(self, plantilla_id: int, telefono_id: str) -> bool:
        """Elimina una plantilla."""
        async with self._pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM plantillas_diarias
                WHERE id = $1 AND telefono_id = $2
            """, plantilla_id, telefono_id)

        deleted = result == "DELETE 1"
        if deleted:
            logger.info("plantilla_deleted", plantilla_id=plantilla_id, telefono_id=telefono_id)
        return deleted

    async def update_items(self, plantilla_id: int, items: List[Dict[str, Any]]) -> bool:
        """Actualiza los items de una plantilla."""
        items_json = json.dumps(items)

        async with self._pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE plantillas_diarias
                SET items_json = $1, actualizado_en = NOW()
                WHERE id = $2
            """, items_json, plantilla_id)

        updated = result == "UPDATE 1"
        if updated:
            logger.info("plantilla_items_updated", plantilla_id=plantilla_id)
        return updated

    def _row_to_plantilla(self, row: asyncpg.Record) -> PlantillaDiaria:
        """Convierte un record a entidad PlantillaDiaria."""
        items = []
        if row["items_json"]:
            try:
                items = json.loads(row["items_json"]) if isinstance(row["items_json"], str) else row["items_json"]
            except Exception:
                items = []

        return PlantillaDiaria(
            id=row["id"],
            telefono_id=row["telefono_id"],
            nombre=row["nombre"],
            items=items,
            activa=row["activa"],
            creado_en=row["creado_en"],
            actualizado_en=row["actualizado_en"],
        )