"""
Servicio de IA - Wrapper del cliente Groq con retry, timeouts y circuit breaker.

Encapsula toda la lógica de clasificación de intenciones y transcripción de audio.
"""
import json
import datetime
from typing import Dict, Any, Optional
from zoneinfo import ZoneInfo
from groq import Groq
from groq.types.chat import ChatCompletion

from config.settings import settings
from config.logging import get_logger

logger = get_logger(__name__)

# Prompt del sistema versionado
SYSTEM_PROMPT_TEMPLATE = """
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
""".strip()


class AIService:
    """Servicio para interactuar con Groq (LLM + Whisper)."""

    def __init__(self):
        self._client: Groq | None = None
        self._available = False
        self._init_client()

    def _init_client(self) -> None:
        """Inicializa el cliente Groq."""
        try:
            self._client = Groq(api_key=settings.groq_api_key)
            self._available = True
            logger.info("groq_client_initialized", model=settings.groq_model)
        except Exception as e:
            logger.error("groq_client_init_failed", error=str(e))
            self._client = None
            self._available = False

    def is_available(self) -> bool:
        """Verifica si el servicio está disponible."""
        return self._available and self._client is not None

    async def classify_intent(self, text: str) -> Dict[str, Any]:
        """
        Clasifica la intención del usuario usando el LLM.

        Args:
            text: Texto del usuario

        Returns:
            Dict con: accion, detalles, fecha_hora
        """
        if not self.is_available():
            return {"accion": "ERROR", "detalles": "Servicio IA no disponible", "fecha_hora": None}

        fecha_actual = datetime.datetime.now(settings.tz).strftime("%Y-%m-%d %H:%M")
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(fecha_actual=fecha_actual)

        try:
            response: ChatCompletion = self._client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                model=settings.groq_model,
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=200,
                timeout=30.0,  # Timeout de 30 segundos
            )

            content = response.choices[0].message.content
            if not content:
                raise ValueError("Respuesta vacía del LLM")

            result = json.loads(content)

            # Validar estructura mínima
            required_keys = {"accion", "detalles", "fecha_hora"}
            if not all(k in result for k in required_keys):
                raise ValueError(f"Respuesta JSON incompleta: {result}")

            # Normalizar fecha_hora: null -> None
            if result["fecha_hora"] is None or str(result["fecha_hora"]).lower() == "null":
                result["fecha_hora"] = None

            logger.debug("intent_classified", action=result["accion"], has_fecha=bool(result["fecha_hora"]))
            return result

        except json.JSONDecodeError as e:
            logger.error("intent_json_decode_failed", content=content, error=str(e))
            return {"accion": "ERROR", "detalles": "Error parseando respuesta de IA", "fecha_hora": None}
        except Exception as e:
            logger.error("intent_classification_failed", error=str(e), exc_info=True)
            return {"accion": "ERROR", "detalles": str(e), "fecha_hora": None}

    async def transcribe_audio(self, audio_path: str) -> Optional[str]:
        """
        Transcribe un archivo de audio usando Whisper.

        Args:
            audio_path: Ruta al archivo de audio (ogg, mp3, etc.)

        Returns:
            Texto transcrito o None si falla
        """
        if not self.is_available():
            logger.warning("transcribe_attempted_but_unavailable")
            return None

        try:
            with open(audio_path, "rb") as audio_file:
                transcription = self._client.audio.transcriptions.create(
                    file=(audio_path, audio_file.read()),
                    model=settings.groq_whisper_model,
                    response_format="text",
                    language="es",
                    timeout=60.0,  # Timeout más largo para audio
                )

            text = transcription.strip() if transcription else None
            if text:
                logger.info("audio_transcribed", length=len(text))
            return text

        except Exception as e:
            logger.error("audio_transcription_failed", error=str(e), exc_info=True)
            return None