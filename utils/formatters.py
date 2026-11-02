"""
Utility formatters for Secretar-IA.

Extracted from main.py to avoid duplication and improve testability.
"""
import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from config.settings import settings
from application.services.ai_service import ActionType

ZONA_HORARIA = settings.tz


def formatear_fecha_arg(fecha_str: str) -> str:
    """
    Formatea fecha ISO a formato argentino (DD/MM/YYYY HH:MM).

    Args:
        fecha_str: Fecha en formato ISO string

    Returns:
        Fecha formateada o string original si falla
    """
    if not fecha_str or fecha_str.lower() == "null":
        return ""
    try:
        clean = fecha_str.replace("T", " ")[:19]
        dt = datetime.datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZONA_HORARIA)
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return fecha_str


def formatear_datetime(dt: datetime.datetime) -> str:
    """
    Formatea datetime aware a formato argentino.

    Args:
        dt: datetime timezone-aware

    Returns:
        String formateado DD/MM/YYYY HH:MM
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZONA_HORARIA)
    return dt.strftime("%d/%m/%Y %H:%M")


def _event_starts_today(event: dict, today: datetime.datetime) -> bool:
    """Verifica si un evento de Calendar empieza hoy."""
    try:
        start = event['start'].get('dateTime', event['start'].get('date'))
        dt = datetime.datetime.fromisoformat(start.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZONA_HORARIA)
        return dt.date() == today.date()
    except Exception:
        return False


def _event_in_range(event: dict, start: datetime.datetime, end: datetime.datetime) -> bool:
    """Verifica si un evento está en el rango."""
    try:
        ev_start = event['start'].get('dateTime', event['start'].get('date'))
        dt = datetime.datetime.fromisoformat(ev_start.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZONA_HORARIA)
        return start <= dt < end
    except Exception:
        return False


def build_confirmation_message(
    action: ActionType,
    details: str,
    task_id: int,
    fecha_hora: Optional[datetime.datetime] = None,
    recurrencia: Optional[str] = None,
    prioridad: int = 0,
    tags: Optional[list[str]] = None,
    calendar_event_id: Optional[str] = None,
) -> str:
    """
    Construye mensaje de confirmación bonito.

    Args:
        action: Tipo de acción
        details: Detalles de la tarea
        task_id: ID de la tarea guardada
        fecha_hora: Fecha/hora opcional
        recurrencia: RRULE string opcional
        prioridad: -1, 0, 1
        tags: Lista de tags
        calendar_event_id: ID de Calendar si se sincronizó

    Returns:
        Mensaje formateado en HTML
    """
    icons = {
        ActionType.EVENTO: "📅",
        ActionType.RECORDATORIO: "⏰",
        ActionType.NOTA: "📔",
    }
    icon = icons.get(action, "📝")

    parts = [f"{icon} Guardado como <b>{action.value}</b> (ID: {task_id})"]
    parts.append(f"📝 {details}")

    if fecha_hora:
        parts.append(f"📅 {formatear_datetime(fecha_hora)}")

    if recurrencia:
        parts.append(f"🔄 Recurrente: <code>{recurrencia}</code>")

    if prioridad == 1:
        parts.append("🔴 Prioridad: ALTA")
    elif prioridad == -1:
        parts.append("🟢 Prioridad: BAJA")

    if tags:
        parts.append(f"🏷️ Tags: #{' #'.join(tags)}")

    if calendar_event_id:
        parts.append("☁️ Sincronizado con Google Calendar")

    return "\n".join(parts)


def format_task_list(tasks: list, title: str, show_ids: bool = True) -> str:
    """
    Formatea una lista de tareas para mostrar.

    Args:
        tasks: Lista de objetos Task
        title: Título de la lista
        show_ids: Si mostrar IDs

    Returns:
        String formateado
    """
    if not tasks:
        return f"{title}\n\n(No hay elementos)"

    lines = [f"<b>{title}</b>\n"]
    for task in tasks:
        prefix = f"[{task.id}] " if show_ids else ""
        fecha_str = f" — {formatear_datetime(task.fecha_hora)}" if task.fecha_hora else ""
        tags_str = f" #{' #'.join(task.tags)}" if task.tags else ""
        prioridad_str = " 🔴" if task.prioridad == 1 else (" 🟢" if task.prioridad == -1 else "")
        lines.append(f"▷ {prefix}{task.detalles}{fecha_str}{tags_str}{prioridad_str}")

    return "\n".join(lines)


def format_daily_task(task) -> tuple[str, list]:
    """
    Formatea una tarea diaria con sub-items para mostrar con botones.

    Args:
        task: Objeto Task de tipo TAREA_DIARIA

    Returns:
        Tuple (mensaje, botones)
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    pending_subs = task.get_pending_subtasks()
    completed_subs = task.get_completed_subtasks()
    total_subs = len(task.subtareas)

    if total_subs > 0:
        progress = f" ({len(completed_subs)}/{total_subs})"
    else:
        progress = ""

    mensaje = f"☑️ <b>{task.detalles}</b>{progress}\n\n"

    botones = []
    for sub in pending_subs:
        botones.append([
            InlineKeyboardButton(
                f"☑️ {sub.texto[:35]}",
                callback_data=f"subtask_{task.id}_{sub.id}"
            )
        ])
        mensaje += f"  ☐ {sub.texto}\n"

    for sub in completed_subs:
        mensaje += f"  ~~{sub.texto}~~ ✅\n"

    return mensaje, botones


def truncate(text: str, max_len: int = 35) -> str:
    """Trunca texto a longitud máxima."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."