"""
Text message handler - processes natural language requests.
"""
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from handlers.base import BaseHandler, handle_errors, require_auth
from application.services.ai_service import ActionType
from config.settings import settings
from config.logging import get_logger
from infrastructure.database.repositories.task_repo import TaskType
import datetime

logger = get_logger(__name__)


class TextMessageHandler(BaseHandler):
    """Handler for text messages using AI classification."""

    @handle_errors
    async def recibir_texto(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para mensajes de texto normales."""
        await self.procesar_peticion(update, context, update.message.text)

    async def procesar_peticion(self, update: Update, context: ContextTypes.DEFAULT_TYPE, texto_usuario: str):
        """Procesa el texto del usuario usando el servicio de IA enriquecido."""
        if not await require_auth(update):
            return

        chat_id = str(update.message.chat_id)

        # Shortcut: comandos de ayuda → mostrar ayuda directamente (antes de IA)
        texto_lower = texto_usuario.lower().strip()
        if texto_lower in ("lista de comandos", "comandos", "ayuda", "menu", "menú", "help"):
            logger.info("help_shortcut_triggered", text=texto_usuario)
            try:
                from handlers.commands.basic import ajuda
                await ajuda(update, context)
            except Exception as e:
                logger.error("help_shortcut_error", error=str(e), exc_info=True)
                if update.message:
                    await update.message.reply_text("⚠️ Error al mostrar la ayuda. Probá /test")
            return

        # Clasificar intención con IA
        services = await self.get_services()
        ai_service = services['ai_service']
        intent = await ai_service.classify_intent(texto_usuario)

        # Log para debugging
        logger.info("intent_received", action=intent.accion.value,
                   detalles=intent.detalles[:50], fecha=intent.fecha_hora,
                   recurrence=intent.recurrencia, tags=intent.tags)

        # Manejar según acción
        if intent.accion == ActionType.ERROR:
            await update.message.reply_text(f"⚠️ No entendí: {intent.detalles}")
            return

        if intent.accion == ActionType.RECHAZADO_GASTOS:
            await update.message.reply_text(f"No gestiono finanzas. Registrá esto en tu otro bot: {intent.detalles}")
            return

        if intent.accion == ActionType.CONVERSACION:
            await update.message.reply_text(intent.detalles)
            return

        if intent.accion == ActionType.AYUDA:
            from handlers.commands.basic import ajuda
            await ajuda(update, context)
            return

        # Dispatch to specific handlers
        handler_map = {
            ActionType.DESHACER: self.handle_deshacer,
            ActionType.ELIMINAR_FECHA: self.handle_eliminar_fecha,
            ActionType.REAGENDAR: self.handle_reagendar,
            ActionType.LISTAR: self.handle_listar,
            ActionType.BUSCAR: self.handle_buscar,
            ActionType.TAREA_DIARIA: self.handle_guardar_tarea_diaria,
            ActionType.PLANTILLA_CREAR: self.handle_crear_plantilla,
            ActionType.PLANTILLA_LISTAR: self.handle_listar_plantillas,
            ActionType.PLANTILLA_ACTIVAR: self.handle_activar_plantilla,
            ActionType.OBJETIVO_CREAR: self.handle_crear_objetivo,
            ActionType.OBJETIVO_LISTAR: self.handle_listar_objetivos,
            ActionType.OBJETIVO_PROGRESO: self.handle_progreso_objetivo,
            ActionType.REVISION_SEMANAL: self.handle_revision_semanal,
        }

        handler = handler_map.get(intent.accion)
        if handler:
            await handler(update, context, chat_id, intent)
        else:
            # Acciones que guardan en BD: EVENTO, RECORDATORIO, NOTA
            await self.handle_guardar_tarea(update, context, chat_id, intent)

    # --- Specific intent handlers ---

    async def handle_guardar_tarea(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                   chat_id: str, intent):
        """Guarda EVENTO, RECORDATORIO o NOTA en BD y Calendar si aplica."""
        from utils.formatters import build_confirmation_message, formatear_datetime
        import datetime

        services = await self.get_services()
        task_repo = services['task_repo']
        calendar_service = services['calendar_service']
        reminder_service = services['reminder_service']

        # Validación: EVENTO requiere fecha/hora
        if intent.accion == ActionType.EVENTO and not intent.fecha_hora:
            await update.message.reply_text(
                "📅 <b>Evento sin fecha/hora</b>\n\n"
                "Para agendar en Calendar necesitás día y hora.\n"
                "Probá: <i>\"mañana 9hs reunión con Juan\"</i> o <i>\"el 25/12 a las 10hs cita\"</i>",
                parse_mode=ParseMode.HTML
            )
            return

        calendar_event_id = None
        calendar_warning = ""

        # Guardar SIEMPRE en BD primero (garantiza persistencia local)
        from infrastructure.database.repositories.task_repo import TaskType, TaskStatus

        task_id = await task_repo.save(
            telefono_id=chat_id,
            tipo=TaskType(intent.accion.value),
            detalles=intent.detalles,
            fecha_hora=intent.fecha_hora,
            recurrencia=intent.recurrencia,
            prioridad=intent.prioridad,
            tags=intent.tags,
            calendar_event_id=None,  # Se actualiza después si sincroniza
        )

        # Si es EVENTO, intentar sincronizar con Google Calendar
        if intent.accion == ActionType.EVENTO and intent.fecha_hora:
            start_dt = intent.fecha_hora
            end_dt = start_dt + datetime.timedelta(hours=1)

            # Verificar conflictos (solo avisar, no bloquear)
            conflicts = await calendar_service.check_conflicts(start_dt, end_dt)
            if conflicts:
                conflict_names = [c.get('summary', 'Sin título') for c in conflicts[:3]]
                calendar_warning = f"\n⚠️ <b>Conflicto en Calendar</b>: {', '.join(conflict_names)}"

            # Intentar crear en Calendar
            try:
                created_event = await calendar_service.create_event(
                    summary=intent.detalles,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    recurrence=intent.recurrencia,
                )
                if created_event:
                    calendar_event_id = created_event.get('id')
                    # Actualizar BD con calendar_event_id
                    await task_repo.update_task(task_id, calendar_event_id=calendar_event_id)
                    logger.info("calendar_event_synced", local_action="EVENTO",
                               calendar_event_id=calendar_event_id, task_id=task_id)
                else:
                    calendar_warning += "\n⚠️ No se pudo sincronizar con Google Calendar (¿token expirado?)."
            except Exception as e:
                logger.error("calendar_sync_failed", error=str(e), task_id=task_id)
                # Mostrar error específico al usuario
                error_msg = str(e)
                if "credenciales" in error_msg.lower() or "token" in error_msg.lower() or "oauth" in error_msg.lower():
                    calendar_warning += "\n⚠️ <b>Sin token OAuth válido</b> - Usá <code>/calendar_status</code> para detalles"
                elif "conflict" in error_msg.lower():
                    calendar_warning += "\n⚠️ Conflicto en Calendar"
                else:
                    calendar_warning += f"\n⚠️ Error Calendar: <code>{error_msg[:80]}</code>"

        # Respuesta al usuario
        respuesta = build_confirmation_message(
            intent.accion, intent.detalles, task_id,
            intent.fecha_hora, intent.recurrencia, intent.prioridad,
            intent.tags, calendar_event_id
        )
        if calendar_warning:
            respuesta += calendar_warning

        # Programar recordatorio si es RECORDATORIO
        if intent.accion == ActionType.RECORDATORIO and intent.fecha_hora:
            success = await reminder_service.schedule_reminder(
                context.job_queue,
                int(chat_id),
                intent.detalles,
                intent.fecha_hora,
            )
            if success:
                respuesta += " ⏰ Alarma programada."
            else:
                respuesta += " ⚠️ No se pudo programar la alarma (¿fecha pasada?)."

        await update.message.reply_text(respuesta, parse_mode=ParseMode.HTML)

    async def handle_guardar_tarea_diaria(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                           chat_id: str, intent):
        """Guarda una TAREA_DIARIA con sub-items en BD."""
        import uuid
        import re
        from infrastructure.database.repositories.task_repo import TaskType, TaskStatus, SubTask
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        services = await self.get_services()
        task_repo = services['task_repo']

        # Parsear los sub-items del texto (separados por comas, "y", saltos de línea)
        texto = intent.detalles
        # Separadores comunes: coma, "y", salto de línea, punto y coma
        items = re.split(r'[,;\n]|\s+y\s+', texto)
        items = [item.strip() for item in items if item.strip()]

        if not items:
            await update.message.reply_text("❌ No pude identificar los items de la lista. Probá: \"Lista de hoy: estudiar, preparar clases, limpiar\"")
            return

        # Crear sub-items con IDs únicos
        subtareas = []
        for i, item in enumerate(items):
            subtareas.append(SubTask(
                id=str(uuid.uuid4())[:8],  # ID corto
                texto=item,
                completado=False,
                orden=i
            ))

        # Guardar en BD como TAREA_DIARIA
        task_id = await task_repo.save(
            telefono_id=chat_id,
            tipo=TaskType.TAREA_DIARIA,
            detalles=texto,  # Título de la lista
            fecha_hora=None,  # Sin fecha específica, es para hoy
            estado=TaskStatus.PENDIENTE,
            prioridad=intent.prioridad,
            tags=intent.tags,
            subtareas=subtareas,
        )

        # Respuesta con botones para tachar
        mensaje = f"☑️ <b>Lista diaria creada</b> (ID: {task_id})\n"
        mensaje += f"📝 {texto}\n\n"

        botones = []
        for sub in subtareas:
            botones.append([
                InlineKeyboardButton(
                    f"☑️ {sub.texto[:35]}",
                    callback_data=f"subtask_{task_id}_{sub.id}"
                )
            ])
            mensaje += f"  ☐ {sub.texto}\n"

        mensaje += f"\n📋 Total: {len(subtareas)} items"
        if intent.prioridad == 1:
            mensaje += " 🔴"
        elif intent.prioridad == -1:
            mensaje += " 🟢"
        if intent.tags:
            mensaje += f" #{' #'.join(intent.tags)}"

        teclado = InlineKeyboardMarkup(botones)
        await update.message.reply_text(mensaje, reply_markup=teclado, parse_mode=ParseMode.HTML)

    # ============================================================
    # NUEVOS HANDLERS: Plantillas, Objetivos, Revisión Semanal
    # ============================================================

    async def handle_crear_plantilla(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                      chat_id: str, intent):
        """Crea una plantilla diaria reutilizable desde texto libre."""
        services = await self.get_services()
        weekly_planning_service = services['weekly_planning_service']
        plantilla_repo = services['plantilla_repo']

        try:
            if weekly_planning_service is None or plantilla_repo is None:
                logger.error("handle_crear_plantilla: services not initialized")
                await update.message.reply_text("❌ Servicio no disponible. Reintentá en unos segundos.")
                return
            # Usar primer tag como nombre, o generar uno automático
            nombre = intent.tags[0] if intent.tags else None
            plantilla_id = await weekly_planning_service.create_plantilla_from_text(
                telefono_id=chat_id,
                texto=intent.detalles,
                nombre=nombre,
            )
            await update.message.reply_text(
                f"📋 <b>Plantilla creada</b> (ID: {plantilla_id})\n"
                f"📝 Items: {intent.detalles}\n"
                f"✅ Ahora se aplicará cada mañana a las 6:30 AM",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error("handle_crear_plantilla_error", error=str(e), exc_info=True)
            await update.message.reply_text("❌ Error al crear plantilla. Reintentá en unos segundos.")

    async def handle_listar_plantillas(self, update: Update, chat_id: str, intent):
        """Lista todas las plantillas del usuario."""
        services = await self.get_services()
        plantilla_repo = services['plantilla_repo']

        try:
            if plantilla_repo is None:
                logger.error("handle_listar_plantillas: plantilla_repo is None")
                await update.message.reply_text("❌ Servicio no disponible. Reintentá en unos segundos.")
                return
            plantillas = await plantilla_repo.get_all(chat_id)

            if not plantillas:
                await update.message.reply_text(
                    "📋 No tenés plantillas guardadas.\n"
                    "Crea una diciendo: <i>\"Plantilla: cada día estudiar 2h, ejercicio\"</i>",
                    parse_mode=ParseMode.HTML
                )
                return

            mensaje = "📋 <b>Tus plantillas:</b>\n\n"
            for p in plantillas:
                activa = " ✅ <b>ACTIVA</b>" if p.activa else ""
                items_preview = ", ".join([item.get("texto", "")[:30] for item in p.items[:3]])
                if len(p.items) > 3:
                    items_preview += f" ... y {len(p.items) - 3} más"
                mensaje += f"▷ <b>{p.nombre}</b>{activa}\n  {items_preview}\n"

            await update.message.reply_text(mensaje, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error("handle_listar_plantillas_error", error=str(e), exc_info=True)
            await update.message.reply_text("❌ Error al obtener plantillas. Reintentá en unos segundos.")

    async def handle_activar_plantilla(self, update: Update, chat_id: str, intent):
        """Activa una plantilla por nombre."""
        services = await self.get_services()
        plantilla_repo = services['plantilla_repo']

        try:
            if plantilla_repo is None:
                logger.error("handle_activar_plantilla: plantilla_repo is None")
                await update.message.reply_text("❌ Servicio no disponible. Reintentá en unos segundos.")
                return
            nombre = intent.detalles.strip()
            plantillas = await plantilla_repo.get_all(chat_id)

            # Buscar por nombre (parcial, case-insensitive)
            plantilla = None
            for p in plantillas:
                if nombre.lower() in p.nombre.lower():
                    plantilla = p
                    break

            if not plantilla:
                await update.message.reply_text(f"❌ No encontré plantilla: \"{nombre}\". Usá /plantillas para verlas.")
                return

            await plantilla_repo.set_active(chat_id, plantilla.id)
            await update.message.reply_text(
                f"✅ Plantilla activada: <b>{plantilla.nombre}</b>\n"
                f"Se aplicará mañana a las 6:30 AM",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error("handle_activar_plantilla_error", error=str(e), exc_info=True)
            await update.message.reply_text("❌ Error al activar plantilla. Reintentá en unos segundos.")

    async def handle_crear_objetivo(self, update: Update, chat_id: str, intent):
        """Crea un objetivo semanal."""
        services = await self.get_services()
        weekly_planning_service = services['weekly_planning_service']
        objetivo_repo = services['objetivo_repo']

        try:
            if weekly_planning_service is None or objetivo_repo is None:
                logger.error("handle_crear_objetivo: services not initialized")
                await update.message.reply_text("❌ Servicio no disponible. Reintentá en unos segundos.")
                return

            # Usar valores parseados por la IA si vienen, si no parsear del texto
            if intent.objetivo_valor is not None and intent.objetivo_unidad:
                valor = intent.objetivo_valor
                unidad = intent.objetivo_unidad
            else:
                # Fallback: parsear del texto
                import re
                texto = intent.detalles
                match = re.search(r'(\d+(?:\.\d+)?)\s*(h|hrs?|horas?|veces?|libros?|km|paginas?|minutos?)', texto, re.IGNORECASE)
                if match:
                    valor = float(match.group(1))
                    unidad = match.group(2).lower()
                else:
                    valor = 1
                    unidad = "veces"

            objetivo_id = await weekly_planning_service.create_objetivo(
                telefono_id=chat_id,
                descripcion=intent.detalles,
                objetivo_valor=valor,
                objetivo_unidad=unidad,
            )

            await update.message.reply_text(
                f"🎯 <b>Objetivo creado</b> (ID: {objetivo_id})\n"
                f"📝 {intent.detalles}\n"
                f"📊 Meta: {valor} {unidad}/semana\n"
                f"📅 Para la semana actual",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error("handle_crear_objetivo_error", error=str(e), exc_info=True)
            await update.message.reply_text("❌ Error al crear objetivo. Reintentá en unos segundos.")

    async def handle_listar_objetivos(self, update: Update, chat_id: str, intent):
        """Lista objetivos de la semana actual."""
        services = await self.get_services()
        objetivo_repo = services['objetivo_repo']

        try:
            if objetivo_repo is None:
                logger.error("handle_listar_objetivos: objetivo_repo is None")
                await update.message.reply_text("❌ Servicio no disponible. Reintentá en unos segundos.")
                return
            objetivos = await objetivo_repo.get_active(chat_id)

            if not objetivos:
                await update.message.reply_text(
                    "🎯 No tenés objetivos para esta semana.\n"
                    "Crea uno: <i>\"Meta: estudiar 10h/semana\"</i>",
                    parse_mode=ParseMode.HTML
                )
                return

            mensaje = "🎯 <b>Objetivos de esta semana:</b>\n\n"
            for obj in objetivos:
                emoji = obj.estado_emoji()
                mensaje += f"{emoji} <b>{obj.descripcion}</b>\n"
                mensaje += f"   Progreso: {obj.formatear_progreso()} ({obj.porcentaje:.1f}%)\n\n"

            await update.message.reply_text(mensaje, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error("handle_listar_objetivos_error", error=str(e), exc_info=True)
            await update.message.reply_text("❌ Error al obtener objetivos. Reintentá en unos segundos.")

    async def handle_progreso_objetivo(self, update: Update, chat_id: str, intent):
        """Actualiza progreso de un objetivo."""
        services = await self.get_services()
        objetivo_repo = services['objetivo_repo']

        try:
            if objetivo_repo is None:
                logger.error("handle_progreso_objetivo: objetivo_repo is None")
                await update.message.reply_text("❌ Servicio no disponible. Reintentá en unos segundos.")
                return
            # Buscar objetivo por descripción
            objetivos = await objetivo_repo.get_active(chat_id)

            obj = None
            for o in objetivos:
                if intent.detalles.lower() in o.descripcion.lower() or o.descripcion.lower() in intent.detalles.lower():
                    obj = o
                    break

            if not obj:
                await update.message.reply_text("❌ No encontré ese objetivo. Usá /objetivos para verlos.")
                return

            # Usar valor parseado por la IA si viene, si no parsear del texto
            if intent.objetivo_valor is not None:
                incremento = intent.objetivo_valor
            else:
                import re
                match = re.search(r'(\d+(?:\.\d+)?)', intent.detalles)
                if not match:
                    await update.message.reply_text("❌ No pude identificar el progreso. Probá: \"Avancé 2h en estudio\"")
                    return
                incremento = float(match.group(1))

            await objetivo_repo.update_progress(obj.id, incremento)

            # Obtener objetivo actualizado
            obj_actualizado = await objetivo_repo.get_by_id(obj.id)

            await update.message.reply_text(
                f"📈 <b>Progreso actualizado</b>\n"
                f"📝 {obj_actualizado.descripcion}\n"
                f"📊 Progreso: {obj_actualizado.formatear_progreso()} ({obj_actualizado.porcentaje:.1f}%)\n"
                + ("✅ ¡Objetivo completado!" if obj_actualizado.completado else ""),
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error("handle_progreso_objetivo_error", error=str(e), exc_info=True)
            await update.message.reply_text("❌ Error al actualizar progreso. Reintentá en unos segundos.")

    async def handle_revision_semanal(self, update: Update, chat_id: str):
        """Genera y envía revisión semanal."""
        services = await self.get_services()
        weekly_planning_service = services['weekly_planning_service']

        try:
            if weekly_planning_service is None:
                logger.error("handle_revision_semanal: weekly_planning_service is None")
                await update.message.reply_text("❌ Servicio no disponible. Reintentá en unos segundos.")
                return
            await weekly_planning_service.send_weekly_review(
                bot=update._bot,
                chat_id=chat_id
            )
        except Exception as e:
            logger.error("handle_revision_semanal_error", error=str(e), exc_info=True)
            await update.message.reply_text("❌ Error al generar revisión. Reintentá en unos segundos.")

    async def handle_deshacer(self, update: Update, chat_id: str):
        """Maneja DESHACER - borra última tarea."""
        services = await self.get_services()
        task_repo = services['task_repo']
        calendar_service = services['calendar_service']

        ultima = await task_repo.get_last_task(chat_id)
        if not ultima:
            await update.message.reply_text("No encontré ningún registro reciente para deshacer.")
            return

        # Si tenía calendar_event_id, borrar de Calendar también
        if ultima.calendar_event_id:
            await calendar_service.delete_event(ultima.calendar_event_id)

        await task_repo.delete_by_id(ultima.id)

        mensaje = f"🗑️ Se deshizo tu última carga: [{ultima.tipo.value}] {ultima.detalles}"
        if ultima.tipo == TaskType.EVENTO and ultima.calendar_event_id:
            mensaje += "\n✅ También se eliminó de Google Calendar."
        await update.message.reply_text(mensaje)

    async def handle_eliminar_fecha(self, update: Update, chat_id: str, fecha_hora):
        """Maneja ELIMINAR_FECHA - borra todo de un día."""
        if not fecha_hora:
            await update.message.reply_text("No pude identificar qué fecha querés borrar. Probá: 'Borrar todo el 25 de octubre'.")
            return

        fecha_str = fecha_hora.strftime("%Y-%m-%d")

        services = await self.get_services()
        task_repo = services['task_repo']

        # Borrar de BD
        borrados = await task_repo.delete_by_date(chat_id, fecha_str)

        # TODO: Borrar de Calendar también (requiere buscar eventos de ese día)

        await update.message.reply_text(f"🗑️ Se eliminaron {borrados} registros programados para el {fecha_str}.")

    async def handle_reagendar(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                              chat_id: str, intent):
        """Maneja REAGENDAR - cambia fecha/hora de tarea existente."""
        if not intent.fecha_hora:
            await update.message.reply_text("No pude identificar la nueva fecha/hora. Probá: 'Cambia la reunión al miércoles a las 15hs'.")
            return

        services = await self.get_services()
        task_repo = services['task_repo']
        calendar_service = services['calendar_service']
        reminder_service = services['reminder_service']

        from infrastructure.database.repositories.task_repo import TaskType

        # Buscar tarea a reagendar
        task = None
        if intent.tarea_original_id:
            task = await task_repo.get_task_by_id(intent.tarea_original_id)
        else:
            # Buscar por similitud en últimas tareas
            pendientes = await task_repo.get_pending(chat_id)
            for t in pendientes:
                if intent.detalles.lower() in t.detalles.lower() or t.detalles.lower() in intent.detalles.lower():
                    task = t
                    break

        if not task:
            await update.message.reply_text("No encontré la tarea a reagendar. Probá siendo más específico o usá /resumen para ver IDs.")
            return

        # Si es EVENTO, actualizar en Calendar
        old_calendar_id = task.calendar_event_id
        new_calendar_id = None

        if task.tipo == TaskType.EVENTO:
            start_dt = intent.fecha_hora
            end_dt = start_dt + datetime.timedelta(hours=1)

            # Verificar conflictos (excluyendo el propio evento)
            conflicts = await calendar_service.check_conflicts(start_dt, end_dt, exclude_event_id=old_calendar_id)
            if conflicts:
                conflict_names = [c.get('summary', 'Sin título') for c in conflicts[:3]]
                await update.message.reply_text(
                    f"⚠️ Conflicto en nuevo horario: {', '.join(conflict_names)}",
                    parse_mode=ParseMode.HTML
                )
                return

            if old_calendar_id:
                updated = await calendar_service.update_event(
                    event_id=old_calendar_id,
                    summary=task.detalles,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    recurrence=intent.recurrencia,
                )
                if updated:
                    new_calendar_id = old_calendar_id
            else:
                # No tenía ID, crear nuevo
                created = await calendar_service.create_event(
                    summary=task.detalles,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    recurrence=intent.recurrencia,
                )
                if created:
                    new_calendar_id = created.get('id')

        # Actualizar en BD
        await task_repo.update_task(
            task_id=task.id,
            fecha_hora=intent.fecha_hora,
            recurrencia=intent.recurrencia,
            calendar_event_id=new_calendar_id,
        )

        # Reprogramar recordatorio si era RECORDATORIO
        if task.tipo == TaskType.RECORDATORIO:
            await reminder_service.cancel_reminders(context.job_queue, int(chat_id))
            if intent.fecha_hora:
                await reminder_service.schedule_reminder(
                    context.job_queue, int(chat_id), task.detalles, intent.fecha_hora
                )

        from utils.formatters import formatear_datetime
        await update.message.reply_text(
            f"🔄 <b>Reagendado:</b> {task.detalles}\n"
            f"📅 Nuevo: {formatear_datetime(intent.fecha_hora)}"
            + (f"\n🔄 Recurrencia: {intent.recurrencia}" if intent.recurrencia else "")
            + ("\n☁️ Sincronizado con Calendar" if new_calendar_id else ""),
            parse_mode=ParseMode.HTML
        )

    async def handle_listar(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                           chat_id: str, intent):
        """Maneja LISTAR - muestra agenda según fecha_hora (hoy, semana, etc)."""
        import datetime
        from utils.formatters import _event_in_range

        services = await self.get_services()
        task_repo = services['task_repo']
        calendar_service = services['calendar_service']
        summary_service = services['summary_service']

        if intent.fecha_hora:
            # Usar fecha como referencia
            ref_date = intent.fecha_hora.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            ref_date = datetime.datetime.now(settings.tz).replace(hour=0, minute=0, second=0, microsecond=0)

        # Determinar rango según detalles
        detalles_lower = intent.detalles.lower()
        if "semana" in detalles_lower or "7 día" in detalles_lower:
            end_date = ref_date + datetime.timedelta(days=7)
            title = "📅 Agenda de la Semana"
        else:
            end_date = ref_date + datetime.timedelta(days=1)
            title = "📅 Agenda del Día"

        tasks = await task_repo.get_tasks_by_date_range(chat_id, ref_date, end_date)
        events = await calendar_service.get_upcoming_events(max_results=20, time_min=ref_date)
        events_filtrados = [e for e in events if _event_in_range(e, ref_date, end_date)]

        await summary_service.send_custom_summary(
            context.bot, chat_id, tasks, events_filtrados, title
        )

    async def handle_buscar(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                           chat_id: str, intent):
        """Maneja BUSCAR - busca en tareas y notas."""
        services = await self.get_services()
        task_repo = services['task_repo']
        calendar_service = services['calendar_service']
        summary_service = services['summary_service']

        query = intent.detalles
        tasks = await task_repo.search_tasks(chat_id, query)
        events = await calendar_service.get_upcoming_events(max_results=50)
        events_filtrados = [e for e in events if query.lower() in e.get('summary', '').lower()]

        await summary_service.send_custom_summary(
            context.bot, chat_id, tasks, events_filtrados, f"🔍 Resultados: '{query}'"
        )


# Instance for easy import
text_handler = TextMessageHandler()
recibir_texto = text_handler.recibir_texto