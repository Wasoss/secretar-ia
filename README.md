# Secretar-IA 🤖

> **Asistente personal inteligente para Telegram** — Gestión de agenda, recordatorios, notas y objetivos con IA conversacional.

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Telegram Bot](https://img.shields.io/badge/Telegram%20Bot-v21-blue.svg)
![Groq AI](https://img.shields.io/badge/Groq-AI-green.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-blue.svg)
![Render](https://img.shields.io/badge/Deploy-Render-purple.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

---

## 📋 Descripción

**Secretar-IA** es un asistente personal inteligente para Telegram que entiende lenguaje natural complejo y gestiona tu vida diaria: agenda, recordatorios, notas, tareas, objetivos semanales y revisiones semanales. Diseñado para ser **ligero, privado y proactivo**.

### ✨ Características Principales

| Categoría | Funcionalidades |
|-----------|-----------------|
| 📅 **Agenda & Calendar** | Eventos únicos/recurrentes, sincronización bidireccional con Google Calendar, detección de conflictos |
| ⏰ **Recordatorios** | Alarmas locales, recurrentes (diarias, semanales, mensuales, días hábiles), zonas horarias |
| 📝 **Notas** | Guardado sin fecha, búsqueda por palabras clave, tags |
| ☑️ **Tareas Diarias** | Listas con sub-items checkables, plantillas reutilizables, aplicación automática 6:30 AM |
| 🎯 **Objetivos Semanales** | Metas medibles (horas, veces, libros, km), seguimiento de progreso, % cumplimiento |
| 📊 **Revisiones Semanales** | Resumen automático domingos 10:00 AM: tareas completadas/pendientes, eventos, objetivos cumplidos |
| 🔊 **Audio** | Transcripción de notas de voz (Whisper v3) |
| 🧠 **IA Conversacional** | Groq (Qwen 2.5 32B) + Whisper v3, clasificación de intenciones, parsing de fechas relativas, RRULE, contexto conversacional |

---

## 🏗️ Arquitectura

```
secretar-ia/
├── main.py                 # Entry point, handlers, health check server
├── config/
│   ├── settings.py         # Configuración validada con Pydantic
│   └── logging.py          # Structlog JSON estructurado
├── application/
