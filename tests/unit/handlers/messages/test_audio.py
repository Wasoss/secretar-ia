"""
Tests for AudioMessageHandler - TDD approach.

Tests for the audio message handler that processes voice notes and audio files,
transcribes them using Whisper, and delegates to the text handler.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from zoneinfo import ZoneInfo

from handlers.messages.audio import AudioMessageHandler
from handlers.base import BaseHandler
from config.settings import settings
from config.logging import get_logger
from telegram import Update
from telegram.ext import ContextTypes


class TestAudioMessageHandler:
    """Tests for AudioMessageHandler."""

    @pytest.fixture
    def mock_update(self):
        """Mock Update object with proper effective_chat.id mocking."""
        from unittest.mock import MagicMock
        update = AsyncMock()
        update.effective_chat = MagicMock()
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
        context.job_queue = AsyncMock()
        context.job_queue.run_once = AsyncMock()
        return context

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from handlers.messages.audio import AudioMessageHandler
        return AudioMessageHandler()

    @pytest.fixture
    def mock_update(self):
        """Mock Update object with proper effective_chat.id mocking."""
        from unittest.mock import MagicMock
        update = AsyncMock()
        update.effective_chat = MagicMock()
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
        context.job_queue = AsyncMock()
        return context

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from handlers.messages.audio import AudioMessageHandler
        return AudioMessageHandler()

    # --- Tests for recibir_audio ---

    @pytest.mark.asyncio
    async def test_recibir_audio_returns_early_if_not_authenticated(self, handler, mock_update, mock_context):
        """Test that recibir_audio returns early if not authenticated."""
        with patch.object(handler, 'require_auth', new_callable=AsyncMock, return_value=False):
            await handler.recibir_audio(mock_update, mock_context)
            mock_update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_recibir_audio_handles_voice_message(self, handler, mock_update, mock_context):
        """Test handling of voice messages (voice notes)."""
        # Arrange
        mock_update.message.voice = AsyncMock()
        mock_update.message.voice.get_file = AsyncMock()

        mock_file = AsyncMock()
        mock_file.download_to_drive = AsyncMock()
        mock_update.message.voice.get_file.return_value = mock_file

        services = {
            'ai_service': AsyncMock(),
        }
        handler.get_services = AsyncMock(return_value=services)

        # Mock the text handler to avoid circular dependency issues
        mock_text_handler = AsyncMock()
        handler._get_text_handler = MagicMock(return_value=AsyncMock())
        handler._get_text_handler.return_value.procesar_peticion = AsyncMock()

        mock_ai = AsyncMock()
        mock_ai.transcribe_audio = AsyncMock(return_value="Transcribed text")

        services['ai_service'] = AsyncMock()
        services['ai_service'].transcribe_audio = AsyncMock(return_value="Transcribed text")

        handler.get_services = AsyncMock(return_value=services)

        # Mock tempfile
        with patch('tempfile.NamedTemporaryFile') as mock_temp:
            mock_temp_file = MagicMock()
            mock_temp_file.name = "/tmp/test.ogg"
            mock_temp.return_value.__enter__.return_value = mock_temp_file

            await handler.recibir_audio(mock_update, mock_context)

            # Verify transcription was called
            services['ai_service'].transcribe_audio.assert_called_once()

    @pytest.mark.asyncio
    async def test_recibir_audio_handles_audio_message(self, handler, mock_update, mock_context):
        """Test handling of audio messages (📎 audio)."""
        # Arrange
        mock_update.message.audio = AsyncMock()
        mock_update.message.audio.get_file = AsyncMock()

        mock_file = AsyncMock()
        mock_file.download_to_drive = AsyncMock()
        mock_update.message.audio.get_file.return_value = mock_file

        services = {'ai_service': AsyncMock()}
        handler.get_services = AsyncMock(return_value={'ai_service': AsyncMock()})
        services['ai_service'].transcribe_audio = AsyncMock(return_value="Transcribed text")

        handler.get_services = AsyncMock(return_value=services)

        with patch('tempfile.NamedTemporaryFile') as mock_temp:
            mock_temp_file = MagicMock()
            mock_temp_file.name = "/tmp/test.ogg"
            mock_temp.return_value.__enter__.return_value = mock_temp_file

            await handler.recibir_audio(mock_update, mock_context)

            services['ai_service'].transcribe_audio.assert_called_once()

    @pytest.mark.asyncio
    async def test_recibir_audio_handles_document_audio(self, handler, mock_update, mock_context):
        """Test handling of document audio files."""
        # Arrange
        mock_update.message.document = AsyncMock()
        mock_update.message.document.mime_type = "audio/ogg"
        mock_update.message.document.get_file = AsyncMock()

        mock_file = AsyncMock()
        mock_file.download_to_drive = AsyncMock()
        mock_update.message.document.get_file.return_value = mock_file

        services = {'ai_service': AsyncMock()}
        handler.get_services = AsyncMock(return_value={'ai_service': AsyncMock()})
        services['ai_service'].transcribe_audio = AsyncMock(return_value="Transcribed text")

        with patch('tempfile.NamedTemporaryFile') as mock_temp:
            mock_temp_file = MagicMock()
            mock_temp_file.name = "/tmp/test.ogg"
            mock_temp.return_value.__enter__.return_value = mock_temp_file

            await handler.recibir_audio(mock_update, mock_context)

            services['ai_service'].transcribe_audio.assert_called_once()

    @pytest.mark.asyncio
    async def test_recibir_audio_rejects_non_audio_document(self, handler, mock_update, mock_context):
        """Test that non-audio documents are rejected."""
        mock_update.message.document = AsyncMock()
        mock_update.message.document.mime_type = "application/pdf"
        mock_update.message.document.get_file = AsyncMock()

        await handler.recibir_audio(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "No detecté audio" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_recibir_audio_handles_transcription_failure(self, handler, mock_update, mock_context):
        """Test handling of transcription failure."""
        mock_update.message.voice = AsyncMock()
        mock_update.message.voice.get_file = AsyncMock()

        services = {'ai_service': AsyncMock()}
        handler.get_services = AsyncMock(return_value=services)
        services['ai_service'].transcribe_audio = AsyncMock(return_value=None)

        await handler.recibir_audio(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "No pude transcribir el audio" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_recibir_audio_handles_transcription_exception(self, handler, mock_update, mock_context):
        """Test handling of transcription exceptions."""
        mock_update.message.voice = AsyncMock()
        mock_update.message.voice.get_file = AsyncMock()

        services = {'ai_service': AsyncMock()}
        handler.get_services = AsyncMock(return_value=services)
        services['ai_service'].transcribe_audio = AsyncMock(side_effect=Exception("Transcription failed"))

        await handler.recibir_audio(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "Error procesando el audio" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_recibir_audio_cleans_up_temp_file(self, handler, mock_update, mock_context):
        """Test that temporary file is cleaned up after processing."""
        mock_update.message.voice = AsyncMock()
        mock_update.message.voice.get_file = AsyncMock()

        services = {'ai_service': AsyncMock()}
        handler.get_services = AsyncMock(return_value=services)
        services['ai_service'].transcribe_audio = AsyncMock(return_value="Transcribed text")

        with patch('tempfile.NamedTemporaryFile') as mock_temp:
            mock_temp_file = MagicMock()
            mock_temp_file.name = "/tmp/test.ogg"
            mock_temp.return_value.__enter__.return_value = mock_temp_file

            await handler.recibir_audio(mock_update, mock_context)

            # Verify temp file was cleaned up
            mock_temp_file.__exit__.assert_called_once()

    @pytest.mark.asyncio
    async def test_recibir_audio_calls_text_handler_with_transcription(self, handler, mock_update, mock_context):
        """Test that transcription is passed to text handler."""
        mock_update.message.voice = AsyncMock()
        mock_update.message.voice.get_file = AsyncMock()

        services = {'ai_service': AsyncMock()}
        handler.get_services = AsyncMock(return_value=services)
        services['ai_service'].transcribe_audio = AsyncMock(return_value="Transcribed text")

        mock_text_handler = AsyncMock()
        handler._get_text_handler = MagicMock(return_value=mock_text_handler)
        mock_text_handler.procesar_peticion = AsyncMock()

        handler.get_services = AsyncMock(return_value={'ai_service': AsyncMock()})
        services['ai_service'].transcribe_audio = AsyncMock(return_value="Transcribed text")

        with patch('tempfile.NamedTemporaryFile') as mock_temp:
            mock_temp_file = MagicMock()
            mock_temp_file.name = "/tmp/test.ogg"
            mock_temp.return_value.__enter__.return_value = mock_temp_file

            await handler.recibir_audio(mock_update, mock_context)

            # Verify text handler was called with transcription
            mock_text_handler.procesar_peticion.assert_called_once()
            call_args = mock_text_handler.procesar_peticion.call_args
            assert call_args[0][2] == "Transcribed text"  # texto_usuario argument


if __name__ == "__main__":
    pytest.main([__file__, "-v"])