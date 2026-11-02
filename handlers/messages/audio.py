"""
Audio message handler - processes voice notes and audio files.
"""
import os
import tempfile
from telegram import Update
from telegram.ext import ContextTypes

from handlers.base import BaseHandler, handle_errors, require_auth
from config.logging import get_logger

logger = get_logger(__name__)


class AudioMessageHandler(BaseHandler):
    """Handler for voice notes and audio files."""

    @handle_errors
    async def recibir_audio(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para notas de voz y audios."""
        if not await require_auth(update):
            return

        # Debug: loguear tipo de mensaje
        msg = update.message
        logger.info("audio_handler_triggered",
                    has_voice=bool(msg.voice),
                    has_audio=bool(msg.audio),
                    has_document=bool(msg.document))

        # Soportar voice (🎤), audio (📎 audio) y document audio
        voice = msg.voice or msg.audio
        if not voice:
            if msg.document and msg.document.mime_type and msg.document.mime_type.startswith('audio/'):
                voice = msg.document
            else:
                logger.warning("audio_no_voice_attribute", message_type=type(msg).__name__)
                await update.message.reply_text("❌ No detecté audio en el mensaje.")
                return

        archivo = await voice.get_file()
        # Usar tempfile para ruta writable en Render
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            ruta_audio = tmp.name

        try:
            await archivo.download_to_drive(ruta_audio)

            services = await self.get_services()
            ai_service = services['ai_service']

            transcripcion = await ai_service.transcribe_audio(ruta_audio)
            if transcripcion:
                logger.info("audio_transcribed_ok", length=len(transcripcion))
                # Reutilizar el handler de texto
                text_handler = self._get_text_handler()
                await text_handler.procesar_peticion(update, context, transcripcion)
            else:
                logger.warning("audio_transcription_empty")
                await update.message.reply_text("❌ No pude transcribir el audio.")
        except Exception as e:
            logger.error("audio_processing_failed", error=str(e), exc_info=True)
            await update.message.reply_text("❌ Error procesando el audio.")
        finally:
            try:
                os.remove(ruta_audio)
            except Exception:
                pass

    def _get_text_handler(self):
        """Lazy import to avoid circular dependency."""
        from handlers.messages.text import TextMessageHandler
        return TextMessageHandler()


audio_handler = AudioMessageHandler()
recibir_audio = audio_handler.recibir_audio