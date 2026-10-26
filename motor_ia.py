import os
import json
import datetime
from typing import Dict, Any
from zoneinfo import ZoneInfo
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
ZONA_HORARIA = ZoneInfo("America/Argentina/Buenos_Aires")

def clasificar_intencion(texto: str) -> Dict[str, Any]:
    fecha_actual = datetime.datetime.now(ZONA_HORARIA).strftime("%Y-%m-%d %H:%M")
    prompt_sistema = f"""
    Sos Secretar-IA, secretaria personal. Hoy es {fecha_actual}. 
    Analizá el mensaje y devolvé un JSON estricto:
    {{"accion": "EVENTO" | "RECORDATORIO" | "NOTA" | "RECHAZADO_GASTOS" | "CONVERSACION" | "DESHACER" | "ELIMINAR_FECHA", "detalles": "Resumen o respuesta", "fecha_hora": "YYYY-MM-DD HH:MM si aplica, sino null"}}
    REGLA 1: Si es un turno o cita para la agenda, usa "EVENTO".
    REGLA 2: Si es una acción a una hora específica, usa "RECORDATORIO".
    REGLA 3: Si es una contraseña, idea o lista sin fecha, usa "NOTA".
    REGLA 4: Si es un saludo o charla, usa "CONVERSACION".
    REGLA 5: Si intenta registrar finanzas, usa "RECHAZADO_GASTOS".
    REGLA 6: Si el usuario pide "deshacer", "borrar el último" o dice "me equivoqué", usa "DESHACER".
    REGLA 7: Si pide borrar, vaciar o eliminar los registros de un día específico, usa "ELIMINAR_FECHA" y extraé la fecha en "fecha_hora".
    """
    try:
        respuesta = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": texto}
            ],
            model="qwen/qwen3.8-27b",
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=200
        )
        return json.loads(respuesta.choices[0].message.content)
    except Exception as e:
        print(f"Error Groq: {e}")
        return {"accion": "ERROR", "detalles": str(e), "fecha_hora": None}

def transcribir_audio(ruta_audio: str) -> str:
    with open(ruta_audio, "rb") as audio_file:
        return groq_client.audio.transcriptions.create(
            file=(ruta_audio, audio_file.read()),
            model="whisper-large-v3",
            response_format="text",
            language="es"
        )