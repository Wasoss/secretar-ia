"""
Servicio de IA - Wrapper del cliente Groq con retry, timeouts y circuit breaker.

Encapsula toda la lógica de clasificación de intenciones y transcripción de audio.
Versión mejorada con:
- Prompt enriquecido para tareas complejas de secretaría
- Soporte para recurrencia (RRULE)
- Parsing de fechas relativas
- Detección de conflictos implícitos
- Contexto de conversación
"""
import json
import datetime
import re
from typing import Dict, Any, Optional, List
from zoneinfo import ZoneInfo
from dataclasses import dataclass
from enum import Enum
from groq import Groq
from groq.types.chat import ChatCompletion

from config.settings import settings
from config.logging import get_logger

logger = get_logger(__name__)


class ActionType(str, Enum):
    """Tipos de acciones soportadas."""
    EVENTO = "EVENTO"
    RECORDATORIO = "RECORDATORIO"
    NOTA = "NOTA"
    RECHAZADO_GASTOS = "RECHAZADO_GASTOS"
    CONVERSACION = "CONVERSACION"
    DESHACER = "DESHACER"
    ELIMINAR_FECHA = "ELIMINAR_FECHA"
    REAGENDAR = "REAGENDAR"
    LISTAR = "LISTAR"
    BUSCAR = "BUSCAR"
    ERROR = "ERROR"


class RecurrenceFrequency(str, Enum):
    """Frecuencias de recurrencia soportadas."""
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"


@dataclass
class ParsedIntent:
    """Intención parseada con metadatos enriquecidos."""
    accion: ActionType
    detalles: str
    fecha_hora: Optional[datetime.datetime]
    recurrencia: Optional[str] = None  # RRULE string
    prioridad: int = 0  # 0=normal, 1=alta, -1=baja
    tags: List[str] = None
    tarea_original_id: Optional[int] = None  # Para REAGENDAR
    confianza: float = 1.0

    def __post_init__(self):
        if self.tags is None:
            self.tags = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accion": self.accion.value,
            "detalles": self.detalles,
            "fecha_hora": self.fecha_hora.isoformat() if self.fecha_hora else None,
            "recurrencia": self.recurrencia,
            "prioridad": self.prioridad,
            "tags": self.tags,
            "tarea_original_id": self.tarea_original_id,
            "confianza": self.confianza,
        }


# Prompt del sistema versionado y enriquecido
SYSTEM_PROMPT_TEMPLATE = """
Sos Secretar-IA, secretaria personal ejecutiva. Hoy es {fecha_actual} (zona horaria: America/Argentina/Buenos_Aires).

Tu rol: Gestionar agenda, recordatorios y notas de forma PROACTIVA y PRECISA. Entendés lenguaje natural complejo.

=== ACCIONES DISPONIBLES ===
1. EVENTO: Cita/turno/reunión en Calendar (con duración, 1h default). Incluye: título, fecha_hora, recurrencia opcional.
2. RECORDATORIO: Alarma para acción puntual. Incluye: qué, cuándo, recurrencia opcional.
3. NOTA: Info sin fecha (claves, ideas, listas, contactos). Solo detalles.
4. RECHAZADO_GASTOS: Finanzas → derivar a bot especializado.
5. CONVERSACION: Saludos, charla, preguntas generales. Responder naturalmente.
6. DESHACER: Borrar última carga del usuario.
7. ELIMINAR_FECHA: Borrar TODO de un día específico.
8. REAGENDAR: Cambiar fecha/hora de evento/recordatorio existente. Requiere: tarea_original_id (si se sabe), nuevo fecha_hora, detalles.
9. LISTAR: Mostrar tareas/eventos (hoy, semana, pendientes, por tag).
10. BUSCAR: Buscar en notas/eventos por palabras clave.

=== REGLAS DE ORO ===
R1: CITA/TURNO/REUNIÓN → EVENTO (va a Google Calendar)
R2: ACCIÓN A HORA ESPECÍFICA → RECORDATORIO (alarma local)
R3: INFO SIN FECHA (clave, idea, lista, contacto) → NOTA
R4: SALUDO/CHARLA/PREGUNTA → CONVERSACION
R5: FINANZAS/GASTOS → RECHAZADO_GASTOS
R6: "DESHACER"/"BORRAR ÚLTIMO"/"ME EQUIVOQUÉ" → DESHACER
R7: "BORRAR TODO DEL [DÍA]" → ELIMINAR_FECHA
R8: "CAMBIAR"/"MOVER"/"REAGENDAR"/"REEMPLAZAR" → REAGENDAR (buscar tarea original)
R9: "QUÉ TENGO"/"LISTAR"/"MOSTRAR"/"AGENDA" → LISTAR
R10: "BUSCAR"/"ENCONTRAR"/"DÓNDE PUSE" → BUSCAR

=== FECHAS RELATIVAS (siempre resolver a YYYY-MM-DD HH:MM) ===
- "hoy" → fecha actual
- "mañana" → +1 día
- "pasado mañana" → +2 días
- "próximo [lunes/martes/...]" → próximo día de semana (si hoy es ese día, +7 días)
- "este [lunes/martes/...]" → día de semana de esta semana
- "en X días/semanas/meses" → sumar
- "el [número] de [mes]" → fecha específica año actual (o siguiente si pasó)
- "fin de semana" → próximo sábado
- "entresemana" → próximo lunes si fin de semana, sino hoy

=== RECURRENCIA (RRULE) ===
Detectar patrones y generar RRULE:
- "cada día" / "diario" → FREQ=DAILY
- "cada semana" / "semanal" / "todos los lunes" → FREQ=WEEKLY;BYDAY=MO
- "cada mes" / "mensual" / "el 15 de cada mes" → FREQ=MONTHLY;BYMONTHDAY=15
- "cada año" / "anual" → FREQ=YEARLY
- "días hábiles" → FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR
- "fines de semana" → FREQ=WEEKLY;BYDAY=SA,SU
- "primer viernes del mes" → FREQ=MONTHLY;BYDAY=1FR
- "último día del mes" → FREQ=MONTHLY;BYMONTHDAY=-1

=== PRIORIDAD ===
- "urgente"/"importante"/"crítico"/"ya" → prioridad=1
- "cuando puedas"/"no apura"/"baja prioridad" → prioridad=-1
- Default → 0

=== TAGS ===
Extraer hashtags o palabras clave: #trabajo #personal #salud #familia #estudio

=== RESPUESTA JSON ESTRICTA ===
{{
  "accion": "EVENTO|RECORDATORIO|NOTA|RECHAZADO_GASTOS|CONVERSACION|DESHACER|ELIMINAR_FECHA|REAGENDAR|LISTAR|BUSCAR",
  "detalles": "Resumen claro y accionable",
  "fecha_hora": "YYYY-MM-DD HH:MM o null",
  "recurrencia": "RRULE string o null",
  "prioridad": -1|0|1,
  "tags": ["tag1", "tag2"],
  "tarea_original_id": null,
  "confianza": 0.0-1.0
}}

=== EJEMPLOS ===
Usuario: "Reunión con Juan el próximo martes a las 14hs, urgente, #trabajo"
→ {{"accion":"EVENTO","detalles":"Reunión con Juan","fecha_hora":"2025-01-14 14:00","recurrencia":null,"prioridad":1,"tags":["trabajo"],"tarea_original_id":null,"confianza":0.95}}

Usuario: "Recordame tomar agua cada hora en días hábiles"
→ {{"accion":"RECORDATORIO","detalles":"Tomar agua","fecha_hora":null,"recurrencia":"FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=9,10,11,12,13,14,15,16,17","prioridad":0,"tags":["salud"],"tarea_original_id":null,"confianza":0.9}}

Usuario: "Cambia la reunión de Juan al miércoles a las 15hs"
→ {{"accion":"REAGENDAR","detalles":"Reunión con Juan","fecha_hora":"2025-01-15 15:00","recurrencia":null,"prioridad":0,"tags":[],"tarea_original_id":null,"confianza":0.85}}

Usuario: "¿Qué tengo el viernes?"
→ {{"accion":"LISTAR","detalles":"Eventos y tareas del viernes","fecha_hora":"2025-01-17 00:00","recurrencia":null,"prioridad":0,"tags":[],"tarea_original_id":null,"confianza":0.9}}
""".strip()


class AIService:
    """Servicio para interactuar con Groq (LLM + Whisper)."""

    def __init__(self):
        self._client: Groq | None = None
        self._available = False
        self._conversation_history: List[Dict[str, str]] = []
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

    def add_context(self, user_text: str, intent: ParsedIntent) -> None:
        """Agrega interacción al historial de conversación (máx 10)."""
        self._conversation_history.append({
            "user": user_text,
            "intent": intent.to_dict()
        })
        if len(self._conversation_history) > 10:
            self._conversation_history = self._conversation_history[-10:]

    def _build_context_prompt(self) -> str:
        """Construye contexto de conversación reciente."""
        if not self._conversation_history:
            return ""
        ctx = "\n--- CONTEXTO RECIENTE ---\n"
        for h in self._conversation_history[-5:]:
            ctx += f"Usuario: {h['user']} → Acción: {h['intent']['accion']} ({h['intent']['detalles']})\n"
        return ctx + "--- FIN CONTEXTO ---\n"

    async def classify_intent(self, text: str) -> ParsedIntent:
        """
        Clasifica la intención del usuario usando el LLM con prompt enriquecido.

        Args:
            text: Texto del usuario

        Returns:
            ParsedIntent con todos los metadatos
        """
        if not self.is_available():
            return ParsedIntent(
                accion=ActionType.ERROR,
                detalles="Servicio IA no disponible",
                fecha_hora=None,
                confianza=0.0
            )

        fecha_actual = datetime.datetime.now(settings.tz).strftime("%Y-%m-%d %H:%M")
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(fecha_actual=fecha_actual)

        # Agregar contexto de conversación
        context_prompt = self._build_context_prompt()
        if context_prompt:
            system_prompt += "\n\n" + context_prompt

        try:
            response: ChatCompletion = self._client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                model=settings.groq_model,
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=300,
                timeout=30.0,
            )

            content = response.choices[0].message.content
            if not content:
                raise ValueError("Respuesta vacía del LLM")

            result = json.loads(content)

            # Validar y normalizar
            intent = self._normalize_result(result)

            # Guardar en contexto
            self.add_context(text, intent)

            logger.debug("intent_classified", action=intent.accion.value,
                        has_fecha=bool(intent.fecha_hora), recurrence=bool(intent.recurrencia))
            return intent

        except json.JSONDecodeError as e:
            logger.error("intent_json_decode_failed", content=content, error=str(e))
            return ParsedIntent(
                accion=ActionType.ERROR,
                detalles="Error parseando respuesta de IA",
                fecha_hora=None,
                confianza=0.0
            )
        except Exception as e:
            logger.error("intent_classification_failed", error=str(e), exc_info=True)
            return ParsedIntent(
                accion=ActionType.ERROR,
                detalles=str(e),
                fecha_hora=None,
                confianza=0.0
            )

    def _normalize_result(self, result: Dict[str, Any]) -> ParsedIntent:
        """Normaliza y valida el resultado del LLM."""
        # Acción
        accion_str = result.get("accion", "ERROR")
        try:
            accion = ActionType(accion_str)
        except ValueError:
            accion = ActionType.ERROR

        # Detalles
        detalles = str(result.get("detalles", "")).strip()
        if not detalles:
            detalles = "Sin detalles"

        # Fecha/hora
        fecha_hora = None
        fh = result.get("fecha_hora")
        if fh and str(fh).lower() != "null":
            try:
                # Parsear como naive y agregar timezone
                if isinstance(fh, str):
                    # Intentar varios formatos
                    for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
                        try:
                            fecha_hora = datetime.datetime.strptime(fh[:len(fmt)], fmt)
                            if fecha_hora.tzinfo is None:
                                fecha_hora = fecha_hora.replace(tzinfo=settings.tz)
                            break
                        except ValueError:
                            continue
            except Exception:
                pass

        # Recurrencia
        recurrencia = result.get("recurrencia")
        if recurrencia and str(recurrencia).lower() == "null":
            recurrencia = None

        # Prioridad
        prioridad = result.get("prioridad", 0)
        if not isinstance(prioridad, int):
            prioridad = 0
        prioridad = max(-1, min(1, prioridad))

        # Tags
        tags = result.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        tags = [str(t).strip().lower().lstrip("#") for t in tags if str(t).strip()]

        # Tarea original ID
        tarea_original_id = result.get("tarea_original_id")
        if tarea_original_id is not None:
            try:
                tarea_original_id = int(tarea_original_id)
            except (ValueError, TypeError):
                tarea_original_id = None

        # Confianza
        confianza = result.get("confianza", 1.0)
        if not isinstance(confianza, (int, float)):
            confianza = 1.0
        confianza = max(0.0, min(1.0, float(confianza)))

        return ParsedIntent(
            accion=accion,
            detalles=detalles,
            fecha_hora=fecha_hora,
            recurrencia=recurrencia,
            prioridad=prioridad,
            tags=tags,
            tarea_original_id=tarea_original_id,
            confianza=confianza
        )

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
                    timeout=60.0,
                )

            text = transcription.strip() if transcription else None
            if text:
                logger.info("audio_transcribed", length=len(text))
            return text

        except Exception as e:
            logger.error("audio_transcription_failed", error=str(e), exc_info=True)
            return None

    async def generate_proactive_suggestion(self, pending_tasks: List[Any],
                                             calendar_events: List[dict]) -> Optional[str]:
        """
        Genera sugerencia proactiva basada en estado actual.

        Ej: "Tenés reunión mañana 9am, ¿quiero recordarte prepararla 30min antes?"
        """
        if not self.is_available() or not pending_tasks and not calendar_events:
            return None

        # Construir resumen del estado
        state_summary = "Estado actual:\n"
        if calendar_events:
            state_summary += "Eventos próximos:\n"
            for ev in calendar_events[:3]:
                start = ev['start'].get('dateTime', ev['start'].get('date'))
                state_summary += f"  - {ev.get('summary', 'Sin título')}: {start}\n"
        if pending_tasks:
            state_summary += "Tareas pendientes:\n"
            for t in pending_tasks[:5]:
                state_summary += f"  - [{t.tipo.value}] {t.detalles}\n"

        prompt = f"""
{state_summary}

Como Secretar-IA, genera UNA sugerencia proactiva útil, breve y accionable.
Ejemplos:
- "Tenés reunión mañana a las 9:00. ¿Programo recordatorio para 30 min antes?"
- "Tenés 3 tareas para hoy. ¿Quieres que las ordene por prioridad?"
- "Tu evento 'Reunión equipo' es en 2hs. ¿Está todo listo?"

Respondé SOLO la sugerencia en español, sin formato JSON, máx 160 caracteres.
Si no hay nada útil, respondé "NINGUNA".
""".strip()

        try:
            response: ChatCompletion = self._client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "Sos Secretar-IA, secretaria proactiva. Generá sugerencias breves y útiles."},
                    {"role": "user", "content": prompt},
                ],
                model=settings.groq_model,
                temperature=0.3,
                max_tokens=100,
                timeout=15.0,
            )

            content = response.choices[0].message.content
            if content and content.strip() != "NINGUNA":
                logger.info("proactive_suggestion_generated", suggestion=content[:50])
                return content.strip()
            return None

        except Exception as e:
            logger.error("proactive_suggestion_failed", error=str(e))
            return None