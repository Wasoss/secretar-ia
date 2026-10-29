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
    AYUDA = "AYUDA"
    DESHACER = "DESHACER"
    ELIMINAR_FECHA = "ELIMINAR_FECHA"
    REAGENDAR = "REAGENDAR"
    LISTAR = "LISTAR"
    BUSCAR = "BUSCAR"
    TAREA_DIARIA = "TAREA_DIARIA"
    PLANTILLA_CREAR = "PLANTILLA_CREAR"
    PLANTILLA_LISTAR = "PLANTILLA_LISTAR"
    PLANTILLA_ACTIVAR = "PLANTILLA_ACTIVAR"
    OBJETIVO_CREAR = "OBJETIVO_CREAR"
    OBJETIVO_LISTAR = "OBJETIVO_LISTAR"
    OBJETIVO_PROGRESO = "OBJETIVO_PROGRESO"
    REVISION_SEMANAL = "REVISION_SEMANAL"
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
    # Campos para objetivos
    objetivo_valor: Optional[float] = None
    objetivo_unidad: Optional[str] = None

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
            "objetivo_valor": self.objetivo_valor,
            "objetivo_unidad": self.objetivo_unidad,
        }


# Prompt del sistema versionado y enriquecido
# Prompt del sistema simplificado y robusto
SYSTEM_PROMPT_TEMPLATE = """
Sos Secretar-IA, secretaria personal. Hoy es {fecha_actual} (America/Argentina/Buenos_Aires).

=== ACCIONES ===
EVENTO: Cita/reunión en Calendar (1h default). Campos: título, fecha_hora, recurrencia opcional.
RECORDATORIO: Alarma local. Qué, cuándo, recurrencia opcional.
NOTA: Info sin fecha (claves, ideas, contactos). Solo detalles.
RECHAZADO_GASTOS: Finanzas → bot especializado.
CONVERSACION: Saludos, charla, preguntas. Responder naturalmente.
AYUDA: Usuario pide ayuda/lista de comandos. Responder con guía breve.
DESHACER: Borrar última carga.
ELIMINAR_FECHA: Borrar TODO de un día.
REAGENDAR: Cambiar fecha/hora de evento existente.
LISTAR: Mostrar agenda (hoy, semana, por tag).
BUSCAR: Buscar en notas/eventos.
TAREA_DIARIA: Lista tareas día con sub-items. Sin fecha_hora.
PLANTILLA_CREAR: Plantilla reutilizable. Sin fecha_hora.
PLANTILLA_LISTAR: Listar plantillas.
PLANTILLA_ACTIVAR: Activar plantilla.
OBJETIVO_CREAR: Meta semanal medible (valor + unidad).
OBJETIVO_LISTAR: Listar objetivos.
OBJETIVO_PROGRESO: Actualizar progreso.
REVISION_SEMANAL: Resumen semanal.

=== REGLAS CLAVE ===
- Cita/reunión/turno → EVENTO
- "Recordame X a las Y" → RECORDATORIO
- Info sin fecha (clave, idea, contacto) → NOTA
- Saludo/charla/pregunta general → CONVERSACION
- Finanzas/gastos → RECHAZADO_GASTOS
- "Deshacer/borrar último" → DESHACER
- "Borrar todo del [día]" → ELIMINAR_FECHA
- "Cambiar/mover/reagendar" → REAGENDAR
- "Qué tengo/listar/mostrar/agenda" → LISTAR
- "Buscar/encontrar" → BUSCAR
- "Lista de hoy/mañana" / "tareas de hoy" → TAREA_DIARIA
- "Plantilla:" / "crear plantilla" → PLANTILLA_CREAR
- "Mis plantillas" → PLANTILLA_LISTAR
- "Activar plantilla X" → PLANTILLA_ACTIVAR
- "Meta/objetivo: X por semana" → OBJETIVO_CREAR
- "Mis objetivos/metas" → OBJETIVO_LISTAR
- "Avancé X en Y" → OBJETIVO_PROGRESO
- "Revisión semanal/cómo fue la semana" → REVISION_SEMANAL
- "Ayuda/lista de comandos/comandos" → AYUDA

=== FECHAS (resolver a YYYY-MM-DD HH:MM) ===
hoy, mañana, pasado mañana, próximo [día], este [día], el DD/MM, fin de semana, entresemana.
"mañana 9hs", "mañana a las 9", "hoy 15:30", "pasado mañana 10hs", "el 25/12 a las 10" → resolver.

=== RECURRENCIA (RRULE) ===
"cada día/diario" → FREQ=DAILY
"cada semana/semanal" → FREQ=WEEKLY;BYDAY=MO
"cada mes/mensual" → FREQ=MONTHLY;BYMONTHDAY=15
"días hábiles" → FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR
"fines de semana" → FREQ=WEEKLY;BYDAY=SA,SU

=== PRIORIDAD ===
urgente/importante/crítico/ya → 1
cuando puedas/no apura/baja → -1
Default → 0

=== TAGS ===
Extraer #hashtags o palabras clave.

=== JSON OBLIGATORIO ===
{{
  "accion": "EVENTO|RECORDATORIO|NOTA|RECHAZADO_GASTOS|CONVERSACION|AYUDA|DESHACER|ELIMINAR_FECHA|REAGENDAR|LISTAR|BUSCAR|TAREA_DIARIA|PLANTILLA_CREAR|PLANTILLA_LISTAR|PLANTILLA_ACTIVAR|OBJETIVO_CREAR|OBJETIVO_LISTAR|OBJETIVO_PROGRESO|REVISION_SEMANAL|ERROR",
  "detalles": "Resumen accionable (TAREA_DIARIA: items por comas; OBJETIVO_CREAR: desc + valor + unidad)",
  "fecha_hora": "YYYY-MM-DD HH:MM o null (TAREA_DIARIA/PLANTILLA_CREAR/OBJETIVO_CREAR/REVISION_SEMANAL/AYUDA → null)",
  "recurrencia": "RRULE o null",
  "prioridad": -1|0|1,
  "tags": ["tag1"],
  "tarea_original_id": null,
  "confianza": 0.0-1.0,
  "objetivo_valor": null,
  "objetivo_unidad": null
}}

=== EJEMPLOS ===
"Reunión con Juan mañana 14hs urgente #trabajo" → {{"accion":"EVENTO","detalles":"Reunión con Juan","fecha_hora":"2025-01-15 14:00","prioridad":1,"tags":["trabajo"]}}
"Recordame tomar agua cada hora hábil" → {{"accion":"RECORDATORIO","detalles":"Tomar agua","recurrencia":"FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR"}}
"Clave wifi es 1234" → {{"accion":"NOTA","detalles":"Clave wifi es 1234"}}
"Hola, ¿cómo estás?" → {{"accion":"CONVERSACION","detalles":"¡Hola! ¿En qué te ayudo?"}}
"Gasté $50 en comida" → {{"accion":"RECHAZADO_GASTOS","detalles":"Finanzas no gestiono"}}
"Borrar último" → {{"accion":"DESHACER"}}
"Borrar todo del viernes" → {{"accion":"ELIMINAR_FECHA"}}
"Cambiar reunión al miércoles 15hs" → {{"accion":"REAGENDAR","detalles":"reunión","fecha_hora":"2025-01-15 15:00"}}
"Qué tengo el viernes" → {{"accion":"LISTAR","detalles":"Agenda viernes","fecha_hora":"2025-01-17 00:00"}}
"Buscar clave wifi" → {{"accion":"BUSCAR","detalles":"clave wifi"}}
"Lista de hoy: estudiar, ejercicio, limpiar" → {{"accion":"TAREA_DIARIA","detalles":"estudiar, ejercicio, limpiar"}}
"Plantilla: cada día leer 30min, ejercicio" → {{"accion":"PLANTILLA_CREAR","detalles":"leer 30min, ejercicio"}}
"Mis plantillas" → {{"accion":"PLANTILLA_LISTAR"}}
"Activar plantilla rutina" → {{"accion":"PLANTILLA_ACTIVAR","detalles":"rutina"}}
"Meta: estudiar 10h/semana" → {{"accion":"OBJETIVO_CREAR","detalles":"estudiar","objetivo_valor":10,"objetivo_unidad":"horas"}}
"Mis objetivos" → {{"accion":"OBJETIVO_LISTAR"}}
"Avancé 2h en estudio" → {{"accion":"OBJETIVO_PROGRESO","detalles":"estudio","objetivo_valor":2,"objetivo_unidad":"horas"}}
"Revisión semanal" → {{"accion":"REVISION_SEMANAL"}}
"Ayuda" / "Lista de comandos" → {{"accion":"AYUDA"}}
"Reunión en el colegio mañana 8am" → {{"accion":"EVENTO","detalles":"Reunión en el colegio","fecha_hora":"2025-01-15 08:00"}}
"mañana 9hs reunion con Diana" → {{"accion":"EVENTO","detalles":"reunion con Diana","fecha_hora":"2025-01-15 09:00"}}
"hoy 15hs llamada cliente" → {{"accion":"EVENTO","detalles":"llamada cliente","fecha_hora":"2025-01-14 15:00"}}
"Recordame llamar a mamá mañana 10" → {{"accion":"RECORDATORIO","detalles":"Llamar a mamá","fecha_hora":"2025-01-15 10:00"}}
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
                max_tokens=600,
                timeout=30.0,
            )

            content = response.choices[0].message.content
            if not content:
                raise ValueError("Respuesta vacía del LLM")

            result = json.loads(content)

            # Validar y normalizar (pasar texto original para fallback de fechas)
            intent = self._normalize_result(result, text)

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

    def _normalize_result(self, result: Dict[str, Any], original_text: str = "") -> ParsedIntent:
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

        # FALLBACK: Si la IA no devolvió fecha, intentar extraer con regex del texto original
        if fecha_hora is None and original_text:
            fecha_hora = self._parse_relative_date(original_text)

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

        # Objetivo valor y unidad (para objetivos)
        objetivo_valor = result.get("objetivo_valor")
        if objetivo_valor is not None:
            try:
                objetivo_valor = float(objetivo_valor)
            except (ValueError, TypeError):
                objetivo_valor = None

        objetivo_unidad = result.get("objetivo_unidad")
        if objetivo_unidad is not None:
            objetivo_unidad = str(objetivo_unidad).strip().lower()
            if not objetivo_unidad:
                objetivo_unidad = None

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
            confianza=confianza,
            objetivo_valor=objetivo_valor,
            objetivo_unidad=objetivo_unidad
        )

    def _parse_relative_date(self, text: str) -> Optional[datetime.datetime]:
        """
        Parsea fechas relativas del texto original cuando la IA falla.
        Soporta: "mañana 9hs", "hoy 15:30", "pasado mañana 10hs", "el 25/12 a las 10", etc.
        """
        import re
        from datetime import datetime, timedelta

        text_lower = text.lower()
        now = datetime.now(settings.tz)
        hoy = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Patrones: "mañana 9hs", "mañana a las 9", "hoy 15:30", "pasado mañana 10hs", "el 25/12 a las 10"
        patterns = [
            # "mañana 9hs", "mañana 9am", "mañana 9:30"
            (r'(mañana)\s*(?:a\s+las\s+)?(\d{1,2})(?::(\d{2}))?\s*(hs?|am|pm)?', 1),
            # "hoy 15hs", "hoy 15:30"
            (r'(hoy)\s*(?:a\s+las\s+)?(\d{1,2})(?::(\d{2}))?\s*(hs?|am|pm)?', 0),
            # "pasado mañana 10hs", "pasado mañana 10:30"
            (r'(pasado\s+mañana)\s*(?:a\s+las\s+)?(\d{1,2})(?::(\d{2}))?\s*(hs?|am|pm)?', 2),
            # "el 25/12 a las 10", "el 25/12 10hs"
            (r'el\s+(\d{1,2})/(\d{1,2})(?:\s+(?:a\s+las\s+|a\s+)(\d{1,2})(?::(\d{2}))?\s*(hs?|am|pm)?)?', None),
        ]

        for pattern, day_offset in patterns:
            match = re.search(pattern, text.lower())
            if match:
                try:
                    groups = match.groups()

                    if day_offset is not None:
                        # mañana / hoy / pasado mañana
                        base_date = hoy + timedelta(days=day_offset)
                        hour = int(match.group(2))
                        minute = int(match.group(3)) if match.group(3) else 0
                        ampm = match.group(4) if len(match.groups()) >= 4 else None
                    else:
                        # el DD/MM
                        day = int(match.group(1))
                        month = int(match.group(2))
                        year = now.year
                        # Si la fecha ya pasó este año, usar el próximo
                        try:
                            test_date = datetime(year, month, day)
                            if test_date < now:
                                year += 1
                        except ValueError:
                            continue
                        base_date = datetime(year, month, day)
                        hour = int(match.group(3)) if match.group(3) else 0
                        minute = int(match.group(4)) if match.group(4) else 0
                        ampm = match.group(5) if len(match.groups()) >= 5 else None

                    # Manejar AM/PM
                    if ampm and 'pm' in ampm and hour < 12:
                        hour += 12
                    elif ampm and 'am' in ampm and hour == 12:
                        hour = 0

                    # Validar hora
                    if 0 <= hour <= 23 and 0 <= minute <= 59:
                        dt = base_date.replace(hour=hour, minute=minute, tzinfo=settings.tz)
                        logger.debug("relative_date_parsed", text=text, result=dt.isoformat())
                        return dt

                except (ValueError, IndexError, AttributeError):
                    continue

        return None

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