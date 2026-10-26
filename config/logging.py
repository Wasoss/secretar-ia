"""
Configuración de logging estructurado con structlog.

Proporciona logs en formato JSON para producción y pretty-printing para desarrollo.
"""
import sys
import logging
import structlog
from config.settings import settings


def configure_logging() -> None:
    """Configura structlog con procesadores apropiados para el entorno."""

    # Nivel de log basado en entorno (podríamos añadir ENV=production)
    log_level = logging.INFO

    # Configurar stdlib logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    # Procesadores compartidos
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if sys.stderr.isatty():
        # Desarrollo: pretty printing con colores
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        # Producción: JSON para agregación (Datadog, CloudWatch, etc.)
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Silenciar loggers ruidosos de librerías externas
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


def get_logger(name: str = None) -> structlog.stdlib.BoundLogger:
    """Obtiene un logger estructurado."""
    return structlog.get_logger(name)


# Configurar al importar
configure_logging()

# Logger por defecto para uso directo
logger = get_logger(__name__)