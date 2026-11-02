# Secretar-IA - Recommended Improvements

## Executive Summary

The codebase is a well-structured Telegram bot with clean architecture separation (application/infrastructure layers). However, `main.py` has grown to 1,469 lines and violates several clean architecture principles. This document outlines prioritized improvements.

---

## 1. Critical Issues (Must Fix)

### 1.1 God Object: `main.py` (1,469 lines)
**Problem**: Single file contains:
- 25+ command handlers
- 15+ intent handlers  
- 30+ callback handlers
- Job scheduling logic
- HTTP health check server
- Formatting utilities
- Business logic mixed with Telegram framework code

**Impact**: Hard to test, maintain, and reason about. Violates Single Responsibility Principle.

**Fix**: Split into handler modules by domain (see refactoring plan).

### 1.2 Global Mutable State
**Problem**: 9 global service variables at module level (lines 38-47):
```python
ai_service: AIService = None
calendar_service: CalendarService = None
reminder_service: ReminderService = None
# ... 6 more
```

**Impact**: 
- Impossible to test in isolation
- Race conditions in concurrent environments
- Hidden dependencies
- Breaks dependency injection

**Fix**: Use proper dependency injection via `Application.bot_data` or a container.

### 1.3 Tight Coupling to Telegram Framework
**Problem**: Business logic directly uses `Update`, `ContextTypes`, `InlineKeyboardMarkup` from `python-telegram-bot`.

**Impact**: Cannot unit test handlers without full Telegram mock. Cannot reuse logic for other interfaces (web, CLI, API).

**Fix**: Extract pure business logic into use cases/services that accept plain Python objects.

### 1.4 No Error Boundary Pattern
**Problem**: Each handler has try/except with duplicate logging and user messaging.

**Fix**: Create `@handle_errors` decorator or middleware.

---

## 2. High Priority Improvements

### 2.1 Extract Handler Classes
Split `main.py` into domain-specific handlers:

```
handlers/
├── __init__.py
├── base.py              # BaseHandler with error handling, auth
├── commands/
│   ├── __init__.py
│   ├── basic.py         # start, ajuda, status, ping, test
│   ├── calendar.py      # calendar_status
│   ├── agenda.py        # hoje, semana, buscar, tag, pendientes
│   ├── templates.py     # plantillas
│   ├── objectives.py    # objetivos
│   └── review.py        # revision, resumen
├── messages/
│   ├── __init__.py
│   ├── text.py          # receber_texto → procesar_peticion
│   └── audio.py         # receber_audio
├── callbacks/
│   ├── __init__.py
│   ├── completion.py    # complete_, delete_
│   └── subtasks.py      # subtask_
└── jobs/
    ├── __init__.py
    ├── daily.py         # template, summary, evening
    ├── weekly.py        # weekly_review
    └── maintenance.py   # keep_alive
```

### 2.2 Introduce Use Case Layer
Create application use cases that orchestrate services without framework knowledge:

```python
# application/use_cases/
├── create_event.py           # CreateEventUseCase
├── create_reminder.py        # CreateReminderUseCase
├── create_note.py            # CreateNoteUseCase
├── create_daily_task.py      # CreateDailyTaskUseCase
├── reschedule_task.py        # RescheduleTaskUseCase
├── delete_task.py            # DeleteTaskUseCase
├── complete_task.py          # CompleteTaskUseCase
├── complete_subtask.py       # CompleteSubtaskUseCase
├── list_agenda.py            # ListAgendaUseCase
├── search_tasks.py           # SearchTasksUseCase
├── manage_template.py        # TemplateUseCases
├── manage_objective.py       # ObjectiveUseCases
├── generate_summary.py       # SummaryUseCases
└── weekly_review.py          # WeeklyReviewUseCase
```

### 2.3 Dependency Injection Container
Replace globals with a simple container:

```python
# infrastructure/di/container.py
class Container:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._pool: asyncpg.Pool | None = None
        self._services: dict = {}
    
    async def get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await create_pool(self.settings.database_url)
        return self._pool
    
    def get_ai_service(self) -> AIService:
        if 'ai' not in self._services:
            self._services['ai'] = AIService(self.settings)
        return self._services['ai']
    
    def get_calendar_service(self) -> CalendarService:
        if 'calendar' not in self._services:
            self._services['calendar'] = CalendarService(self.get_pool)
        return self._services['calendar']
    
    # ... other services
    
    def get_task_repo(self) -> TaskRepository:
        pool = await self.get_pool()
        return TaskRepository(pool)
```

### 2.4 Standardize Error Handling
```python
# application/exceptions.py
class SecretarIAError(Exception):
    """Base exception with user-friendly message."""
    def __init__(self, user_message: str, log_message: str = None):
        self.user_message = user_message
        self.log_message = log_message or user_message
        super().__init__(log_message)

class CalendarUnavailableError(SecretarIAError):
    pass

class AuthenticationError(SecretarIAError):
    pass

# decorators.py
def handle_telegram_errors(handler):
    @wraps(handler)
    async def wrapper(update, context):
        try:
            return await handler(update, context)
        except SecretarIAError as e:
            logger.warning(e.log_message)
            if update.message:
                await update.message.reply_text(f"⚠️ {e.user_message}")
        except Exception as e:
            logger.error("handler_failed", error=str(e), exc_info=True)
            if update.message:
                await update.message.reply_text("❌ Error interno. Probá /test")
    return wrapper
```

---

## 3. Medium Priority Improvements

### 3.1 Testing Strategy
**Current**: Only 1 SQLite test (not testing actual code).

**Needed**:
- Unit tests for each use case (mock repositories)
- Integration tests for repositories (testcontainers PostgreSQL)
- Contract tests for AI service (fixed prompt responses)
- E2E tests for critical flows (using pytest-asyncio)

```python
# tests/unit/use_cases/test_create_event.py
@pytest.fixture
def mock_repo():
    return AsyncMock(spec=TaskRepository)

@pytest.fixture
def mock_calendar():
    return AsyncMock(spec=CalendarService)

async def test_create_event_success(mock_repo, mock_calendar):
    use_case = CreateEventUseCase(mock_repo, mock_calendar)
    result = await use_case.execute(
        user_id="123",
        details="Reunión con Juan",
        fecha_hora=datetime(2025, 1, 15, 14, 0),
        tags=["trabajo"]
    )
    assert result.success
    mock_repo.save.assert_called_once()
    mock_calendar.create_event.assert_called_once()
```

### 3.2 Input Validation with Pydantic
Replace manual validation in handlers with Pydantic models:

```python
# application/dto.py
class CreateEventRequest(BaseModel):
    details: str = Field(min_length=1, max_length=200)
    fecha_hora: datetime
    recurrencia: str | None = Field(pattern=r"^FREQ=(DAILY|WEEKLY|MONTHLY|YEARLY)")
    prioridad: int = Field(ge=-1, le=1)
    tags: list[str] = Field(default_factory=list)
    
    @field_validator('fecha_hora')
    @classmethod
    def must_be_future(cls, v):
        if v <= datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")):
            raise ValueError("Fecha debe ser futura")
        return v
```

### 3.3 Improve AI Service Reliability
- Add retry with exponential backoff for Groq API
- Implement circuit breaker pattern
- Add request/response caching for repeated queries
- Add token usage tracking and cost monitoring

```python
# application/services/ai_service.py improvements
from tenacity import retry, stop_after_attempt, wait_exponential

class AIService:
    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3)
    )
    async def classify_intent(self, text: str) -> ParsedIntent:
        # ... existing code
```

### 3.4 Calendar Sync Resilience
- Implement outbox pattern for Calendar operations
- Add reconciliation job to fix drift
- Support batch operations

```python
# infrastructure/outbox/calendar_outbox.py
class CalendarOutbox:
    async def enqueue_create(self, task_id: int, event_data: dict):
        await pool.execute("""
            INSERT INTO calendar_outbox (task_id, operation, payload)
            VALUES ($1, 'CREATE', $2)
        """, task_id, json.dumps(event_data))
    
    async def process(self) -> int:
        # Process pending operations
        pass
```

### 3.5 Structured Configuration for Jobs
Move job scheduling to configuration:

```python
# config/jobs.py
JOB_SCHEDULE = {
    "daily_template": {
        "func": "apply_daily_template",
        "time": "06:30",
        "timezone": "America/Argentina/Buenos_Aires",
    },
    "morning_summary": {
        "func": "send_daily_summary",
        "time": "06:50",
        "timezone": "America/Argentina/Buenos_Aires",
    },
    # ...
}
```

---

## 4. Low Priority / Nice to Have

### 4.1 API Layer for Web Dashboard
Add FastAPI for a web dashboard:
- View/edit tasks
- Calendar visualization
- Weekly review history
- Objective tracking charts

### 4.2 Multi-user Support (Beyond Single Chat)
Current: Single `MI_TELEGRAM_ID` hardcoded.
Future: Support multiple users with proper isolation.

### 4.3 Plugin System for Actions
Allow adding new action types without modifying core:
```python
# application/actions/registry.py
class ActionRegistry:
    def __init__(self):
        self._handlers: dict[ActionType, ActionHandler] = {}
    
    def register(self, action_type: ActionType, handler: ActionHandler):
        self._handlers[action_type] = handler
    
    def get(self, action_type: ActionType) -> ActionHandler:
        return self._handlers.get(action_type)
```

### 4.4 Observability
- Add OpenTelemetry tracing
- Metrics: commands/min, AI latency, Calendar sync success rate
- Health check endpoints with dependency status

### 4.5 Internationalization (i18n)
Extract all user-facing strings to translation files.

---

## 5. Refactoring Priority Order

| Phase | Task | Effort | Risk |
|-------|------|--------|------|
| 1 | Extract global services → DI Container | Low | Low |
| 2 | Create base handler with error handling | Low | Low |
| 3 | Split command handlers into modules | Medium | Low |
| 4 | Extract use cases for business logic | Medium | Medium |
| 5 | Split message/callback handlers | Medium | Low |
| 6 | Add comprehensive test suite | High | Low |
| 7 | Add input validation (Pydantic DTOs) | Medium | Low |
| 8 | Implement outbox for Calendar sync | Medium | Medium |
| 9 | Add observability (metrics, tracing) | Low | Low |
| 10 | Multi-user support | High | High |

---

## 6. Immediate Quick Wins (Can Do Today)

1. **Fix global state**: Move services to `application.bot_data` dictionary
2. **Add error decorator**: Eliminate duplicate try/except blocks
3. **Extract formatting utils**: Move `_build_confirmation_message`, `formatear_fecha_arg`, `_event_starts_today`, `_event_in_range` to `utils/formatters.py`
4. **Add type hints**: Add missing return types in handlers
5. **Remove dead code**: `ajuda_fixed.py`, `ajuda_fixed.txt`, `modelos.py`, `motor_ia.py`, `base_datos.py`, `calendario.py`, `fix_cal.py` (legacy files)
6. **Add .gitignore entries**: `__pycache__/`, `venv/`, `secretaria.db`, `token.json`
7. **Pin dependencies**: Create `requirements.txt` with pinned versions

---

## 7. Architecture Decision Records Needed

Create ADRs for:
- ADR-001: Why asyncpg over SQLAlchemy?
- ADR-002: Why Groq/qwen over OpenAI?
- ADR-003: Single-user vs multi-user architecture
- ADR-004: Job scheduling approach (PTB job_queue vs APScheduler vs cron)
- ADR-005: Calendar sync strategy (eventual consistency vs strong)