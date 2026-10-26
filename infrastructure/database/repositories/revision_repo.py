"""
Repositorio de revisiones semanales - Capa de acceso a datos.

Encapsula queries para el log histórico de revisiones semanales.
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, List, Dict, Any
import asyncpg
import json

from config.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class RevisionSemanal:
    """Entidad de dominio para una revisión semanal."""
    id: int
    telefono_id: str
    semana_inicio: date
    resumen: Dict[str, Any]  # {tareas_completadas, eventos, objetivos, plantillas_usadas, notas, ...}
    creado_en: datetime


class RevisionRepository:
    """Repositorio para revisiones semanales (log histórico)."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def save(
        self,
        telefono_id: str,
        semana_inicio: date,
        resumen: Dict[str, Any],
    ) -> int:
        """
        Guarda una revisión semanal.

        Args:
            telefono_id: ID del usuario
            semana_inicio: Lunes de la semana (YYYY-MM-DD)
            resumen: Dict con datos de la revisión

        Returns:
            ID de la revisión creada
        """
        resumen_json = json.dumps(resumen, ensure_ascii=False)

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO revisiones_semanales (telefono_id, semana_inicio, resumen_json)
                VALUES ($1, $2, $3)
                ON CONFLICT (telefono_id, semana_inicio) DO UPDATE SET
                    resumen_json = EXCLUDED.resumen_json,
                    creado_en = NOW()
                RETURNING id
            """, telefono_id, semana_inicio, resumen_json)

        revision_id = row["id"]
        logger.info("revision_saved", revision_id=revision_id,
                   telefono_id=telefono_id, semana=str(semana_inicio))
        return revision_id

    async def get_by_week(self, telefono_id: str, semana_inicio: date) -> Optional:
        """Obtiene la revisión de una semana específica."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, telefono_id, semana_inicio, resumen_json, creado_en
                FROM revisiones_semanales
                WHERE telefono_id = $1 AND semana_inicio = $2
            """, telefono_id, semana_inicio)

        return self._row_to_revision(row) if row else None

    async def get_latest(self, telefono_id: str, limit: int = 5) -> List:
        """Obtiene las últimas revisiones del usuario."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, telefono_id, semana_inicio, resumen_json, creado_en
                FROM revisiones_semanales
                WHERE telefono_id = $1
                ORDER BY semana_inicio DESC
                LIMIT $2
            """, telefono_id, limit)

        return [self._row_to_revision(row) for row in rows]

    async def get_by_id(self, revision_id: int) -> Optional:
        """Obtiene una revisión por ID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, telefono_id, semana_inicio, resumen_json, creado_en
                FROM revisiones_semanales
                WHERE id = $1
            """, revision_id)

        return self._row_to_revision(row) if row else None

    def _row_to_revision(self, row: asyncpg.Record) -> RevisionSemanal:
        """Convierte un record a entidad RevisionSemanal."""
        resumen = {}
        if row["resumen_json"]:
            try:
                resumen = json.loads(row["resumen_json"]) if isinstance(row["resumen_json"], str) else row["resumen_json"]
            except Exception:
                resumen = {}

        return RevisionSemanal(
            id=row["id"],
            telefono_id=row["telefono_id"],
            semana_inicio=row["semana_inicio"],
            resumen=resumen,
            creado_en=row["creado_en"],
        )