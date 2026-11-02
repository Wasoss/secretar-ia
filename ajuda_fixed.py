async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ayuda - Guía de funções."""
    try:
        if not await verificar_usuario(update):
            return

        texto = (
            "🤖 <b>Guía de Secretar-IA</b>\n\n"
            "📅 <b>Eventos (Google Calendar):</b>\n\n"
            "  <i>\"Reunión el martes a las 15hs\"</i>\n"
            "  <i>\"Cita dentista el 20/01 a las 10:30\"</i>\n"
            "  <i>\"Clase yoga cada lunes a las 19hs\"</i> (recurrente)\n\n"
            "⏰ <b>Recordatorios (alarmas locales):</b>\n\n"
            "  <i>\"Recordame llamar a mamá a las 18hs\"</i>\n"
            "  <i>\"Avisame tomar pastillas cada 8hs\"</i> (recurrente)\n\n"
            "📔 <b>Notas (sin fecha):</b>\n\n"
            "  <i>\"Anotá la clave wifi es 1234\"</i>\n"
            "  <i>\"Idea: regalo para Ana - libro\"</i>\n\n"
            "☑️ <b>Tareas diarias (lista con sub-items):</b>\n\n"
            "  <i>\"Lista de hoy: estudiar lógica, preparar clases, limpiar\"</i>\n"
            "  → Se crea una lista con checkboxes para tachar individualmente\n\n"
            "🔧 <b>Gestión avanzada:</b>\n\n"
            "  <i>\"Cambia la reunión al miércoles 16hs\"</i> (reagendar)\n"
            "  <i>\"Borrar todo del 25 de octubre\"</i>\n"
            "  <i>\"Deshacer\"</i> (borra último)\n\n"
            "📋 <b>Comandos:</b>\n\n"
            "  /resumen — Resumen matutino (eventos hoy/mañana + tareas)\n"
            "  /pendientes — Ver tareas diarias con sub-items para tachar\n"
            "  /notas — Consultar notas guardadas\n"
            "  /hoy — Ver agenda de hoy\n"
            "  /semana — Ver agenda de la semana\n"
            "  /buscar <texto> — Buscar en notas/eventos\n"
            "  /tag <etiqueta> — Filtrar por tag\n"
            "  /ayuda — Esta guía\n"
            "  /test — Diagnóstico del sistema\n\n"
            "💡 <b>Tips:</b> Usá #tag para organizar. "
            "Palabras clave: <i>urgente</i> (prioridad alta), "
            "<i>no apura</i> (baja).\n"
            "Para lista diaria: decí <i>\"Lista de hoy: ...\"</i> o <i>\"Tareas de hoy: ...\"</i>"
        )
        if update.message:
            await update.message.reply_text(texto, parse_mode=ParseMode.HTML)
        else:
            logger.warning("ayuda_called_without_message")
    except Exception as e:
        logger.error("ayuda_error", error=str(e), exc_info=True)
        if update.message:
            await update.message.reply_text("⚠️ Error al mostrar la ayuda. Probá /test")
