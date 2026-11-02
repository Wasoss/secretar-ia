"""
Maintenance job handlers for Secretar-IA.
"""
from telegram.ext import ContextTypes
from config.logging import get_logger

logger = get_logger(__name__)


async def keep_alive_db_job(context: ContextTypes.DEFAULT_TYPE):
    """Keep-alive: cada 5 min hace query simple para evitar spin-down en Render free tier."""
    from infrastructure.di.container import get_container
    container = get_container()
    pool = await container.get_pool()

    try:
        await pool.fetchval("SELECT 1")
        logger.debug("keep_alive_db_ok")
    except Exception as e:
        logger.error("keep_alive_db_failed", error=str(e))