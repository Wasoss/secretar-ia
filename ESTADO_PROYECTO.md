# Estado del Proyecto - Secretar-IA

**Última actualización:** 2026-11-02
**Commit actual:** a26c0cf (main)

---

## ✅ Cambios Realizados (Clean Architecture Refactor)

### 1. Rearquitectura Principal (main.py: 1,469 → 168 líneas)
- **main.py**: Punto de entrada limpio usando handlers modulares
- **infrastructure/di/container.py**: Contenedor DI que reemplaza 9 variables globales mutables
- **handlers/base.py**: BaseHandler con error handling, auth, utilities
- **utils/formatters.py**: Funciones de formateo compartidas (extraídas de main.py)

### 2. Handlers Modulares
```
handlers/
├── commands/
│   ├── basic.py        # start, ajuda, status, ping, test_sistema
│   ├── calendar.py     # calendar_status
│   ├── agenda.py       # ver_notas, ver_hoy, ver_semana, buscar, filtrar_tag, ver_pendientes
│   ├── templates.py    # ver_plantillas
│   └── objectives.py   # ver_objetivos, ver_revision
├── messages/
│   ├── text.py         # recibir_texto + procesar_peticion + intent handlers
│   └── audio.py        # recibir_audio
├── callbacks/
│   └── completion.py   # complete_, delete_, subtask_
├── jobs/
│   ├── daily.py        # resumen matutino, plantilla, recordatorio vespertino
│   ├── weekly.py       # revisión semanal
│   └── maintenance.py  # keep_alive_db
└── __init__.py         # Exports públicos
```

### 3. Documentación
- **ARCHITECTURE_FLOW.md**: Diagramas Mermaid (arquitectura, flujo mensajes, jobs, BD, IA)
- **IMPROVEMENTS.md**: 35+ mejoras priorizadas (Crítico → Bajo)
- **ESTADO_PROYECTO.md**: Este archivo

### 4. Fix: Parsing de fechas "El miércoles 3/11 a las 12hs" (2026-11-02)
- **ai_service.py**: Agregados ejemplos al prompt del sistema
- **ai_service.py**: Agregado patrón regex fallback para "El [día] DD/MM a las HH"

---

## 🔄 Pendiente / Por Hacer

### Prioridad Alta (Siguiente Sprint)
- [ ] **Tests unitarios** para handlers, use cases, servicios
- [ ] **Capa de Use Cases** para separar lógica de negocio de framework Telegram
- [ ] **Validación Pydantic** (DTOs) para inputs de handlers
- [ ] **Patrón Outbox** para sincronización Calendar resiliente

### Prioridad Media
- [ ] **Observabilidad**: métricas, tracing, health checks detallados
- [ ] **Internacionalización (i18n)** para strings user-facing
- [ ] **API Layer (FastAPI)** para dashboard web
- [ ] **Multi-user support** (actualmente single chat_id hardcoded)

### Prioridad Baja / Nice-to-Have
- [ ] Plugin system para ActionTypes extensibles
- [ ] Dashboard web con gráficos de objetivos
- [ ] Notificaciones push móviles nativas
- [ ] Backup/restauración automática de BD

---

## 🐛 Issues Conocidos

| Issue | Severidad | Estado |
|-------|-----------|--------|
| Sin tests de integración (requiere BD real) | Media | Pendiente |
| Manejo de errores Calendar no distingue todos los códigos HTTP | Baja | Pendiente |
| Conversation history en memoria (se pierde al restart) | Baja | Pendiente |
| No hay retry/backoff configurable para Groq API | Media | Pendiente |

---

## 📦 Dependencias Actuales

```txt
python-telegram-bot==22.8
asyncpg==0.32.0
groq==1.7.0
pydantic==2.14.2
pydantic-settings==2.16.2
google-api-python-client==2.201.0
google-auth-oauthlib==1.5.0
structlog==26.1.0
tenacity==9.2.1
python-dotenv==1.2.4
pytest==9.2.0
pytest-asyncio==1.4.1.post1
```

---

## 🚀 Para Desarrollar Localmente

```bash
# 1. Clonar e instalar
cd secretar-ia
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt

# 2. Configurar .env (ver .env.example)
cp .env.example .env
# Editar .env con tus tokens

# 3. OAuth Calendar (solo primera vez)
python -m scripts.setup_calendar

# 4. Ejecutar
python main.py
```

---

## 🌐 Deploy (Render)

- **Web Service**: `python main.py`
- **Health Check**: `GET /health` (puerto 10000)
- **Environment Variables**: Configurar en dashboard Render
- **Free Tier**: Keep-alive job cada 5 min evita spin-down

---

## 📝 Próximos Pasos Recomendados

1. **Crear tests**: `tests/unit/use_cases/test_create_event.py` con mocks
2. **Use Case Layer**: `application/use_cases/create_event.py`
3. **DTOs**: `application/dto.py` con Pydantic models
4. **CI/CD**: GitHub Actions para lint + test + deploy
5. **ADRs**: Documentar decisiones arquitectónicas en `docs/adr/`