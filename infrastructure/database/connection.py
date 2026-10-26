"""
Pool de conexiones asíncrono a PostgreSQL usando asyncpg.

Proporciona conexión pooling eficiente para uso en handlers async.
"""
import asyncpg
from config.settings import settings
from config.logging import get_logger

logger = get_logger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """
    Obtiene el pool de conexiones (singleton lazy initialization).

    Returns:
        asyncpg.Pool: Pool de conexiones configurado

    Raises:
        RuntimeError: Si no se puede crear el pool
    """
    global _pool
    if _pool is None:
        try:
            _pool = await asyncpg.create_pool(
                dsn=str(settings.database_url),
                min_size=2,
                max_size=10,
                command_timeout=30,
                # Configuraciones recomendadas para Neon/serverless
                statement_cache_size=0,  # Neon no soporta prepared statements bien
            )
            logger.info("database_pool_created", min_size=2, max_size=10)
        except Exception as e:
            logger.error("database_pool_creation_failed", error=str(e))
            raise RuntimeError(f"No se pudo crear pool de base de datos: {e}") from e
    return _pool


async def close_pool() -> None:
    """Cierra el pool de conexiones gracefulmente."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("database_pool_closed")


async def init_db() -> None:
    """
    Inicializa las tablas necesarias (idempotente).

    Se ejecuta al startup de la aplicación.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Tabla de tareas y notas
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tareas (
                id SERIAL PRIMARY KEY,
                telefono_id TEXT NOT NULL,
                tipo TEXT NOT NULL,
                detalles TEXT NOT NULL,
                fecha_hora TIMESTAMPTZ,
                estado TEXT NOT NULL DEFAULT 'PENDIENTE',
                creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        # Índices para queries frecuentes
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tareas_telefono_estado
            ON tareas (telefono_id, estado)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tareas_fecha_hora
            ON tareas (fecha_hora)
        """)

        # Tabla de credenciales (tokens OAuth, etc.)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS credenciales (
                id SERIAL PRIMARY KEY,
                nombre TEXT UNIQUE NOT NULL,
                token_json TEXT NOT NULL,
                actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

    logger.info("database_initialized", tables=["tareas", "credenciales"])