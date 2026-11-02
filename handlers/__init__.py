"""
Handlers package for Secretar-IA.
"""
from .base import BaseHandler, handle_errors, require_auth, HandlerError, AuthenticationError, ValidationError
from .commands import (
    start, ajuda, status, ping, test_sistema,
    calendar_status,
    ver_notas, ver_hoy, ver_semana, buscar, filtrar_tag, ver_pendientes,
    ver_plantillas, ver_objetivos, ver_revision,
)
from .messages import recibir_texto, recibir_audio
from .callbacks import callback_completar
from .jobs import (
    enviar_resumen_diario, apply_daily_template_job, send_evening_reminder_job,
    send_weekly_review_job, keep_alive_db_job,
)

__all__ = [
    'BaseHandler',
    'handle_errors',
    'require_auth',
    'HandlerError',
    'AuthenticationError',
    'ValidationError',
    'start',
    'ajuda',
    'status',
    'ping',
    'test_sistema',
    'calendar_status',
    'ver_notas',
    'ver_hoy',
    'ver_semana',
    'buscar',
    'filtrar_tag',
    'ver_pendientes',
    'ver_plantillas',
    'ver_objetivos',
    'ver_revision',
    'recibir_texto',
    'recibir_audio',
    'callback_completar',
    'enviar_resumen_diario',
    'apply_daily_template_job',
    'send_evening_reminder_job',
    'send_weekly_review_job',
    'keep_alive_db_job',
]