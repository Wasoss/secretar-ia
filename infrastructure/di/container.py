"""
Dependency Injection Container for Secretar-IA.

Replaces global mutable state with a proper singleton container
that manages service lifecycle and dependencies.
"""
import asyncpg
from typing import Optional
from config.settings import settings
from config.logging import get_logger

from application.services.ai_service import AIService
from application.services.calendar_service import CalendarService
from application.services.reminder_service import ReminderService
from application.services.summary_service import SummaryService
from application.services.weekly_planning_service import WeeklyPlanningService
from infrastructure.database.repositories.task_repo import TaskRepository
from infrastructure.database.repositories.plantilla_repo import PlantillaRepository
from infrastructure.database.repositories.objetivo_repo import ObjetivoRepository
from infrastructure.database.repositories.revision_repo import RevisionRepository
from infrastructure.database.repositories.credential_repo import CredentialRepository
from infrastructure.database.connection import init_db, close_pool

logger = get_logger(__name__)


class Container:
    """
    Dependency injection container managing all services and repositories.

    Services are lazily initialized on first access.
    All services are singletons within the container lifecycle.
    """

    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None
        self._services: dict = {}
        self._repos: dict = {}
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize database and all services."""
        if self._initialized:
            return

        logger.info("container_initializing")
        await init_db()

        # Pre-create pool
        self._pool = await self._create_pool()

        self._initialized = True
        logger.info("container_initialized")

    async def _create_pool(self) -> asyncpg.Pool:
        """Create database connection pool."""
        from infrastructure.database.connection import get_pool
        return await get_pool()

    async def close(self) -> None:
        """Close all resources."""
        if self._pool:
            await close_pool()
            self._pool = None
        logger.info("container_closed")

    # --- Database Pool ---
    async def get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await self._create_pool()
        return self._pool

    # --- Services ---
    def get_ai_service(self) -> AIService:
        if 'ai' not in self._services:
            self._services['ai'] = AIService()
            logger.debug("ai_service_created")
        return self._services['ai']

    def get_calendar_service(self) -> CalendarService:
        if 'calendar' not in self._services:
            self._services['calendar'] = CalendarService()
            logger.debug("calendar_service_created")
        return self._services['calendar']

    def get_reminder_service(self) -> ReminderService:
        if 'reminder' not in self._services:
            self._services['reminder'] = ReminderService()
            logger.debug("reminder_service_created")
        return self._services['reminder']

    async def get_summary_service(self) -> SummaryService:
        if 'summary' not in self._services:
            task_repo = await self.get_task_repo()
            calendar_service = self.get_calendar_service()
            ai_service = self.get_ai_service()
            self._services['summary'] = SummaryService(task_repo, calendar_service, ai_service)
            logger.debug("summary_service_created")
        return self._services['summary']

    async def get_weekly_planning_service(self) -> WeeklyPlanningService:
        if 'weekly_planning' not in self._services:
            task_repo = await self.get_task_repo()
            plantilla_repo = await self.get_plantilla_repo()
            objetivo_repo = await self.get_objetivo_repo()
            revision_repo = await self.get_revision_repo()
            calendar_service = self.get_calendar_service()
            ai_service = self.get_ai_service()

            self._services['weekly_planning'] = WeeklyPlanningService(
                task_repo=task_repo,
                plantilla_repo=plantilla_repo,
                objetivo_repo=objetivo_repo,
                revision_repo=revision_repo,
                calendar_service=calendar_service,
                ai_service=ai_service,
            )
            logger.debug("weekly_planning_service_created")
        return self._services['weekly_planning']

    # --- Repositories ---
    async def get_task_repo(self) -> TaskRepository:
        if 'task_repo' not in self._repos:
            pool = await self.get_pool()
            self._repos['task_repo'] = TaskRepository(pool)
            logger.debug("task_repo_created")
        return self._repos['task_repo']

    async def get_plantilla_repo(self) -> PlantillaRepository:
        if 'plantilla_repo' not in self._repos:
            pool = await self.get_pool()
            self._repos['plantilla_repo'] = PlantillaRepository(pool)
            logger.debug("plantilla_repo_created")
        return self._repos['plantilla_repo']

    async def get_objetivo_repo(self) -> ObjetivoRepository:
        if 'objetivo_repo' not in self._repos:
            pool = await self.get_pool()
            self._repos['objetivo_repo'] = ObjetivoRepository(pool)
            logger.debug("objetivo_repo_created")
        return self._repos['objetivo_repo']

    async def get_revision_repo(self) -> RevisionRepository:
        if 'revision_repo' not in self._repos:
            pool = await self.get_pool()
            self._repos['revision_repo'] = RevisionRepository(pool)
            logger.debug("revision_repo_created")
        return self._repos['revision_repo']

    async def get_credential_repo(self) -> CredentialRepository:
        if 'credential_repo' not in self._repos:
            pool = await self.get_pool()
            self._repos['credential_repo'] = CredentialRepository(pool)
            logger.debug("credential_repo_created")
        return self._repos['credential_repo']

    # --- Convenience: Get all services at once (for backward compatibility) ---
    async def get_all_services(self) -> dict:
        """Get all services as a dict (for migration period)."""
        return {
            'ai_service': self.get_ai_service(),
            'calendar_service': self.get_calendar_service(),
            'reminder_service': self.get_reminder_service(),
            'summary_service': await self.get_summary_service(),
            'weekly_planning_service': await self.get_weekly_planning_service(),
            'task_repo': await self.get_task_repo(),
            'plantilla_repo': await self.get_plantilla_repo(),
            'objetivo_repo': await self.get_objetivo_repo(),
            'revision_repo': await self.get_revision_repo(),
        }


# Global container instance (singleton)
_container: Optional[Container] = None


def get_container() -> Container:
    """Get the global container instance."""
    global _container
    if _container is None:
        _container = Container()
    return _container


async def initialize_container() -> Container:
    """Initialize the global container."""
    container = get_container()
    await container.initialize()
    return container


async def close_container() -> None:
    """Close the global container."""
    global _container
    if _container:
        await _container.close()
        _container = None