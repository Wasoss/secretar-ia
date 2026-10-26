"""
Repositorio de objetivos semanales - Capa de acceso a datos.

Encapsula queries para objetivos semanales con tracking de progreso.
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, List
from enum import Enum
import asyncpg

from config.logging import get_logger

logger = get_logger(__name__)


class ObjetivoUnidad(str, Enum):
    """Unidades de medida para objetivos."""
    HORAS = "horas"
    VECES = "veces"
    LIBROS = "libros"
    KM = "km"
    PAGINAS = "paginas"
    MINUTOS = "minutos"
    PERSONALIZADA = "personalizada"


@dataclass(slots=True)
class ObjetivoSemanal:
    """Entidad de dominio para un objetivo semanal."""
    id: int
    telefono_id: str
    descripcion: str  # "estudiar 10h/semana"
    objetivo_valor: float  # 10
    objetivo_unidad: str  # "horas"
    semana_inicio: date  # Lunes de la semana
    valor_actual: float
    creado_en: datetime
    actualizado_en: datetime

    @property
    def porcentaje(self) -> float:
        """Porcentaje de avance (0-100, puede pasar 100)."""
        if self.objetivo_valor == 0:
            return 0.0
        return min(100.0, (self.valor_actual / self.objetivo_valor) * 100)

    @property
    def completado(self) -> bool:
        """Si alcanzó o superó el objetivo."""
        return self.valor_actual >= self.objetivo_valor

    @property
    def restante(self) -> float:
        """Cuánto falta para completar."""
        return max(0, self.objetivo_valor - self.valor_actual)

    def formatear_progreso(self) -> str:
        """Formatea el progreso para mostrar al usuario."""
        if self.objetivo_unidad == "horas":
            return f"{self.valor_actual:.1f}h / {self.objetivo_valor:.1f}h"
        elif self.objetivo_unidad == "veces":
            return f"{int(self.valor_actual)} / {int(self.objetivo_valor)}"
        else:
            return f"{self.valor_actual} / {self.objetivo_valor} {self.objetivo_unidad}"

    def estado_emoji(self) -> str:
        """Emoji según estado."""
        if self.completado:
            return "✅"
        elif self.porcentaje >= 75:
            return "🟡"
        elif self.porcentaje >= 50:
            return "🟠"
        else:
            return "🔴"


class ObjetivoRepository:
    """Repositorio para objetivos semanales."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    def _parse_unidad(self, unidad_str: str) -> str:
        """Normaliza la unidad a formato estándar."""
        unidad_lower = unidad_str.lower().strip()
        # Mapear variaciones comunes
        if unidad_lower in ["h", "hr", "hrs", "hora", "horas", "hour", "hours"]:
            return "horas"
        elif unidad_lower in ["v", "vez", "veces", "time", "times"]:
            return "veces"
        elif unidad_lower in ["l", "libro", "libros", "book", "books"]:
            return "libros"
        elif unidad_lower in ["km", "kilometro", "kilometros", "kilometer", "kilometers"]:
            return "km"
        elif unidad_lower in ["pag", "pags", "pagina", "paginas", "page", "pages"]:
            return "paginas"
        elif unidad_lower in ["min", "mins", "minuto", "minutos", "minute", "minutes"]:
            return "minutos"
        return "personalizada"

    async def save(
        self,
        telefono_id: str,
        descripcion: str,
        objetivo_valor: float,
        objetivo_unidad: str,
        semana_inicio: Optional[date] = None,
    ) -> int:
        """
        Guarda un nuevo objetivo semanal.

        Args:
            telefono_id: ID del usuario
            descripcion: Descripción legible (ej: "estudiar 10h/semana")
            objetivo_valor: Valor numérico objetivo (ej: 10)
            objetivo_unidad: Unidad (horas, veces, libros, km, etc.)
            semana_inicio: Lunes de la semana (default: lunes actual)

        Returns:
            ID del objetivo creado
        """
        if semana_inicio is None:
            from datetime import date, timedelta
            hoy = date.today()
            semana_inicio = hoy - timedelta(days=hoy.weekday())  # Lunes de esta semana

        unidad_normalizada = self._parse_unidad(objetivo_unidad)

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO objetivos_semanales (
                    telefono_id, descripcion, objetivo_valor, objetivo_unidad,
                    semana_inicio, valor_actual
                )
                VALUES ($1, $2, $3, $4, $5, 0)
                ON CONFLICT (telefono_id, semana_inicio, descripcion) DO UPDATE SET
                    objetivo_valor = EXCLUDED.objetivo_valor,
                    objetivo_unidad = EXCLUDED.objetivo_unidad,
                    actualizado_en = NOW()
                RETURNING id
            """, telefono_id, descripcion, objetivo_valor, objetivo_unidad, semana_inicio)

        objetivo_id = row["id"]
        logger.info("objetivo_saved", objetivo_id=objetivo_id, descripcion=descripcion,
                   objetivo_valor=objetivo_valor, objetivo_unidad=objetivo_unidad)
        return objetivo_id

    async def get_by_week(self, telefono_id: str, semana_inicio: Optional[date] = None) -> List:
        """Obtiene todos los objetivos de una semana."""
        if semana_inicio is None:
            from datetime import date, timedelta
            hoy = date.today()
            semana_inicio = date.today() - timedelta(days=date.today().weekday())

        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, telefono_id, descripcion, objetivo_valor, objetivo_unidad,
                       semana_inicio, valor_actual, creado_en, actualizado_en
                FROM objetivos_semanales
                WHERE telefono_id = $1 AND semana_inicio = $2
                ORDER BY creado_en
            """, telefono_id, semana_inicio)

        return [self._row_to_objetivo(row) for row in rows]

    async def get_active(self, telefono_id: str) -> List:
        """Obtiene objetivos de la semana actual."""
        from datetime import date, timedelta
        hoy = date.today()
        semana_inicio = hoy - timedelta(days=hoy.weekday())
        return await self.get_by_week(telefono_id, semana_inicio)

    async def get_by_id(self, objetivo_id: int) -> Optional:
        """Obtiene un objetivo por ID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, telefono_id, descripcion, objetivo_valor, objetivo_unidad,
                       semana_inicio, valor_actual, creado_en, actualizado_en
                FROM objetivos_semanales
                WHERE id = $1
            """, objetivo_id)

        return self._row_to_objetivo(row) if row else None

    async def update_progress(self, objetivo_id: int, incremento: float) -> bool:
        """
        Incrementa el valor actual del objetivo.

        Args:
            objetivo_id: ID del objetivo
            incremento: Valor a sumar (ej: 1.5 horas)

        Returns:
            True si se actualizó
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE objetivos_semanales
                SET valor_actual = valor_actual + $1, actualizado_en = NOW()
                WHERE id = $2
            """, incremento, objetivo_id)

        updated = result == "UPDATE 1"
        if updated:
            logger.info("objetivo_progress_updated", objetivo_id=objetivo_id, incremento=incremento)
        return updated

    async def set_progress(self, objetivo_id: int, valor: float) -> bool:
        """Establece el valor actual exacto."""
        async with self._pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE objetivos_semanales
                SET valor_actual = $1, actualizado_en = NOW()
                WHERE id = $2
            """, valor, objetivo_id)

        updated = result == "UPDATE 1"
        if updated:
            logger.info("objetivo_progress_set", objetivo_id=objetivo_id, valor=valor)
        return updated

    async def delete(self, objetivo_id: int) -> bool:
        """Elimina un objetivo."""
        async with self._pool.acquire() as conn:
            result = await conn.execute("DELETE FROM objetivos_semanales WHERE id = $1", objetivo_id)

        deleted = result == "DELETE 1"
        if deleted:
            logger.info("objetivo_deleted", objetivo_id=objetivo_id)
        return deleted

    async def get_week_summary(self, telefono_id: str, semana_inicio: Optional[date] = None) -> dict:
        """
        Obtiene resumen de objetivos de la semana para revisión.

        Returns:
            Dict con: total_objetivos, completados, en_progreso, pendientes, porcentaje_promedio
        """
        objetivos = await self.get_by_week(telefono_id, semana_inicio)

        total = len(objetivos)
        completados = sum(1 for o in objetivos if o.completado)
        en_progreso = sum(1 for o in objetivos if not o.completado and o.valor_actual > 0)
        pendientes = sum(1 for o in objetivos if o.valor_actual == 0)

        porcentaje_promedio = sum(o.porcentaje for o in objetivos) / total if total > 0 else 0

        return {
            "total": total,
            "completados": completados,
            "en_progreso": en_progreso,
            "pendientes": pendientes,
            "porcentaje_promedio": round(porcentaje_promedio, 1),
            "objetivos": [
                {
                    "descripcion": o.descripcion,
                    "progreso": o.formatear_progreso(),
                    "porcentaje": o.porcentaje,
                    "completado": o.completado,
                    "emoji": o.estado_emoji(),
                }
                for o in objetivos
            ]
        }

    def _row_to_objetivo(self, row: asyncpg.Record):
        """Convierte un record a entidad ObjetivoSemanal."""
        return ObjetivoSemanal(
            id=row["id"],
            telefono_id=row["telefono_id"],
            descripcion=row["descripcion"],
            objetivo_valor=float(row["objetivo_valor"]),
            objetivo_unidad=row["objetivo_unidad"],
            semana_inicio=row["semana_inicio"],
            valor_actual=float(row["valor_actual"]),
            creado_en=row["creado_en"],
            actualizado_en=row["actualizado_en"],
        )