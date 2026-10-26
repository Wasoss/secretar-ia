"""
Repositorio de credenciales - Almacena tokens OAuth de Google Calendar.
"""
from typing import Optional
import asyncpg

from config.logging import get_logger

logger = get_logger(__name__)


class CredentialRepository:
    """Repositorio para tokens OAuth y credenciales persistentes."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def save_token(self, nombre: str, token_json: str) -> None:
        """
        Guarda o actualiza un token JSON (upsert).

        Args:
            nombre: Identificador único (ej: 'google_calendar')
            token_json: Token serializado como JSON string
        """
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO credenciales (nombre, token_json, actualizado_en)
                VALUES ($1, $2, NOW())
                ON CONFLICT (nombre) DO UPDATE SET
                    token_json = EXCLUDED.token_json,
                    actualizado_en = NOW()
            """, nombre, token_json)

        logger.info("credential_saved", nombre=nombre)

    async def get_token(self, nombre: str) -> Optional[str]:
        """
        Obtiene un token JSON por nombre.

        Returns:
            Token JSON string o None si no existe
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT token_json FROM credenciales WHERE nombre = $1",
                nombre
            )

        if row:
            logger.debug("credential_retrieved", nombre=nombre)
            return row["token_json"]

        logger.debug("credential_not_found", nombre=nombre)
        return None

    async def delete_token(self, nombre: str) -> bool:
        """
        Elimina un token.

        Returns:
            True si se eliminó, False si no existía
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM credenciales WHERE nombre = $1", nombre
            )

        deleted = result == "DELETE 1"
        if deleted:
            logger.info("credential_deleted", nombre=nombre)
        return deleted