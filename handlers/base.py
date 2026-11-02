"""
Base handler classes with common functionality.

Provides error handling, authentication, and access to DI container.
"""
import logging
from functools import wraps
from typing import Callable, Awaitable, Any

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config.settings import settings
from config.logging import get_logger
from infrastructure.di.container import get_container

logger = get_logger(__name__)


class HandlerError(Exception):
    """Base exception for handler errors with user-friendly message."""

    def __init__(self, user_message: str, log_message: str = None):
        self.user_message = user_message
        self.log_message = log_message or user_message
        super().__init__(log_message)


class AuthenticationError(HandlerError):
    """Raised when user is not authorized."""

    def __init__(self):
        super().__init__(
            user_message="⛔ Acceso denegado. No estás autorizado para usar este bot.",
            log_message="unauthorized_access_attempt"
        )


class ValidationError(HandlerError):
    """Raised when input validation fails."""

    def __init__(self, message: str):
        super().__init__(
            user_message=f"⚠️ {message}",
            log_message=f"validation_error: {message}"
        )


def verify_user(update: Update) -> bool:
    """
    Verify that the user is authorized.

    Returns:
        True if authorized, False otherwise (and sends denial message)
    """
    chat_id = str(update.effective_chat.id)
    if chat_id != settings.mi_telegram_id:
        logger.warning("access_denied", chat_id=chat_id)
        return False
    return True


async def require_auth(update: Update) -> bool:
    """
    Require authentication, send denial message if not authorized.

    Usage:
        if not await require_auth(update):
            return
    """
    if not verify_user(update):
        if update.message:
            await update.message.reply_text("⛔ Acceso denegado. No estás autorizado para usar este bot.")
        return False
    return True


def handle_errors(handler: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """
    Decorator to handle errors consistently across handlers.

    Catches HandlerError and logs/sends user message.
    Catches unexpected errors and logs/sends generic message.
    """
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        try:
            return await handler(update, context, *args, **kwargs)
        except HandlerError as e:
            logger.warning(e.log_message)
            if update.message:
                await update.message.reply_text(e.user_message, parse_mode=ParseMode.HTML)
            elif update.callback_query:
                await update.callback_query.answer(e.user_message, show_alert=True)
        except Exception as e:
            logger.error("handler_failed", error=str(e), exc_info=True)
            if update.message:
                await update.message.reply_text("❌ Error interno. Probá /test", parse_mode=ParseMode.HTML)
            elif update.callback_query:
                await update.callback_query.answer("❌ Error interno", show_alert=True)
    return wrapper


class BaseHandler:
    """Base class for all handlers with common utilities."""

    def __init__(self):
        self._container = get_container()

    @property
    def container(self):
        return self._container

    async def get_services(self) -> dict:
        """Get all services from container."""
        return await self._container.get_all_services()

    async def auth_required(self, update: Update) -> bool:
        """Check auth and return boolean."""
        return await require_auth(update)

    def get_chat_id(self, update: Update) -> str:
        """Get chat_id from update."""
        return str(update.effective_chat.id)

    async def send_html(self, update: Update, text: str, **kwargs) -> None:
        """Send HTML message."""
        if update.message:
            await update.message.reply_text(text, parse_mode=ParseMode.HTML, **kwargs)
        elif update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, **kwargs)

    async def send_markdown(self, update: Update, text: str, **kwargs) -> None:
        """Send Markdown message."""
        if update.message:
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, **kwargs)
        elif update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, **kwargs)