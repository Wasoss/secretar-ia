"""
Tests for calendar command handlers - TDD approach.

Following TDD: write failing test first, then implement minimal code to pass.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from zoneinfo import ZoneInfo

from handlers.commands.calendar import CalendarCommandsHandler
from config.settings import settings


class TestCalendarCommands:
    """Tests for calendar command handlers."""

    @pytest.fixture
    def mock_update(self):
        """Mock Update object."""
        update = AsyncMock()
        update.effective_chat.id = settings.mi_telegram_id
        update.message = AsyncMock()
        update.message.reply_text = AsyncMock()
        update.message.chat_id = settings.mi_telegram_id
        return update

    @pytest.fixture
    def mock_context(self):
        """Mock Context object."""
        context = AsyncMock()
        context.bot_data = {}
        return context

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return CalendarCommandsHandler()

    @pytest.mark.asyncio
    async def test_calendar_status_with_token(self, handler):
        """Test /calendar_status when token exists and is valid."""
        # Arrange
        mock_update = AsyncMock()
        mock_update.effective_chat.id = settings.mi_telegram_id
        mock_update.message = AsyncMock()
        mock_update.message.reply_text = AsyncMock()
        mock_update.message.chat_id = settings.mi_telegram_id

        with patch('handlers.commands.calendar.get_pool') as mock_get_pool:
            mock_pool = AsyncMock()
            mock_get_pool.return_value = mock_pool

            mock_conn = AsyncMock()
            mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

            # Mock token in database
            mock_conn.fetchrow.return_value = {"token_json": '{"access_token": "test", "refresh_token": "refresh"}'}

            with patch('handlers.commands.calendar.CredentialRepository') as mock_cred_repo_class:
                mock_cred_repo = AsyncMock()
                mock_cred_repo_class.return_value = mock_cred_repo
                mock_cred_repo.get_token.return_value = '{"access_token": "test", "refresh_token": "refresh"}'

                mock_update = AsyncMock()
                mock_update.effective_chat.id = settings.mi_telegram_id
                mock_update.message = AsyncMock()
                mock_update.message.reply_text = AsyncMock()
                mock_update.message.chat_id = settings.mi_telegram_id

                handler = CalendarCommandsHandler()
                await handler.calendar_status(mock_update, AsyncMock())

    @pytest.mark.asyncio
    async def test_calendar_status_no_token(self, handler):
        """Test /calendar_status when no token in database."""
        # Arrange
        mock_update = AsyncMock()
        mock_update.effective_chat.id = settings.mi_telegram_id
        mock_update.message = AsyncMock()
        mock_update.message.reply_text = AsyncMock()
        mock_update.message.chat_id = settings.mi_telegram_id

        with patch('handlers.commands.calendar.get_pool') as mock_get_pool:
            mock_pool = AsyncMock()
            mock_get_pool.return_value = AsyncMock()

            mock_cred_repo = AsyncMock()
            mock_cred_repo.get_token.return_value = None

            with patch('handlers.commands.calendar.CredentialRepository') as mock_cred_repo_class:
                mock_cred_repo_class.return_value = mock_cred_repo

                mock_update = AsyncMock()
                mock_update.effective_chat.id = settings.mi_telegram_id
                mock_update.message = AsyncMock()
                mock_update.message.reply_text = AsyncMock()
                mock_update.message.chat_id = settings.mi_telegram_id

                from handlers.commands.calendar import CalendarCommandsHandler
                handler = CalendarCommandsHandler()
                await handler.calendar_status(AsyncMock(), AsyncMock())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])