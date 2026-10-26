"""
Pool de conexiones asíncrono a PostgreSQL usando asyncpg.

Proporciona conexión pooling eficiente para uso en handlers async.
Versión mejorada con migración automática de schema.
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
    Inicializa las tablas necesarias (idempotente) y ejecuta migraciones.

    Se ejecuta al startup de la aplicación.
    Orden correcto:
    1. Ejecutar migraciones primero (agregar columnas a tablas existentes)
    2. Crear tablas si no existen (con todas las columnas)
    3. Crear índices
    """
    pool = await get_pool()

    # 1. PRIMERO: Ejecutar migraciones para agregar columnas faltantes en tablas existentes
    await _run_migrations(pool)

    # 2. LUEGO: Crear tablas e índices (idempotente)
    async with pool.acquire() as conn:
        # Tabla de tareas y notas - CON TODOS LOS CAMPOS NUEVOS
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tareas (
                id SERIAL PRIMARY KEY,
                telefono_id TEXT NOT NULL,
                tipo TEXT NOT NULL,
                detalles TEXT NOT NULL,
                fecha_hora TIMESTAMPTZ,
                estado TEXT NOT NULL DEFAULT 'PENDIENTE',
                creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                -- Nuevos campos
                recurrencia TEXT,
                prioridad INTEGER NOT NULL DEFAULT 0,
                tags TEXT[] NOT NULL DEFAULT '{}',
                calendar_event_id TEXT,
                subtareas JSONB
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
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tareas_tags
            ON tareas USING GIN (tags)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tareas_calendar_event
            ON tareas (calendar_event_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tareas_recurrencia
            ON tareas (recurrencia) WHERE recurrencia IS NOT NULL
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


async def _run_migrations(pool: asyncpg.Pool) -> None:
    """Ejecuta migraciones idempotentes para agregar columnas nuevas."""
    async with pool.acquire() as conn:
        # Verificar y agregar columnas a 'tareas' si no existen
        columns_to_add = [
            ("recurrencia", "TEXT"),
            ("prioridad", "INTEGER NOT NULL DEFAULT 0"),
            ("tags", "TEXT[] NOT NULL DEFAULT '{}'"),
            ("calendar_event_id", "TEXT"),
            ("subtareas", "JSONB"),
        ]

        for col_name, col_type in columns_to_add:
            try:
                await conn.execute(f"""
                    ALTER TABLE tareas
                    ADD COLUMN IF NOT EXISTS {col_name} {col_type}
                """)
                logger.debug("migration_column_added", column=col_name)
            except Exception as e:
                logger.warning("migration_column_failed", column=col_name, error=str(e))

        # Verificar y agregar columnas a 'credenciales' si no existen
        try:
            await conn.execute("""
                ALTER TABLE credenciales
                ADD COLUMN IF NOT EXISTS actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
            """)
        except Exception as e:
            logger.warning("migration_credenciales_failed", error=str(e))

        # Re-crear índices si no existen (idempotente) - estos se crean también en init_db
        indexes = [
            ("idx_tareas_tags", "CREATE INDEX IF NOT EXISTS idx_tareas_tags ON tareas USING GIN (tags)"),
            ("idx_tareas_calendar_event", "CREATE INDEX IF NOT EXISTS idx_tareas_calendar_event ON tareas (calendar_event_id)"),
            ("idx_tareas_recurrencia", "CREATE INDEX IF NOT EXISTS idx_tareas_recurrencia ON tareas (recurrencia) WHERE recurrencia IS NOT NULL"),
        ]

        for idx_name, idx_sql in indexes:
            try:
                await conn.execute(idx_sql)
                logger.debug("migration_index_created", index=idx_name)
            except Exception as e:
                logger.warning("migration_index_failed", index=idx_name, error=str(e))