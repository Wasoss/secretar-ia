import os
import psycopg2
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# Obtener la URL de conexión desde las variables de entorno
DATABASE_URL = os.getenv("DATABASE_URL")

def get_connection():
    return psycopg2.connect(DATABASE_URL)

def inicializar_db() -> None:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Tabla para tareas y notas
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tareas (
                    id SERIAL PRIMARY KEY,
                    telefono_id TEXT,
                    tipo TEXT,
                    detalles TEXT,
                    fecha_hora TEXT,
                    estado TEXT
                )
            """)
            # Tabla para guardar el token de Google Calendar sin que se borre
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS credenciales (
                    id SERIAL PRIMARY KEY,
                    nombre TEXT UNIQUE,
                    token_json TEXT
                )
            """)
        conn.commit()

def guardar_tarea(telefono_id: str, tipo: str, detalles: str, fecha_hora: Optional[str]) -> None:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO tareas (telefono_id, tipo, detalles, fecha_hora, estado) VALUES (%s, %s, %s, %s, %s)",
                (telefono_id, tipo, detalles, fecha_hora, "PENDIENTE")
            )
        conn.commit()

def obtener_pendientes(telefono_id: str) -> list:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, tipo, detalles, fecha_hora FROM tareas WHERE telefono_id = %s AND estado = 'PENDIENTE'", (telefono_id,))
            return cursor.fetchall()

def obtener_solo_notas(telefono_id: str) -> list:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, tipo, detalles, fecha_hora FROM tareas WHERE telefono_id = %s AND tipo = 'NOTA' AND estado = 'PENDIENTE'", (telefono_id,))
            return cursor.fetchall()

def completar_tarea(tarea_id: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE tareas SET estado = 'COMPLETADO' WHERE id = %s", (tarea_id,))
        conn.commit()

# --- FUNCIONES PARA GOOGLE CALENDAR ---
def guardar_token(token_json: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO credenciales (nombre, token_json) VALUES ('google_calendar', %s) ON CONFLICT (nombre) DO UPDATE SET token_json = EXCLUDED.token_json",
                (token_json,)
            )
        conn.commit()

def obtener_token() -> Optional[str]:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT token_json FROM credenciales WHERE nombre = 'google_calendar'")
            res = cursor.fetchone()
            return res[0] if res else None

def obtener_ultima_tarea(telefono_id: str):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, tipo, detalles FROM tareas WHERE telefono_id = %s ORDER BY id DESC LIMIT 1", (telefono_id,))
            return cursor.fetchone()

def eliminar_tarea_por_id(tarea_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM tareas WHERE id = %s", (tarea_id,))
        conn.commit()

def eliminar_por_fecha(telefono_id: str, fecha_str: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Busca todas las fechas que empiecen con YYYY-MM-DD
            cursor.execute("DELETE FROM tareas WHERE telefono_id = %s AND fecha_hora LIKE %s", (telefono_id, f"{fecha_str}%"))
            eliminados = cursor.rowcount
        conn.commit()
    return eliminados