"""
Command handlers for Secretar-IA.
"""
from .basic import start, ajuda, status, ping, test_sistema
from .calendar import calendar_status
from .agenda import ver_notas, ver_hoy, ver_hoy_corto, ver_semana, buscar, filtrar_tag, ver_pendientes
from .templates import ver_plantillas
from .objectives import ver_objetivos, ver_revision

__all__ = [
    'start', 'ajuda', 'status', 'ping', 'test_sistema',
    'calendar_status',
    'ver_notas', 'ver_hoy', 'ver_hoy_corto', 'ver_semana', 'buscar', 'filtrar_tag', 'ver_pendientes',
    'ver_plantillas', 'ver_objetivos', 'ver_revision',
]