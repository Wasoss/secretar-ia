"""
Servicio de Google Calendar - Wrapper asíncrono de la API.

Maneja OAuth, creación/lectura de eventos y persistencia de tokens en BD.
Versión mejorada con:
- Detección de conflictos
- Sync bidireccional (actualizar/eliminar eventos)
- Soporte para recurrencia (RRULE)
- Manejo robusto de errores
"""
import json
import datetime
from typing import Optional, List
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

    def _normalize_datetime(self, dt: datetime.datetime) -> datetime.datetime:
        """Asegura que el datetime sea timezone-aware en zona de Argentina."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=settings.tz)
        elif dt.tzinfo != settings.tz:
            dt = dt.astimezone(settings.tz)
        return dt

    async def create_event(
        self,
        summary: str,
        start_dt: datetime.datetime,
        end_dt: Optional[datetime.datetime] = None,
        description: str = "",
        recurrence: Optional[str] = None,
        reminders: Optional[List[dict]] = None,
    ) -> Optional[dict]:
        """
        Crea un evento en el calendario principal.

        Args:
            summary: Título del evento
            start_dt: Fecha/hora de inicio (timezone-aware)
            end_dt: Fecha/hora de fin (default: +1 hora)
            description: Descripción del evento
            recurrence: RRULE string (ej: "FREQ=WEEKLY;BYDAY=MO")
            reminders: Lista de overrides de recordatorios

        Returns:
            Evento creado (dict de la API) o None si falla
        """
        try:
            await self.ensure_credentials()
            service = self._get_service()

            start_dt = self._normalize_datetime(start_dt)
            if end_dt is None:
                end_dt = start_dt + datetime.timedelta(hours=1)
            else:
                end_dt = self._normalize_datetime(end_dt)

            event = {
                'summary': summary,
                'description': description,
                'start': {
                    'dateTime': start_dt.isoformat(),
                    'timeZone': str(settings.tz),
                },
                'end': {
                    'dateTime': end_dt.isoformat(),
                    'timeZone': str(settings.tz),
                },
            }

            # Recurrencia
            if recurrence:
                event['recurrence'] = [f"RRULE:{recurrence}"]

            # Recordatorios personalizados
            if reminders is not None:
                event['reminders'] = {
                    'useDefault': False,
                    'overrides': reminders,
                }
            else:
                # Default: 1 día antes y 1 hora antes
                event['reminders'] = {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'popup', 'minutes': 24 * 60},
                        {'method': 'popup', 'minutes': 60},
                    ],
                }

            created_event = service.events().insert(calendarId='primary', body=event).execute()
            logger.info("calendar_event_created",
                       summary=summary, start=start_dt.isoformat(), event_id=created_event.get('id'))
            return created_event

        except HttpError as e:
            logger.error("calendar_api_error", error=str(e), status=e.resp.status)
            return None
        except Exception as e:
            logger.error("calendar_event_creation_failed", error=str(e), exc_info=True)
            return None

    async def get_upcoming_events(self, max_results: int = 10, time_min: Optional[datetime.datetime] = None) -> List[dict]:
        """
        Obtiene próximos eventos del calendario principal.

        Args:
            max_results: Máximo número de eventos
            time_min: Fecha mínima (default: ahora)

        Returns:
            Lista de eventos (dicts de la API de Google)
        """
        try:
            await self.ensure_credentials()
            service = self._get_service()

            if time_min is None:
                time_min = datetime.datetime.now(settings.tz)
            time_min = self._normalize_datetime(time_min)

            events_result = service.events().list(
                calendarId='primary',
                timeMin=time_min.isoformat(),
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

    async def check_conflicts(
        self,
        start_dt: datetime.datetime,
        end_dt: datetime.datetime,
        exclude_event_id: Optional[str] = None
    ) -> List[dict]:
        """
        Verifica si hay conflictos de horario en el calendario.

        Args:
            start_dt: Inicio del nuevo evento
            end_dt: Fin del nuevo evento
            exclude_event_id: ID de evento a excluir (para updates)

        Returns:
            Lista de eventos que conflictan
        """
        try:
            await self.ensure_credentials()
            service = self._get_service()

            start_dt = self._normalize_datetime(start_dt)
            end_dt = self._normalize_datetime(end_dt)

            # Buscar eventos en el rango
            events_result = service.events().list(
                calendarId='primary',
                timeMin=start_dt.isoformat(),
                timeMax=end_dt.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            events = events_result.get('items', [])

            # Filtrar el evento excluido
            if exclude_event_id:
                events = [e for e in events if e.get('id') != exclude_event_id]

            logger.debug("calendar_conflict_check", conflicts=len(events),
                        start=start_dt.isoformat(), end=end_dt.isoformat())
            return events

        except HttpError as e:
            logger.error("calendar_conflict_check_failed", error=str(e))
            return []
        except Exception as e:
            logger.error("calendar_conflict_check_failed", error=str(e), exc_info=True)
            return []

    async def update_event(
        self,
        event_id: str,
        summary: Optional[str] = None,
        start_dt: Optional[datetime.datetime] = None,
        end_dt: Optional[datetime.datetime] = None,
        description: Optional[str] = None,
        recurrence: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Actualiza un evento existente.

        Args:
            event_id: ID del evento a actualizar
            summary: Nuevo título (opcional)
            start_dt: Nueva fecha/hora inicio (opcional)
            end_dt: Nueva fecha/hora fin (opcional)
            description: Nueva descripción (opcional)
            recurrence: Nueva recurrencia (opcional)

        Returns:
            Evento actualizado o None si falla
        """
        try:
            await self.ensure_credentials()
            service = self._get_service()

            # Obtener evento actual
            event = service.events().get(calendarId='primary', eventId=event_id).execute()

            # Actualizar campos
            if summary is not None:
                event['summary'] = summary
            if description is not None:
                event['description'] = description
            if start_dt is not None:
                start_dt = self._normalize_datetime(start_dt)
                event['start'] = {'dateTime': start_dt.isoformat(), 'timeZone': str(settings.tz)}
            if end_dt is not None:
                end_dt = self._normalize_datetime(end_dt)
                event['end'] = {'dateTime': end_dt.isoformat(), 'timeZone': str(settings.tz)}
            if recurrence is not None:
                if recurrence:
                    event['recurrence'] = [f"RRULE:{recurrence}"]
                elif 'recurrence' in event:
                    del event['recurrence']

            updated_event = service.events().update(
                calendarId='primary', eventId=event_id, body=event
            ).execute()

            logger.info("calendar_event_updated", event_id=event_id)
            return updated_event

        except HttpError as e:
            if e.resp.status == 404:
                logger.warning("calendar_event_not_found", event_id=event_id)
            else:
                logger.error("calendar_update_error", error=str(e), status=e.resp.status)
            return None
        except Exception as e:
            logger.error("calendar_update_failed", error=str(e), exc_info=True)
            return None

    async def delete_event(self, event_id: str) -> bool:
        """
        Elimina un evento por ID.

        Args:
            event_id: ID del evento a eliminar

        Returns:
            True si se eliminó exitosamente
        """
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

    async def find_event_by_summary_and_date(
        self,
        summary: str,
        date: datetime.datetime
    ) -> Optional[dict]:
        """
        Busca un evento por título y fecha aproximada (útil para REAGENDAR).

        Args:
            summary: Título o parte del título
            date: Fecha aproximada

        Returns:
            Evento encontrado o None
        """
        try:
            await self.ensure_credentials()
            service = self._get_service()

            # Buscar en rango de 3 días alrededor de la fecha
            start = self._normalize_datetime(date - datetime.timedelta(days=2))
            end = self._normalize_datetime(date + datetime.timedelta(days=2))

            events_result = service.events().list(
                calendarId='primary',
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy='startTime',
                q=summary  # Query de texto libre
            ).execute()

            events = events_result.get('items', [])
            for event in events:
                if summary.lower() in event.get('summary', '').lower():
                    return event

            return None

        except Exception as e:
            logger.error("calendar_find_event_failed", error=str(e))
            return None

    async def sync_event_from_local(
        self,
        local_task_id: int,
        summary: str,
        start_dt: datetime.datetime,
        end_dt: Optional[datetime.datetime] = None,
        description: str = "",
        recurrence: Optional[str] = None,
        existing_event_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Sincroniza una tarea local con Calendar (create o update).

        Args:
            local_task_id: ID de la tarea local
            summary: Título
            start_dt: Inicio
            end_dt: Fin
            description: Descripción
            recurrence: RRULE
            existing_event_id: ID de evento ya sincronizado (para update)

        Returns:
            Event ID de Google Calendar o None si falla
        """
        if existing_event_id:
            # Actualizar evento existente
            updated = await self.update_event(
                event_id=existing_event_id,
                summary=summary,
                start_dt=start_dt,
                end_dt=end_dt,
                description=description,
                recurrence=recurrence,
            )
            return existing_event_id if updated else None
        else:
            # Crear nuevo
            created = await self.create_event(
                summary=summary,
                start_dt=start_dt,
                end_dt=end_dt,
                description=description,
                recurrence=recurrence,
            )
            return created.get('id') if created else None