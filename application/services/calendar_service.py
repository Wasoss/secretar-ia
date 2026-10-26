"""
Servicio de Google Calendar - Wrapper asíncrono de la API.

Maneja OAuth, creación/lectura de eventos y persistencia de tokens en BD.
"""
import json
import datetime
from typing import Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config.settings import settings
from config.logging import get_logger
from infrastructure.database.connection import get_pool
from infrastructure.database.repositories.credential_repo import CredentialRepository

logger = get_logger(__name__)

SCOPES = ['https://www.googleapis.com/auth/calendar']


class CalendarService:
    """Servicio para interactuar con Google Calendar API."""

    def __init__(self):
        self._service = None
        self._creds: Credentials | None = None

    async def ensure_credentials(self) -> Credentials:
        """
        Obtiene credenciales válidas (refresca o inicia flujo OAuth si es necesario).

        Returns:
            Credentials válidas de Google

        Raises:
            RuntimeError: Si no se pueden obtener credenciales
        """
        if self._creds and self._creds.valid:
            return self._creds

        # 1. Intentar cargar token persistido en BD
        pool = await get_pool()
        cred_repo = CredentialRepository(pool)
        token_json = await cred_repo.get_token("google_calendar")

        if token_json:
            try:
                self._creds = Credentials.from_authorized_user_info(
                    json.loads(token_json), SCOPES
                )
            except Exception as e:
                logger.warning("stored_token_invalid", error=str(e))
                self._creds = None

        # 2. Refrescar si expirado pero hay refresh_token
        if self._creds and self._creds.expired and self._creds.refresh_token:
            try:
                self._creds.refresh(Request())
                await cred_repo.save_token("google_calendar", self._creds.to_json())
                logger.info("calendar_token_refreshed")
            except Exception as e:
                logger.warning("token_refresh_failed", error=str(e))
                self._creds = None

        # 3. Si no hay credenciales válidas, iniciar flujo OAuth
        if not self._creds or not self._creds.valid:
            # En entorno serverless (Render), NO podemos usar run_local_server
            # El token DEBE estar ya en BD (inyectado manualmente o en setup inicial)
            if not self._creds:
                raise RuntimeError(
                    "No hay credenciales de Google Calendar válidas. "
                    "Ejecutá el flujo OAuth localmente una vez para guardar el token en la BD."
                )
            # Si tenemos creds pero no son válidas y no se pueden refrescar
            raise RuntimeError("Credenciales de Google Calendar inválidas y no se pueden refrescar")

        return self._creds

    def _get_service(self):
        """Obtiene cliente de la API de Calendar (lazy)."""
        if self._service is None:
            self._service = build('calendar', 'v3', credentials=self._creds)
        return self._service

    async def create_event(self, summary: str, start_dt: datetime.datetime) -> bool:
        """
        Crea un evento en el calendario principal.

        Args:
            summary: Título del evento
            start_dt: Fecha/hora de inicio (debe ser timezone-aware)

        Returns:
            True si se creó exitosamente
        """
        try:
            await self.ensure_credentials()
            service = self._get_service()

            # Asegurar timezone aware en zona de Argentina
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=settings.tz)
            elif start_dt.tzinfo != settings.tz:
                start_dt = start_dt.astimezone(settings.tz)

            end_dt = start_dt + datetime.timedelta(hours=1)

            event = {
                'summary': summary,
                'start': {
                    'dateTime': start_dt.isoformat(),
                    'timeZone': str(settings.tz),
                },
                'end': {
                    'dateTime': end_dt.isoformat(),
                    'timeZone': str(settings.tz),
                },
                # Recordatorios: 1 día antes y 1 hora antes
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'popup', 'minutes': 24 * 60},
                        {'method': 'popup', 'minutes': 60},
                    ],
                },
            }

            service.events().insert(calendarId='primary', body=event).execute()
            logger.info("calendar_event_created", summary=summary, start=start_dt.isoformat())
            return True

        except HttpError as e:
            logger.error("calendar_api_error", error=str(e), status=e.resp.status)
            return False
        except Exception as e:
            logger.error("calendar_event_creation_failed", error=str(e), exc_info=True)
            return False

    async def get_upcoming_events(self, max_results: int = 5) -> list[dict]:
        """
        Obtiene próximos eventos del calendario principal.

        Returns:
            Lista de eventos (dicts de la API de Google)
        """
        try:
            await self.ensure_credentials()
            service = self._get_service()

            now = datetime.datetime.now(settings.tz).isoformat()
            events_result = service.events().list(
                calendarId='primary',
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            events = events_result.get('items', [])
            logger.debug("calendar_events_fetched", count=len(events))
            return events

        except HttpError as e:
            logger.error("calendar_api_error", error=str(e), status=e.resp.status)
            return []
        except Exception as e:
            logger.error("calendar_fetch_failed", error=str(e), exc_info=True)
            return []

    async def delete_event(self, event_id: str) -> bool:
        """Elimina un evento por ID."""
        try:
            await self.ensure_credentials()
            service = self._get_service()
            service.events().delete(calendarId='primary', eventId=event_id).execute()
            logger.info("calendar_event_deleted", event_id=event_id)
            return True
        except HttpError as e:
            if e.resp.status == 404:
                logger.warning("calendar_event_not_found", event_id=event_id)
            else:
                logger.error("calendar_delete_error", error=str(e))
            return False
        except Exception as e:
            logger.error("calendar_delete_failed", error=str(e), exc_info=True)
            return False