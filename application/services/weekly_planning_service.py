"""
Servicio de Planificación Semanal - Une plantillas, objetivos y revisiones.

Funcionalidades:
1. Aplica plantilla diaria cada mañana (6:50 AM)
2. Rastrea progreso de objetivos semanales
3. Genera revisión semanal los domingos (10:00 AM)
"""
import json
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Optional, List, Dict, Any

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from config.settings import settings
from config.logging import get_logger
from infrastructure.database.repositories.task_repo import TaskRepository, TaskType, TaskStatus
from infrastructure.database.repositories.plantilla_repo import PlantillaRepository, PlantillaDiaria
from infrastructure.database.repositories.objetivo_repo import ObjetivoRepository, ObjetivoSemanal
from infrastructure.database.repositories.revision_repo import RevisionRepository, RevisionSemanal

if TYPE_CHECKING:
    from application.services.calendar_service import CalendarService
    from application.services.ai_service import AIService

logger = get_logger(__name__)


class WeeklyPlanningService:
    """Servicio que orquesta plantillas, objetivos y revisiones semanales."""

    def __init__(
        self,
        task_repo: TaskRepository,
        plantilla_repo: PlantillaRepository,
        objetivo_repo: "ObjetivoRepository",
        revision_repo: "RevisionRepository",
        calendar_service: Optional["CalendarService"] = None,
        ai_service: Optional["AIService"] = None,
    ):
        self._task_repo = task_repo
        self._plantilla_repo = plantilla_repo
        self._objetivo_repo = objetivo_repo
        self._revision_repo = revision_repo
        self._calendar_service = calendar_service
        self._ai_service = ai_service

    # ============================================================
    # 1. PLANTILLAS DIARIAS - Aplicar cada mañana
    # ============================================================

    async def apply_daily_template(self, telefono_id: str) -> Optional[int]:
        """
        Aplica la plantilla activa creando TAREA_DIARIA de hoy.

        Returns:
            ID de la tarea diaria creada o None si no hay plantilla activa
        """
        plantilla = await self._plantilla_repo.get_active(telefono_id)
        if not plantilla or not plantilla.items:
            logger.debug("daily_template_not_found", telefono_id=telefono_id)
            return None

        # Verificar si ya existe TAREA_DIARIA para hoy
        from datetime import date
        hoy = date.today()
        inicio_hoy = datetime.combine(hoy, datetime.min.time()).replace(tzinfo=settings.tz)
        fin_hoy = inicio_hoy + timedelta(days=1)

        existing = await self._task_repo.get_tasks_by_date_range(
            telefono_id, inicio_hoy, fin_hoy, TaskStatus.PENDIENTE
        )
        for t in existing:
            if t.tipo == TaskType.TAREA_DIARIA:
                logger.info("daily_template_already_applied", telefono_id=telefono_id)
                return t.id

        # Crear subtareas desde la plantilla
        from infrastructure.database.repositories.task_repo import SubTask
        import uuid

        subtareas = []
        for i, item in enumerate(plantilla.items):
            texto = item.get("texto", "").strip()
            if texto:
                subtareas.append(SubTask(
                    id=str(uuid.uuid4())[:8],
                    texto=texto,
                    completado=False,
                    orden=i
                ))

        if not subtareas:
            return None

        # Crear TAREA_DIARIA
        task_id = await self._task_repo.save(
            telefono_id=telefono_id,
            tipo=TaskType.TAREA_DIARIA,
            detalles=plantilla.nombre,
            fecha_hora=None,
            estado="PENDIENTE",
            subtareas=subtareas,
            tags=["plantilla"],
        )

        logger.info("daily_template_applied", telefono_id=telefono_id,
                   plantilla=plantilla.nombre, task_id=task_id, items=len(subtareas))
        return task_id

    async def create_plantilla_from_text(self, telefono_id: str, texto: str, nombre: str = None) -> int:
        """
        Crea una plantilla desde texto libre.
        Ej: "estudiar 2h, ejercicio 30min, leer 30min"
        """
        import re
        items = re.split(r'[,;\n]|\s+y\s+', texto)
        items = [item.strip() for item in items if item.strip()]

        if not items:
            raise ValueError("No se encontraron items válidos")

        items_structured = [{"texto": item, "orden": i} for i, item in enumerate(items)]

        if not nombre:
            nombre = f"Plantilla {datetime.now().strftime('%d/%m')}"

        plantilla_id = await self._plantilla_repo.save(
            telefono_id=telefono_id,
            nombre=nombre,
            items=items_structured,
            activa=True,  # Por defecto la nueva se vuelve activa
        )

        logger.info("plantilla_created_from_text", telefono_id=telefono_id,
                   plantilla_id=plantilla_id, items=len(items))
        return plantilla_id

    # ============================================================
    # 2. OBJETIVOS SEMANALES - Tracking de progreso
    # ============================================================

    async def create_objetivo(
        self,
        telefono_id: str,
        descripcion: str,
        objetivo_valor: float,
        objetivo_unidad: str,
    ) -> int:
        """
        Crea un objetivo para la semana actual.

        Args:
            telefono_id: ID del usuario
            descripcion: "estudiar 10h/semana"
            objetivo_valor: 10
            objetivo_unidad: "horas"
        """
        from datetime import date, timedelta
        hoy = date.today()
        semana_inicio = date.today() - timedelta(days=date.today().weekday())  # Lunes

        objetivo_id = await self._objetivo_repo.save(
            telefono_id=telefono_id,
            descripcion=descripcion,
            objetivo_valor=objetivo_valor,
            objetivo_unidad=objetivo_unidad,
            semana_inicio=semana_inicio,
        )
        return objetivo_id

    async def get_objetivos_semana(self, telefono_id: str) -> List:
        """Obtiene objetivos de la semana actual."""
        return await self._objetivo_repo.get_active(telefono_id)

    async def update_objetivo_progress(self, objetivo_id: int, incremento: float) -> bool:
        """Incrementa progreso de un objetivo."""
        return await self._objetivo_repo.update_progress(objetivo_id, incremento)

    async def get_weekly_goals_summary(self, telefono_id: str) -> dict:
        """Resumen de objetivos para revisión semanal."""
        from datetime import date, timedelta
        hoy = date.today()
        semana_inicio = date.today() - timedelta(days=date.today().weekday())
        return await self._objetivo_repo.get_week_summary(telefono_id)

    # ============================================================
    # 3. REVISIÓN SEMANAL (Domingo) - Resumen completo
    # ============================================================

    async def generate_weekly_review(self, telefono_id: str, semana_inicio: date = None) -> Dict[str, Any]:
        """
        Genera revisión semanal completa.

        Returns:
            Dict con resumen completo para guardar y mostrar
        """
        if semana_inicio is None:
            from datetime import date, timedelta
            hoy = date.today()
            semana_inicio = date.today() - timedelta(days=date.today().weekday())

        semana_fin = semana_inicio + timedelta(days=6)
        inicio_semana = datetime.combine(semana_inicio, datetime.min.time()).replace(tzinfo=settings.tz)
        fin_semana = datetime.combine(semana_inicio + timedelta(days=7), datetime.min.time()).replace(tzinfo=settings.tz)

        # Obtener datos de la semana
        phone_id = telefono_id

        # Tareas completadas esta semana
        tareas_semana = await self._task_repo.get_tasks_by_date_range(
            telefono_id, inicio_semana, fin_semana + timedelta(days=1), None
        )
        tareas_completadas = [t for t in tareas_semana if t.estado == TaskStatus.COMPLETADO]
        tareas_pendientes = [t for t in tareas_semana if t.estado == TaskStatus.PENDIENTE]

        # Eventos de la semana (si hay calendar_service)
        eventos_semana = []
        if self._calendar_service:
            try:
                eventos = await self._calendar_service.get_upcoming_events(max_results=50, time_min=inicio_semana)
                eventos_semana = [e for e in eventos if self._event_in_week(e, semana_inicio)]
            except Exception:
                pass

        # Plantillas usadas
        from datetime import date, timedelta
        hoy = date.today()
        tareas_semana_all = await self._task_repo.get_tasks_by_date_range(
            telefono_id, inicio_semana, datetime.combine(semana_inicio + timedelta(days=7), datetime.min.time()).replace(tzinfo=settings.tz), None
        )
        plantillas_usadas = set()
        for t in tareas_semana_all:
            if t.tipo == TaskType.TAREA_DIARIA and t.tags and "plantilla" in t.tags:
                plantillas_usadas.add(t.detalles)

        # Objetivos de la semana
        objetivos_resumen = await self._objetivo_repo.get_week_summary(telefono_id)

        # Calcular estadísticas
        total_tareas = len(tareas_semana)
        completadas = len(tareas_completadas)
        pendientes = len(tareas_pendientes)
        tasa_completitud = round((completadas / total_tareas * 100) if total_tareas > 0 else 0, 1)

        resumen = {
            "semana": semana_inicio.isoformat(),
            "periodo": f"{semana_inicio.strftime('%d/%m')} - {(semana_inicio + timedelta(days=6)).strftime('%d/%m')}",
            "estadisticas": {
                "tareas_totales": total_tareas,
                "completadas": completadas,
                "pendientes": pendientes,
                "tasa_completitud": tasa_completitud,
                "eventos_asistidos": len(eventos_semana),
                "plantillas_usadas": list(plantillas_usadas),
            },
            "objetivos": objetivos_resumen.get("objetivos", []),
            "objetivos_resumen": {
                "total": objetivos_resumen.get("total", 0),
                "completados": objetivos_resumen.get("completados", 0),
                "porcentaje_promedio": objetivos_resumen.get("porcentaje_promedio", 0),
            },
            "tareas_detalle": [
                {
                    "tipo": t.tipo.value,
                    "detalles": t.detalles,
                    "estado": t.estado.value,
                    "fecha": t.fecha_hora.isoformat() if t.fecha_hora else None,
                }
                for t in tareas_semana
            ],
            "eventos": [
                {
                    "titulo": e.get("summary", "Sin título"),
                    "inicio": e["start"].get("dateTime", e["start"].get("date")),
                }
                for e in eventos_semana
            ],
        }

        # Guardar en histórico
        await self._revision_repo.save(telefono_id, date.today() - timedelta(days=date.today().weekday()), resumen)

        logger.info("weekly_review_generated", telefono_id=telefono_id,
                   semana=semana_inicio.isoformat(), tareas=total_tareas)
        return resumen

    async def send_weekly_review(self, bot: Bot, chat_id: str, semana_inicio: date = None) -> None:
        """Envía la revisión semanal formateada por Telegram."""
        if semana_inicio is None:
            from datetime import date, timedelta
            hoy = date.today()
            semana_inicio = date.today() - timedelta(days=date.today().weekday())

        resumen = await self.generate_weekly_review(telefono_id=chat_id, semana_inicio=semana_inicio)

        # Formatear mensaje
        mensaje = f"📊 <b>Revisión Semanal</b> ({resumen['periodo']})\n\n"

        # Stats
        stats = resumen["estadisticas"]
        mensaje += "📊 <b>Estadísticas:</b>\n"
        mensaje += f"  ✅ Tareas completadas: {stats['completadas']}/{stats['tareas_totales']} ({stats['tasa_completitud']}%)\n"
        mensaje += f"  ⏳ Pendientes: {stats['pendientes']}\n"
        mensaje += f"  📅 Eventos: {stats['eventos_asistidos']}\n"
        if stats['plantillas_usadas']:
            mensaje += f"  📋 Plantillas: {', '.join(stats['plantillas_usadas'])}\n"
        mensaje += "\n"

        # Objetivos
        obj_resumen = resumen["objetivos_resumen"]
        if obj_resumen["total"] > 0:
            mensaje += "🎯 <b>Objetivos semanales:</b>\n"
            mensaje += f"  ✅ Completados: {obj_resumen['completados']}/{obj_resumen['total']}\n"
            mensaje += f"  📈 Promedio: {obj_resumen['porcentaje_promedio']}%\n"
            for obj in resumen.get("objetivos", []):
                emoji = "✅" if obj["completado"] else ("🟡" if obj["porcentaje"] >= 75 else "🔴")
                mensaje += f"  {emoji} {obj['descripcion']}: {obj['progreso']} ({obj['porcentaje']}%)\n"
            mensaje += "\n"

        # Detalle tareas
        if resumen["tareas_detalle"]:
            mensaje += "📝 <b>Detalle tareas:</b>\n"
            for t in resumen["tareas_detalle"][:10]:  # Limitar a 10
                estado_emoji = "✅" if t["estado"] == "COMPLETADO" else "⏳"
                fecha_str = t["fecha"][:10] if t["fecha"] else "sin fecha"
                mensaje += f"  {estado_emoji} [{t['tipo']}] {t['detalles'][:40]} ({fecha_str})\n"
            if len(resumen["tareas_detalle"]) > 10:
                mensaje += f"  ... y {len(resumen['tareas_detalle']) - 10} más\n"
            mensaje += "\n"

        mensaje += "💪 ¡Buen trabajo esta semana!"

        await bot.send_message(
            chat_id=chat_id,
            text=mensaje,
            parse_mode=ParseMode.HTML
        )

        logger.info("weekly_review_sent", chat_id=chat_id)

    def _event_in_week(self, event: dict, semana_inicio: date) -> bool:
        """Verifica si evento está en la semana."""
        try:
            inicio = event['start'].get('dateTime', event['start'].get('date'))
            dt = datetime.fromisoformat(inicio.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=settings.tz)
            semana_fin = datetime.combine(semana_inicio + timedelta(days=7), datetime.min.time()).replace(tzinfo=settings.tz)
            inicio_semana_dt = datetime.combine(semana_inicio, datetime.min.time()).replace(tzinfo=settings.tz)
            return inicio_semana_dt <= dt < semana_fin
        except Exception:
            return False