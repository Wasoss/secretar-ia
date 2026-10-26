#!/usr/bin/env python
"""Script de migración de base de datos para Secretar-IA."""
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

        # 1. Agregar columna actualizado_en a credenciales
        print("\n📝 Agregando columna 'actualizado_en' a tabla 'credenciales'...")
        await conn.execute("""
            ALTER TABLE credenciales
            ADD COLUMN IF NOT EXISTS actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
        """)
        print("✅ Columna 'actualizado_en' agregada")

        # 2. Agregar columnas created_at/updated_at a tareas si no existen
        print("\n📝 Verificando columnas de 'tareas'...")
        await conn.execute("""
            ALTER TABLE tareas
            ADD COLUMN IF NOT EXISTS creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
        """)
        await conn.execute("""
            ALTER TABLE tareas
            ADD COLUMN IF NOT EXISTS actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
        """)
        print("✅ Columnas 'creado_en' y 'actualizado_en' verificadas en 'tareas'")

        # 3. Crear índices si no existen
        print("\n📝 Creando índices...")
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tareas_telefono_estado
            ON tareas (telefono_id, estado)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tareas_fecha_hora
            ON tareas (fecha_hora)
        """)
        print("✅ Índices creados")

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