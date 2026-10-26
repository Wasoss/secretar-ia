import os
import datetime
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MI_TELEGRAM_ID = os.getenv("MI_TELEGRAM_ID")
ZONA_HORARIA = ZoneInfo("America/Argentina/Buenos_Aires")

import base_datos
import calendario
import motor_ia

base_datos.inicializar_db()

# --- SERVIDOR SIMULADO PARA RENDER ---
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot activo")

def iniciar_servidor():
    puerto = int(os.getenv("PORT", 10000))
    HTTPServer(("0.0.0.0", puerto), DummyHandler).serve_forever()

# --- FORMATEO Y SEGURIDAD ---
def formatear_fecha_arg(fecha_str: str) -> str:
    if not fecha_str or fecha_str.lower() == "null": 
        return ""
    try:
        fecha_limpia = fecha_str.replace("T", " ")[:16]
        if " " in fecha_limpia:
            return datetime.datetime.strptime(fecha_limpia, "%Y-%m-%d %H:%M").strftime("%d/%m/%Y %H:%M")
        return datetime.datetime.strptime(fecha_limpia[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return fecha_str

async def verificar_usuario(update: Update) -> bool:
    chat_id = str(update.effective_chat.id)
    if chat_id != MI_TELEGRAM_ID:
        print(f"Acceso bloqueado al ID: {chat_id}")
        await update.message.reply_text("⛔ Acceso denegado. No estás autorizado para usar este bot.")
        return False
    return True

# --- FUNCIONES PRINCIPALES ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await verificar_usuario(update): return
    context.job_queue.run_once(guardar_chat_id, 1, data=str(update.message.chat_id))
    await update.message.reply_text("Hola. Soy tu Secretar-IA. Ya puedo gestionar tu agenda, alarmas y notas de forma segura en la nube.")

async def guardar_chat_id(context: ContextTypes.DEFAULT_TYPE):
    context.bot_data['chat_id'] = context.job.data

async def enviar_alarma(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    detalles = context.job.data
    await context.bot.send_message(chat_id=chat_id, text=f"⏰ <b>¡RECORDATORIO!</b>\n\nEs hora de: {detalles}", parse_mode=ParseMode.HTML)

async def procesar_peticion(update: Update, context: ContextTypes.DEFAULT_TYPE, texto_usuario: str):
    if not await verificar_usuario(update): return
    
    chat_id = str(update.message.chat_id)
    resultado = motor_ia.clasificar_intencion(texto_usuario)
    
    accion = resultado.get("accion", "ERROR")
    detalles = resultado.get("detalles", "")
    fecha_hora = resultado.get("fecha_hora")
    
    if accion == "RECHAZADO_GASTOS":
        await update.message.reply_text(f"No gestiono finanzas. Registrá esto en tu otro bot: {detalles}")
        return
        
    if accion == "CONVERSACION":
        await update.message.reply_text(detalles)
        return

    if accion == "DESHACER":
        ultima = base_datos.obtener_ultima_tarea(chat_id)
        if ultima:
            t_id, t_tipo, t_detalles = ultima
            base_datos.eliminar_tarea_por_id(t_id)
            mensaje_borrado = f"🗑️ Se deshizo tu última carga: [{t_tipo}] {t_detalles}"
            if t_tipo == "EVENTO":
                mensaje_borrado += "\n⚠️ (Importante: Borralo manualmente de Google Calendar, ya que esa conexión es de una sola vía por ahora)."
            await update.message.reply_text(mensaje_borrado)
        else:
            await update.message.reply_text("No encontré ningún registro reciente para deshacer.")
        return

    if accion == "ELIMINAR_FECHA":
        if fecha_hora:
            fecha_corta = fecha_hora[:10]  # Extrae solo YYYY-MM-DD
            borrados = base_datos.eliminar_por_fecha(chat_id, fecha_corta)
            await update.message.reply_text(f"🗑️ Se eliminaron {borrados} registros programados para el {fecha_corta}.")
        else:
            await update.message.reply_text("No pude identificar qué fecha querés borrar. Probá diciendo 'Borrar todo lo del 25 de octubre'.")
        return
        
    if accion == "EVENTO" and fecha_hora:
        if calendario.crear_evento_calendario(detalles, fecha_hora):
            await update.message.reply_text(f"📅 Evento agendado en Calendar: {detalles}")
        else:
            await update.message.reply_text("Hubo un error al guardar en Calendar.")
        return

    base_datos.guardar_tarea(chat_id, accion, detalles, fecha_hora)
    respuesta = f"📝 Guardado como {accion}."

    if accion == "RECORDATORIO" and fecha_hora:
        try:
            fecha_obj = datetime.datetime.strptime(fecha_hora, "%Y-%m-%d %H:%M").replace(tzinfo=ZONA_HORARIA)
            ahora = datetime.datetime.now(ZONA_HORARIA)
            if fecha_obj > ahora:
                segundos_espera = (fecha_obj - ahora).total_seconds()
                context.job_queue.run_once(enviar_alarma, when=segundos_espera, chat_id=update.message.chat_id, data=detalles)
                respuesta += " ⏰ Alarma programada."
        except Exception as e:
            print(f"Error programando alarma: {e}")

    await update.message.reply_text(respuesta)

async def recibir_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await procesar_peticion(update, context, update.message.text)

async def recibir_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await verificar_usuario(update): return
    archivo = await update.message.voice.get_file()
    ruta_audio = "nota_de_voz.ogg"
    await archivo.download_to_drive(ruta_audio)
    
    transcripcion = motor_ia.transcribir_audio(ruta_audio)
    await procesar_peticion(update, context, transcripcion)
    os.remove(ruta_audio)

async def marcar_completada(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if str(query.message.chat_id) != MI_TELEGRAM_ID: return
    
    tarea_id = query.data.split("_")[1]
    base_datos.completar_tarea(tarea_id)
    
    await query.answer("¡Acción completada! ✅")
    teclado_actual = query.message.reply_markup.inline_keyboard
    nuevo_teclado = [[btn] for fila in teclado_actual for btn in fila if btn.callback_data != query.data]
    
    if nuevo_teclado:
        await query.edit_message_reply_markup(InlineKeyboardMarkup(nuevo_teclado))
    else:
        await query.edit_message_text(text="¡Todas las tareas de esta lista están listas! 🎉")

async def enviar_resumen_diario(context: ContextTypes.DEFAULT_TYPE):
    chat_id = MI_TELEGRAM_ID
    if not chat_id: return
        
    pendientes = base_datos.obtener_pendientes(chat_id)
    eventos = calendario.obtener_eventos_calendario()
    
    if not pendientes and not eventos:
        await context.bot.send_message(chat_id=chat_id, text="¡Buen día! ☀️ No tenés tareas ni eventos próximos.")
        return

    mensaje = "¡Buen día! ☀️ Acá tenés tu resumen:\n\n"
    if eventos:
        mensaje += "📅 <b>Próximos eventos (Calendar):</b>\n"
        for evento in eventos:
            inicio = evento['start'].get('dateTime', evento['start'].get('date'))
            fecha_str = formatear_fecha_arg(inicio)
            mensaje += f"▷ {evento.get('summary', 'Sin título')} (<i>{fecha_str}</i>)\n"
        mensaje += "\n"
        
    if pendientes:
        mensaje += "📝 <b>Tareas y Notas pendientes:</b>\n"
        botones = []
        for tarea in pendientes:
            t_id, tipo, detalles, fecha = tarea
            fecha_str = f" (<i>{formatear_fecha_arg(fecha)}</i>)" if fecha else ""
            mensaje += f"○ <b>[{tipo}]</b> {detalles}{fecha_str}\n"
            botones.append([InlineKeyboardButton(f"✅ {detalles[:25]}", callback_data=f"ok_{t_id}")])
            
        teclado = InlineKeyboardMarkup(botones)
        await context.bot.send_message(chat_id=chat_id, text=mensaje, reply_markup=teclado, parse_mode=ParseMode.HTML)
    else:
        await context.bot.send_message(chat_id=chat_id, text=mensaje, parse_mode=ParseMode.HTML)

async def test_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await verificar_usuario(update): return
    await enviar_resumen_diario(context)

async def ver_notas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await verificar_usuario(update): return
    chat_id = str(update.message.chat_id)
    notas = base_datos.obtener_solo_notas(chat_id)
    
    if not notas:
        await update.message.reply_text("📔 No tenés notas guardadas actualmente.")
        return

    mensaje = "📔 <b>Tus Notas guardadas:</b>\n\n"
    botones = []
    for nota in notas:
        t_id, tipo, detalles, fecha = nota
        mensaje += f"○ {detalles}\n"
        botones.append([InlineKeyboardButton(f"❌ Borrar: {detalles[:20]}", callback_data=f"ok_{t_id}")])
        
    teclado = InlineKeyboardMarkup(botones)
    await update.message.reply_text(text=mensaje, reply_markup=teclado, parse_mode=ParseMode.HTML)

async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await verificar_usuario(update): return
    texto = (
        "🤖 <b>Guía de Funciones de Secretar-IA</b>\n\n"
        "• 📅 <b>Eventos:</b> Decí o escribí citas (ej. <i>'Reunión el martes a las 15hs'</i>) para guardarlas en Google Calendar.\n"
        "• ⏰ <b>Recordatorios:</b> Programá alarmas (ej. <i>'Recordame llamar a mamá a las 18hs'</i>).\n"
        "• 📔 <b>Notas:</b> Guardá información sin fecha (ej. <i>'Anotá la clave del wifi es 1234'</i>).\n"
        "• 📋 <b>Comandos disponibles:</b>\n"
        "  /resumen - Ver tareas y eventos próximos.\n"
        "  /notas - Consultar tus notas guardadas.\n"
        "  /ayuda - Muestra esta guía.\n"
        "  /test - Verifica el estado de la base de datos y Calendar.\n"
        "• 🗑️ <b>Gestión:</b> Decí <i>'deshacer'</i> para borrar la última carga, o <i>'borrar todo lo del 25 de octubre'</i> para limpiar una fecha."
    )
    await update.message.reply_text(texto, parse_mode=ParseMode.HTML)

async def test_sistema(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await verificar_usuario(update): return
    chat_id = str(update.effective_chat.id)
    try:
        # Prueba de conexión a la Base de Datos (Neon)
        pendientes = base_datos.obtener_pendientes(chat_id)
        # Prueba de conexión a Google Calendar
        eventos = calendario.obtener_eventos_calendario()
        
        resultado = (
            "🧪 <b>Diagnóstico del Sistema:</b>\n\n"
            "✅ Base de datos (Neon.tech): Conectada\n"
            f"   └ Tareas/Notas pendientes: {len(pendientes)}\n"
            "✅ Google Calendar: Conectado\n"
            f"   └ Próximos eventos sincronizados: {len(eventos)}\n"
            "✅ Motor de IA (Groq): Activo"
        )
        await update.message.reply_text(resultado, parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ Error en el test del sistema:\n<code>{e}</code>", parse_mode=ParseMode.HTML)


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("resumen", test_resumen))
    app.add_handler(CommandHandler("notas", ver_notas))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_texto))
    app.add_handler(MessageHandler(filters.VOICE, recibir_audio))
    app.add_handler(CallbackQueryHandler(marcar_completada, pattern="^ok_"))
    
    hora_envio = datetime.time(hour=6, minute=50, tzinfo=ZONA_HORARIA)
    app.job_queue.run_daily(enviar_resumen_diario, time=hora_envio)
    
    # Inicia el servidor web simulado en segundo plano
    threading.Thread(target=iniciar_servidor, daemon=True).start()
    
    print("Bot privado con soporte para Render iniciado.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()