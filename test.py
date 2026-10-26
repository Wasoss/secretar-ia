import sqlite3
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

# Estas importaciones se habilitarán en la Fase 3
# from main import app, procesar_mensaje_groq

@pytest.fixture
def db_en_memoria():
    """Crea una base de datos SQLite en memoria aislada para las pruebas."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE tareas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telefono_id TEXT,
            tipo TEXT,
            detalles TEXT,
            fecha_hora DATETIME,
            estado TEXT
        )
    """)
    conn.commit()
    yield conn
    conn.close()

def test_guardar_tarea_sql(db_en_memoria):
    """Verifica la inserción segura en SQLite mediante consultas parametrizadas."""
    cursor = db_en_memoria.cursor()
    telefono_id = "5491123456789"
    tipo = "RECORDATORIO"
    detalles = "Enviar reporte de gastos"
    fecha_hora = "2026-11-01 10:00:00"
    estado = "PENDIENTE"
    
    cursor.execute(
        "INSERT INTO tareas (telefono_id, tipo, detalles, fecha_hora, estado) VALUES (?, ?, ?, ?, ?)",
        (telefono_id, tipo, detalles, fecha_hora, estado)
    )
    db_en_memoria.commit()
    
    cursor.execute("SELECT * FROM tareas WHERE telefono_id = ?", (telefono_id,))
    resultado = cursor.fetchone()
    
    assert resultado is not None
    assert resultado[2] == "RECORDATORIO"
    assert resultado[3] == "Enviar reporte de gastos"

# --- Tests de FastAPI (Comentados hasta implementar main.py) ---
# client = TestClient(app)

# def test_verificacion_webhook_whatsapp():
#     """Simula la validación inicial que exige Meta al configurar el Webhook."""
#     token_prueba = "MI_TOKEN_SECRETO"
#     response = client.get(f"/webhook?hub.verify_token={token_prueba}&hub.challenge=1158201444")
#     assert response.status_code == 200
#     assert response.text == "1158201444"