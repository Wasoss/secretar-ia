# ESTADO DEL PROYECTO: Secretar-IA
**Fecha:** 2026-11-02
**Versión:** 1.0 (en desarrollo)

---

## ✅ LO REALIZADO (Completado y Deployado)

### ✅ FIXES CRÍTICOS DEPLOYADOS (en producción)

| Issue | Root Cause | Fix Aplicado | Commit |
|-------|------------|--------------|--------|
| **Date parsing: "martes 12/11" no reconocido** | Regex sin patrón para día_semana DD/MM | Patrón non-capturing group `(?:lunes\|martes\|mi[eé]rcoles\|jueves\|viernes\|s[áa]bado\|domingo)\s+(\d{1,2})/(\d{1,2})...` | `b0051d7` |
| **/ayuda y shortcuts no respondían** | Excepción en `verificar_usuario()` fuera de try/except + shortcut sin try/except | try/except envolviendo TODO el cuerpo de `ayuda()` + try/except en shortcut de `procesar_peticion` | `301cfef`, `503e3ba` |
| **"No error handlers are registered"** | Falta `app.add_error_handler(error_handler)` | Error handler global agregado en `main.py` | `6b6310d` |
| **/ping no existía** | Falta comando de health check simple | Agregado `/ping` → "🏓 Pong!" | `40289ea` |
| **HTML inválido en /ayuda** | Tag `<texto>` no escapado en `/buscar <texto>` | Escapado a `<texto>` | `54e4941` |
| **Shortcut "ayuda" limitado** | Solo 3 variantes | Agregadas 6 variantes: "ayuda", "lista de comandos", "comandos", "menu", "menú", "help" | `0bf8ce9`, `54e4941` |
| **Date parsing "mañana reunion..."** | Regex con capturing group que desplazaba índices | Non-capturing groups `(?:...)` en todos los patrones | `52bba43` |

### Funcionalidades Core Operativas ✅
- **Eventos/Recordatorios/Notas** → Guardado en BD + Sync Google Calendar (bidireccional)
- **Tareas diarias con sub-items** → Checkboxes interactivos (inline keyboard)
- **Plantillas diarias** → Creación, listado, activación, auto-aplicación 6:30 AM
- **Objetivos semanales** → Creación, progreso, lista, revisión semanal domingos 10:00
- **Revisión semanal** → Domingos 10:00 AM con stats, objetivos, plantillas usadas
- **Resumen matutino** 6:50 AM + Recordatorio vespertino 18:00
- **NLP con Groq (qwen/qwen3-32b)** → Clasificación de intenciones + parsing fechas relativas
- **Google Calendar bidireccional** → Create/Update/Delete + Conflict detection
- **NLP con fallback regex** → Fallback `_parse_relative_date()` si IA falla
- **Health check + Keep-alive** → Para Render free tier (cada 5 min)

---

## 🔴 LO QUE FALTA MEJORAR (PENDIENTE)

---

### 1. 🔴 REESTRUCTURACIÓN / FACTORIZACIÓN DE CÓDIGO
**Prioridad: ALTA**

| Archivo | Líneas | Problema | Acción Requerida |
|---------|--------|----------|------------------|
| `main.py` | ~1450 líneas | God class: handlers + jobs + setup + utils todo en uno | Split en módulos: `handlers/`, `jobs/`, `services/`, `utils/` |
| `ai_service.py` | ~570 líneas | Prompt gigante hardcodeado + lógica parsing + IA en uno | Separar: `prompts/`, `parsers/`, `ai_client.py` |
| `weekly_planning_service.py` | 350+ líneas | Lógica plantillas + objetivos + revisiones en una clase | Split: `TemplateService`, `GoalService`, `ReviewService` |
| `summary_service.py` | 350+ líneas | Resumen matutino + vespertino + custom + suggestions | Split: `MorningSummary`, `EveningReminder`, `CustomSummary` |
| `task_repo.py` | 500+ líneas | Queries SQL mezcladas con lógica de dominio | Repository pattern puro + Query Builders |

**Archivos a crear:**
```
application/
├── handlers/
│   ├── __init__.py
│   ├── command_handlers.py      # /start, /ayuda, /test, /ping, /hoy, /semana, etc.
│   ├── message_handlers.py      # recibir_texto, recibir_audio, callbacks
│   └── callback_handlers.py     # complete_, delete_, subtask_
├── jobs/
│   ├── __init__.py
│   ├── daily_jobs.py            # plantilla 6:30, resumen 6:50, vespertino 18:00
│   ├── weekly_jobs.py           # revisión semanal domingos 10:00
│   └── keep_alive.py            # keep-alive DB
├── services/
│   ├── __init__.py
│   ├── ai_service.py            # (ya existe, refactorizar)
│   ├── calendar_service.py
│   ├── reminder_service.py
│   ├── summary_service.py       # → split en morning/evening/custom
│   └── weekly_planning_service.py  # → split en Template/Goal/Review
├── parsers/
│   ├── __init__.py
│   ├── date_parser.py           # _parse_relative_date + regex patterns
│   └── intent_classifier.py     # classify_intent + prompt templates
├── prompts/
│   ├── __init__.py
│   ├── system_prompts.py        # SYSTEM_PROMPT_TEMPLATE + ejemplos
│   └── examples.py              # EJEMPLOS como data structure
└── utils/
    ├── __init__.py
    ├── date_utils.py            # formatear_fecha_arg, _parse_relative_date
    └── html_utils.py            # escape_html, format_telegram_html
```

---

### 2. 🟡 AGREGAR AUTOTESTING
**Prioridad: ALTA**

| Tipo | Cobertura Actual | Objetivo | Herramientas |
|------|------------------|----------|--------------|
| Unit tests | 0% | >80% | `pytest` + `pytest-asyncio` + `pytest-mock` |
| Integration tests | 0% | >60% | `pytest` + `testcontainers` (PostgreSQL) |
| Contract tests | 0% | APIs críticas | `schemathesis` / `pact` |
| E2E tests | 0% | Flujos críticos | `pytest` + `telegram-bot-api` mock |

**Estructura de tests propuesta:**
```
tests/
├── unit/
│   ├── test_date_parser.py          # _parse_relative_date cases
│   ├── test_intent_classifier.py    # classify_intent + prompt rendering
│   ├── test_task_repo.py            # CRUD + queries (mock DB)
│   ├── test_plantilla_service.py    # CRUD plantillas + apply_daily_template
│   ├── test_objetivo_service.py     # CRUD objetivos + progreso
│   └── test_summary_service.py      # send_daily_summary formatting
├── integration/
│   ├── test_calendar_sync.py        # create/update/delete events
│   ├── test_daily_template_flow.py  # plantilla → tarea_diaria → summary
│   └── test_recurring_events.py     # RRULE generation + parsing
├── e2e/
│   └── test_bot_flow.py             # Bot completo con mock Telegram API
└── fixtures/
    ├── sample_messages.json         # Inputs reales del usuario
    ├── expected_intents.json        # Intents esperados
    └── sample_events.json           # Eventos Calendar mock
```

**Configuración pytest.ini:**
```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
asyncio_mode = auto
addopts = -v --tb=short --strict-markers
markers =
    unit: Unit tests
    integration: Integration tests
    e2e: End-to-end tests
    slow: Tests that take >5s
```

---

### 3. 🔴 CIBERSEGURIDAD (Para venta del código)
**Prioridad: CRÍTICA si se vende el código**

| Área | Estado Actual | Riesgo | Acción Requerida |
|------|---------------|--------|------------------|
| **Secrets Management** | `.env` en repo (gitignore OK pero historial tiene leaks) | CRÍTICO | Rotar TODAS las secrets (Groq API, Telegram token, Neon DB URL). Usar `git filter-repo` o BFG para limpiar historial. Usar Vault/1Password/GitHub Secrets en prod. |
| **Autenticación/Autorización** | Solo `chat_id` hardcodeado en `settings.mi_telegram_id` | ALTO | Implementar OAuth2/Telegram Login + JWT tokens + RBAC si multi-usuario |
| **Input Validation** | Solo `verificar_usuario` por chat_id | ALTO | Sanitizar TODOS los inputs (XSS, SQLi, command injection). Usar Pydantic validators. |
| **Secrets en Logs** | `logger.info` puede loguear tokens/queries | MEDIO | Sanitizar logs (no loguear `settings.groq_api_key`, `telegram_token`, DB URLs). Usar `structlog` con processors de sanitización. |
| **Dependencias** | `requirements.txt` sin pinning estricto + sin `pip-audit` | MEDIO | `pip-tools` + `pip-audit` en CI. `dependabot.yml` en GitHub. |
| **Rate Limiting** | Sin rate limiting en handlers | MEDIO | `aiolimiter` + middleware de rate limiting por usuario/IP. |
| **CORS/CSRF** | N/A (bot Telegram) | BAJO | N/A |
| **Encryption at Rest** | DB Neon (PostgreSQL) - TLS en tránsito OK, en reposo depende de Neon | BAJO | Verificar `sslmode=require` en connection string. |
| **Audit Logging** | Solo `structlog` básico | MEDIO | Audit trail inmutable (append-only) para acciones sensibles (borrar, reagendar, calendar sync). |

**Checklist de Hardening para Venta:**
- [ ] Rotar TODAS las credenciales y limpiar historial git
- [ ] Implementar OAuth2/Telegram Login para multi-usuario
- [ ] Sanitizar todos los inputs (Pydantic validators)
- [ ] Rate limiting por usuario (ej: 30 req/min)
- [ ] Audit logging inmutable (append-only table)
- [ ] Dependency scanning automatizado (Dependabot + pip-audit)
- [ ] Penetration testing básico (OWASP Top 10)
- [ ] Documentación de seguridad (SECURITY.md, threat model)

---

### 4. 🟡 MAYOR ENTENDIMIENTO DEL LENGUAJE NATURAL (tipo Eco-hogarbot)
**Prioridad: MEDIA-ALTA**

**Gap actual vs Eco-hogarbot:**
| Capacidad | Secretar-IA (Actual) | Eco-hogarbot (Referencia) | Gap |
|-----------|---------------------|---------------------------|-----|
| **Entidades complejas** | Solo fecha/hora, recurrencia básica | Entidades anidadas (monto+categoría+fecha+recurrencia+tags) | Extracción de entidades anidadas + validación semántica |
| **Contexto conversacional** | 10 mensajes history (solo user/intent) | Memoria semántica + estado de conversación multi-turno | Memoria a largo plazo + resolución de referencias (anáfora) |
| **Desambiguación** | Ninguna (primera interpretación gana) | Preguntas de clarificación activas | Preguntas de seguimiento ("¿A qué hora exacta?") |
| **Corrección/Feedback** | Solo `/deshacer` | Corrección incremental ("cambia X a Y") | Edición incremental de intención |
| **Conocimiento dominio** | Solo prompt hardcodeado | Base de conocimiento consultable (RAG) | RAG sobre docs del usuario (preferencias, contactos, rutinas) |
| **Proactividad** | Sugerencia simple (1 por resumen) | Múltiples sugerencias contextuales + timing óptimo | Motor de reglas + scoring de relevancia |

**Plan de Mejora (Roadmap):**

| Fase | Entregable | Esfuerzo | Valor |
|------|------------|----------|-------|
| **Fase 1: Entidades Ricas** | Extraer: monto+cat+fecha+recurrencia+tags en un solo mensaje | 2-3 semanas | Alto |
| **Fase 2: Memoria Conversacional** | Contexto multi-turno + resolución anáfora ("cambia ESO a las 5") | 3-4 semanas | Alto |
| **Fase 3: Clarificación Activa** | Bot pregunta si ambigüedad ("¿A qué hora exacta?") | 2-3 semanas | Alto |
| **Fase 4: Edición Incremental** | "Cambia la reunión a las 5" → actualiza solo hora | 3-4 semanas | Medio |
| **Fase 5: RAG Personal** | Preferencias/contactos/rutinas en vector DB (pgvector) | 4-6 semanas | Muy Alto |
| **Fase 6: Proactividad Inteligente** | Motor de reglas + scoring + timing óptimo | 4-6 semanas | Alto |

**Quick Wins (1-2 semanas):**
- [ ] Agregar patrón "mañana a las 9" (ya implementado en fix reciente)
- [ ] Soporte "el lunes que viene" / "próximo martes"
- [ ] Preguntar "¿A qué hora?" si falta hora en EVENTO
- [ ] Detectar "cambia X a Y" → REAGENDAR automático

---

## 📋 PLAN DE ACCIÓN PRIORIZADO

| Semana | Foco | Entregables |
|--------|------|-------------|
| **Semana 1** | Refactoring Crítico | Split `main.py` → handlers/jobs/services. Tests unitarios date_parser. |
| **Semana 2** | Testing Foundation | pytest + fixtures + CI/CD. 80% coverage unit. |
| **Semana 3** | Security Hardening | Rotate secrets, input validation, rate limiting, audit log. |
| **Semana 4** | NLU v2 - Entidades Ricas | Extracción múltiple + validación semántica. |
| **Semana 5-6** | Memoria Conversacional | Contexto multi-turno + anáfora + clarificación activa. |
| **Semana 7-8** | RAG Personal + Proactividad | pgvector + motor reglas + scoring. |
| **Semana 9-10** | Hardening + Docs | Pen-test, SECURITY.md, runbooks, deploy automático. |

---

## 📊 MÉTRICAS DE ÉXITO (KPIs)

| Métrica | Baseline | Target | Medición |
|---------|----------|--------|----------|
| **Precisión parsing fechas** | ~60% | >95% | Test suite 50+ casos |
| **Latencia P95 respuesta** | ~3s | <1.5s | APM (Render metrics) |
| **Tasa error no manejado** | ~5% | <0.1% | Sentry / logs |
| **Cobertura tests** | 0% | >80% | `pytest --cov` |
| **Tiempo deploy** | Manual ~10min | <3 min | GitHub Actions |
| **Tiempo fix bug crítico** | Horas | <30 min | Runbook + feature flags |
| **Uptime** | ~99% | 99.9% | UptimeRobot + health checks |

---

## 📁 ARCHIVOS CLAVE PARA REVISAR

```
secretar-ia/
├── main.py                    # Entry point - REFACTORIZAR URGENTE
├── application/services/
│   ├── ai_service.py          # Parsing fechas + clasificación (FIXED date parsing)
│   ├── calendar_service.py    # Calendar CRUD + sync
│   ├── summary_service.py     # Resúmenes matutino/vespertino
│   └── weekly_planning_service.py  # Plantillas + Objetivos + Revisión
├── infrastructure/database/
│   ├── repositories/
│   │   ├── task_repo.py       # CRUD + DAILY_TASKS + subtareas
│   │   ├── plantilla_repo.py  # CRUD plantillas
│   │   └── objetivo_repo.py   # CRUD objetivos + progreso
│   └── connection.py          # Pool asyncpg + init_db + migraciones
├── config/
│   ├── settings.py            # Pydantic Settings (secrets via env)
│   └── logging.py             # structlog config
└── scripts/
    └── setup_calendar.py      # OAuth flow local → guarda token en Neon
```

---

## 🚀 PRÓXIMOS PASOS INMEDIATOS (Esta semana)

1. [ ] **Refactor `main.py`** → Split en `handlers/`, `jobs/`, `services/`
2. [ ] **Setup pytest + CI/CD** → GitHub Actions + pytest-asyncio + coverage
3. [ ] **Security Audit Completo** → Rotar secrets, input validation, rate limiting
3. [ ] **Date Parser Tests** → 50+ casos de prueba para `_parse_relative_date`
3. [ ] **Verificar deploy Render** → Health check + logs + métricas
4. [ ] **Documentar API interna** → Docstrings + type hints completos

---

**Última actualización:** 2026-11-02
**Responsable:** Nicolás + IA Assistant
**Próxima revisión:** Deploy verificado + tests passing