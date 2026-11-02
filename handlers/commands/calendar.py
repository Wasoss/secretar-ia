"""
Calendar command handlers: calendar_status.
"""
import json
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from handlers.base import BaseHandler, handle_errors, require_auth
from config.logging import get_logger
from infrastructure.database.connection import get_pool
from infrastructure.database.repositories.credential_repo import CredentialRepository

logger = get_logger(__name__)


class CalendarCommandsHandler(BaseHandler):
    """Handler for calendar-related commands."""

    @handle_errors
    async def calendar_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /calendar_status - Diagnóstico detallado de Google Calendar."""
        if not await require_auth(update):
            return

        chat_id = str(update.effective_chat.id)
        try:
            pool = await get_pool()
            cred_repo = CredentialRepository(pool)

            # Verificar token en BD
            token_json = await cred_repo.get_token("google_calendar")

            mensaje = "📅 <b>Estado Google Calendar:</b>\n\n"

            if not token_json:
                mensaje += "❌ <b>Sin token OAuth en BD</b>\n"
                mensaje += "   Necesitás correr el flujo OAuth localmente una vez.\n\n"
                mensaje += "<b>Pasos:</b>\n"
                mensaje += "1. En local: <code>python -m scripts.setup_calendar</code>\n"
                mensaje += "2. Autorizá en el navegador\n"
                mensaje += "3. El token se guarda automáticamente en Neon\n"
                mensaje += "4. Redeploy en Render\n\n"
                mensaje += "<i>Alternativa: Insertar token JSON manualmente en tabla 'credenciales' (name='google_calendar')</i>"
            else:
                mensaje += "✅ Token encontrado en BD\n"
                try:
                    token_data = json.loads(token_json)
                    if 'expiry' in token_data:
                        mensaje += f"   Expira: {token_data['expiry']}\n"
                    if 'refresh_token' in token_data:
                        mensaje += "   ✅ Tiene refresh_token\n"
                    else:
                        mensaje += "   ⚠️ SIN refresh_token (no se puede renovar)\n"
                except Exception:
                    mensaje += "   ⚠️ Token con formato inválido\n"

                # Probar conexión real
                try:
                    services = await self.get_services()
                    calendar_service = services['calendar_service']
                    events = await calendar_service.get_upcoming_events(max_results=1)
                    mensaje += f"\n✅ Conexión API: OK ({len(events)} eventos próximos)"
                except Exception as e:
                    mensaje += f"\n❌ Error conectando a API: <code>{e}</code>"

            await update.message.reply_text(mensaje, parse_mode=ParseMode.HTML)

        except Exception as e:
            logger.error("calendar_status_failed", error=str(e), exc_info=True)
            await update.message.reply_text(f"❌ Error:\n<code>{e}</code>", parse_mode=ParseMode.HTML)


calendar_commands = CalendarCommandsHandler()
calendar_status = calendar_commands.calendar_status