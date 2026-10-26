#!/usr/bin/env python
"""Script de migración de base de datos para Secretar-IA.
Versión actualizada para el nuevo schema con recurrencia, prioridad, tags, calendar_event_id.
"""
import asyncio
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()


async def migrate():
    """Ejecuta migraciones pendientes."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ DATABASE_URL no configurada")
        return

    conn = await asyncpg.connect(database_url)
    try:
        print("🔗 Conectado a la base de datos")

        # 1. Agregar columnas nuevas a 'tareas' si no existen
        columns = [
            ("recurrencia", "TEXT"),
            ("prioridad", "INTEGER NOT NULL DEFAULT 0"),
            ("tags", "TEXT[] NOT NULL DEFAULT '{}'"),
            ("calendar_event_id", "TEXT"),
        ]

        print("\n📝 Verificando columnas de 'tareas'...")
        for col_name, col_type in columns:
            try:
                await conn.execute(f"""
                    ALTER TABLE tareas
                    ADD COLUMN IF NOT EXISTS {col_name} {col_type}
                """)
                print(f"✅ Columna '{col_name}' verificada/agregada")
            except Exception as e:
                print(f"⚠️  Columna '{col_name}': {e}")

        # 2. Agregar columna actualizado_en a credenciales si no existe
        print("\n📝 Verificando columnas de 'credenciales'...")
        try:
            await conn.execute("""
                ALTER TABLE credenciales
                ADD COLUMN IF NOT EXISTS actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
            """)
            print("✅ Columna 'actualizado_en' verificada en 'credenciales'")
        except Exception as e:
            print(f"⚠️  credenciales.actualizado_en: {e}")

        # 3. Crear índices si no existen
        print("\n📝 Creando índices...")
        indexes = [
            ("idx_tareas_telefono_estado", """
                CREATE INDEX IF NOT EXISTS idx_tareas_telefono_estado
                ON tareas (telefono_id, estado)
            """),
            ("idx_tareas_fecha_hora", """
                CREATE INDEX IF NOT EXISTS idx_tareas_fecha_hora
                ON tareas (fecha_hora)
            """),
            ("idx_tareas_tags", """
                CREATE INDEX IF NOT EXISTS idx_tareas_tags
                ON tareas USING GIN (tags)
            """),
            ("idx_tareas_calendar_event", """
                CREATE INDEX IF NOT EXISTS idx_tareas_calendar_event
                ON tareas (calendar_event_id)
            """),
            ("idx_tareas_recurrencia", """
                CREATE INDEX IF NOT EXISTS idx_tareas_recurrencia
                ON tareas (recurrencia) WHERE recurrencia IS NOT NULL
            """),
        ]

        for idx_name, idx_sql in indexes:
            try:
                await conn.execute(idx_sql)
                print(f"✅ Índice '{idx_name}' creado")
            except Exception as e:
                print(f"⚠️  Índice '{idx_name}': {e}")

        # 4. Verificar schema final
        print("\n📋 Schema final:")
        for table in ["credenciales", "tareas"]:
            cols = await conn.fetch(f"""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = '{table}'
                ORDER BY ordinal_position
            """)
            print(f"\n  Tabla: {table}")
            for c in cols:
                print(f"    - {c['column_name']}: {c['data_type']} (nullable={c['is_nullable']}, default={c['column_default']})")

        print("\n🎉 Migración completada exitosamente!")

    except Exception as e:
        print(f"❌ Error en migración: {e}")
        raise
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(migrate())