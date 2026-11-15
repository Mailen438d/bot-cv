import asyncio
import os
import threading
import io
import httpx
import asyncpg
from datetime import datetime, timedelta
from flask import Flask
from pypdf import PdfReader
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, LabeledPrice, PreCheckoutQuery, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from groq import AsyncGroq
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ==========================================
# CONFIGURACIÓN Y LLAVES
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
client = AsyncGroq(api_key=GROQ_API_KEY)

# ==========================================
# 🚨 PON TU ID DE TELEGRAM AQUÍ
# ==========================================
ADMIN_ID = 6643605796

# --- SERVIDOR FALSO PARA RENDER ---
app = Flask(__name__)
@app.route('/')
def home(): return "✅ Súper Bot encendido 24/7"
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
def keep_alive():
    t = threading.Thread(target=run_flask)
    t.start()

db_pool = None
scheduler = AsyncIOScheduler()

# --- ESTADOS ---
class Herramientas(StatesGroup):
    esperando_cv = State()
    esperando_carta = State()
    esperando_estafa = State()
    esperando_cold_email = State()
    esperando_linkedin = State()

class Entrevista(StatesGroup):
    esperando_puesto = State()
    en_progreso = State()

class BuscadorEmpleo(StatesGroup):
    esperando_palabra = State()
    esperando_pais = State()

class AlertaVIP(StatesGroup):
    esperando_puesto = State()
    esperando_ubicacion = State()

class AdminChat(StatesGroup):
    en_progreso = State()

# --- FUNCIONES DE AYUDA ---
async def enviar_mensaje_seguro(chat_id, texto):
    texto_cortado = texto[:4000]
    try:
        await bot.send_message(chat_id=chat_id, text=texto_cortado, parse_mode="Markdown")
    except Exception:
        await bot.send_message(chat_id=chat_id, text=texto_cortado)

# --- MENÚ PRINCIPAL ---
def menu_principal():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Analizar mi CV (Valor: $5)", callback_data="menu_cv")],
        [InlineKeyboardButton(text="✉️ Carta de Presentación (Valor: $5)", callback_data="menu_carta")],
        [InlineKeyboardButton(text="🎤 Simulador de Entrevista (Valor: $10)", callback_data="menu_entrevista")],
        [InlineKeyboardButton(text="🕵️ Detector de Estafas (Valor: $5)", callback_data="menu_estafa")],
        [InlineKeyboardButton(text="🚀 Cold Email para LinkedIn (Valor: $5)", callback_data="menu_cold_email")],
        [InlineKeyboardButton(text="💼 Optimizar mi LinkedIn (Valor: $5)", callback_data="menu_linkedin")],
        [InlineKeyboardButton(text="🔍 Buscar Empleos (GRATIS)", callback_data="menu_empleos")],
        [InlineKeyboardButton(text="🔔 Cazador VIP (Alertas 300 Stars/mes)", callback_data="menu_vip")],
        [InlineKeyboardButton(text="⭐ PASE PRO (500 Stars / 2 Meses)", callback_data="menu_pro")],
        [InlineKeyboardButton(text="🎁 Invitar Amigos (Ganar Usos)", callback_data="menu_referido")]
    ])
    return kb

@dp.message(CommandStart(deep_link=False))
async def start(msg: Message):
    uid = msg.from_user.id
    async with db_pool.acquire() as conn:
        usuario = await conn.fetchrow("SELECT * FROM usuarios WHERE user_id = $1", uid)
        if not usuario:
            await conn.execute("INSERT INTO usuarios (user_id, usos_gratis) VALUES ($1, $2)", uid, 2)
    
    texto = (
        "¡Hola! 💼 Soy tu **Súper Asistente de Carrera con IA**.\n\n"
        "Tienes **2 usos gratuitos**. Puedes escribirme o enviarme una **nota de voz**.\n"
        "Si quieres todas las herramientas, revisa el **PASE PRO** en el menú de abajo."
    )
    await msg.answer(texto, reply_markup=menu_principal(), parse_mode="Markdown")

@dp.message(CommandStart(deep_link=True))
async def start_with_ref(msg: Message, command: CommandObject):
    uid = msg.from_user.id
    referrer_id = None
    try: referrer_id = int(command.args)
    except: pass

    async with db_pool.acquire() as conn:
        usuario = await conn.fetchrow("SELECT * FROM usuarios WHERE user_id = $1", uid)
        if not usuario:
            await conn.execute("INSERT INTO usuarios (user_id, usos_gratis) VALUES ($1, $2)", uid, 2)
            if referrer_id and referrer_id != uid:
                await conn.execute("UPDATE usuarios SET usos_gratis = usos_gratis + 3 WHERE user_id = $1", referrer_id)
                try: await bot.send_message(referrer_id, "🎉 ¡Alguien se unió con tu enlace! Has ganado **+3 usos gratis**.", parse_mode="Markdown")
                except: pass

    await msg.answer("¡Hola! 💼 Has entrado con una invitación. ¡Disfruta tus usos gratis!", reply_markup=menu_principal(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("menu_"))
async def manejar_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    accion = callback.data.split("_")[1]
    uid = callback.from_user.id

    if accion == "cv":
        await callback.message.answer("📄 Envíame el **texto de tu CV**, un **PDF** o una **nota de voz**.")
        await state.set_state(Herramientas.esperando_cv)
    elif accion == "carta":
        await callback.message.answer("✉️ Envíame la **oferta de trabajo** (texto, PDF o audio) y te escribiré una carta de presentación.")
        await state.set_state(Herramientas.esperando_carta)
    elif accion == "estafa":
        await callback.message.answer("🕵️ Pega aquí el mensaje de la oferta de trabajo que te enviaron y te diré si es real o una estafa.")
        await state.set_state(Herramientas.esperando_estafa)
    elif accion == "cold_email":
        await callback.message.answer("🚀 Pega aquí la oferta de trabajo o el perfil del reclutador y te escribiré el mensaje perfecto para LinkedIn.")
        await state.set_state(Herramientas.esperando_cold_email)
    elif accion == "linkedin":
        await callback.message.answer("💼 Pega aquí el texto de tu perfil de LinkedIn (tu 'Acerca de' o Experiencia) y lo reescribiré para que sea más profesional.")
        await state.set_state(Herramientas.esperando_linkedin)
    elif accion == "entrevista":
        await callback.message.answer("🎤 ¿Para qué puesto quieres que te entreviste?")
        await state.set_state(Entrevista.esperando_puesto)
    elif accion == "empleos":
        await callback.message.answer("🔍 ¿Qué tipo de empleo buscas? (Ej: Programador, Ventas, Diseño)")
        await state.set_state(BuscadorEmpleo.esperando_palabra)
    elif accion == "vip":
        bot_info = await bot.get_me()
        await cobrar_alerta_vip(uid)
    elif accion == "pro":
        await cobrar_pro(uid)
    elif accion == "referido":
        bot_info = await bot.get_me()
        link = f"https://t.me/{bot_info.username}?start={uid}"
        await callback.message.answer(f"🎁 **Gana usos gratis**\n\nPor cada amigo que se una con tu enlace, ganarás **+3 usos**.\n\n`{link}`", parse_mode="Markdown")

# --- VERIFICACIÓN DE PAGOS Y LÍMITES ---
async def verificar_uso(message: Message, herramienta: str):
    uid = message.from_user.id
    async with db_pool.acquire() as conn:
        usuario = await conn.fetchrow("SELECT * FROM usuarios WHERE user_id = $1", uid)
        if not usuario:
            await conn.execute("INSERT INTO usuarios (user_id, usos_gratis) VALUES ($1, $2)", uid, 2)
            return True

        # 1. Revisar si tiene Pase PRO activo
        if usuario['pro_expira'] and usuario['pro_expira'] > datetime.now():
            return True
        
        # 2. Revisar si compró esta herramienta individual
        columna = f"pago_{herramienta}"
        if columna in usuario.keys() and usuario[columna]:
            return True

        # 3. Usar pase gratis
        if usuario['usos_gratis'] > 0:
            nuevos_usos = usuario['usos_gratis'] - 1
            await conn.execute("UPDATE usuarios SET usos_gratis = $1 WHERE user_id = $2", nuevos_usos, uid)
            await message.answer(f"*(Te quedan {nuevos_usos} usos gratis)*", parse_mode="Markdown")
            return True
        else:
            await cobrar_herramienta_individual(uid, herramienta)
            return False

# --- PROCESAMIENTO DE IA (TODAS LAS HERRAMIENTAS) ---
async def procesar_con_ia(msg: Message, texto: str, herramienta: str):
    await bot.send_chat_action(chat_id=msg.chat.id, action="typing")
    try:
        prompts = {
            "cv": "Eres un reclutador experto. Analiza este CV y da consejos concisos para mejorarlo.",
            "carta": "Eres un experto en RRHH. Escribe una carta de presentación persuasiva basada en esta oferta.",
            "estafa": "Eres un experto en ciberseguridad laboral. Analiza este mensaje de supuesta oferta de trabajo. Dime si es una estafa (phishing, multinivel, piden dinero) o si parece real. Sé contundente.",
            "cold_email": "Eres un experto en ventas y RRHH. Escribe un mensaje corto, directo y persuasivo para enviar por LinkedIn a un reclutador sobre esta oferta o perfil.",
            "linkedin": "Eres un experto en marca personal. Reescribe este texto de LinkedIn para que suene mucho más profesional, atractivo y optimizado para palabras clave.",
            "admin": "Estás hablando con el creador. Responde técnico y directo."
        }
        
        response = await client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "system", "content": prompts.get(herramienta, prompts["cv"])}, {"role": "user", "content": texto}]
        )
        await enviar_mensaje_seguro(msg.chat.id, response.choices[0].message.content)
    except Exception as e:
        await msg.answer("Error con la IA.")

# --- ENTRADA DE TEXTO GENERAL ---
@dp.message(F.text & ~F.text.startswith("/"))
async def manejar_texto(msg: Message, state: FSMContext):
    current_state = await state.get_state()
    
    if current_state == AdminChat.en_progreso.state:
        if msg.from_user.id == ADMIN_ID: await procesar_con_ia(msg, msg.text, "admin")
        return

    # Mapeo de estados a herramientas
    mapeo = {
        Herramientas.esperando_cv.state: "cv",
        Herramientas.esperando_carta.state: "carta",
        Herramientas.esperando_estafa.state: "estafa",
        Herramientas.esperando_cold_email.state: "cold_email",
        Herramientas.esperando_linkedin.state: "linkedin"
    }

    if current_state == Entrevista.en_progreso.state:
        await responder_entrevista(msg, state)
        return
    elif current_state == BuscadorEmpleo.esperando_palabra.state:
        await state.update_data(busqueda=msg.text)
        await msg.answer("🌍 ¿En qué país o ciudad? (Escribe 'Remoto' para buscar en todo el mundo)")
        await state.set_state(BuscadorEmpleo.esperando_pais)
        return
    elif current_state == BuscadorEmpleo.esperando_pais.state:
        await buscar_empleos(msg, state)
        return
    elif current_state == AlertaVIP.esperando_puesto.state:
        await state.update_data(puesto_vip=msg.text)
        await msg.answer("🌍 ¿En qué país o ciudad? (Escribe 'Remoto' si buscas desde casa)")
        await state.set_state(AlertaVIP.esperando_ubicacion)
        return
    elif current_state == AlertaVIP.esperando_ubicacion.state:
        await guardar_alerta_vip(msg, state)
        return

    # Si viene de un botón de herramienta
    if current_state in mapeo:
        herramienta = mapeo[current_state]
        await state.clear()
        if not await verificar_uso(msg, herramienta): return
        await procesar_con_ia(msg, msg.text, herramienta)
    else:
        # Si escribe algo random sin pulsar botón, asumimos que es un CV
        if not await verificar_uso(msg, "cv"): return
        await procesar_con_ia(msg, msg.text, "cv")

# --- AUDIOS (Usa el mismo mapeo que el texto) ---
@dp.message(F.voice)
async def manejar_audio(msg: Message, state: FSMContext):
    current_state = await state.get_state()
    mapeo = {
        Herramientas.esperando_cv.state: "cv",
        Herramientas.esperando_carta.state: "carta",
        Herramientas.esperando_estafa.state: "estafa"
    }
    herramienta = mapeo.get(current_state, "cv")
    await state.clear()
    
    if not await verificar_uso(msg, herramienta): return
    await msg.answer("🎤 Escuchando tu audio...")
    try:
        file = await bot.get_file(msg.voice.file_id)
        file_bytes = await bot.download_file(file.file_path)
        transcription = await client.audio.transcriptions.create(file=("audio.ogg", file_bytes.read()), model="whisper-large-v3")
        texto_transcrito = transcription.text
        await msg.answer(f"🗣️ *He entendido:* {texto_transcrito}\n\nProcesando...", parse_mode="Markdown")
        await procesar_con_ia(msg, texto_transcrito, herramienta)
    except Exception as e:
        await msg.answer(f"❌ Error al procesar el audio: {e}")

# --- BUSCADOR DE EMPLEOS GRATIS ---
async def buscar_empleos(msg: Message, state: FSMContext):
    pais = msg.text.lower()
    datos = await state.get_data()
    palabra = datos.get("busqueda", "")
    await state.clear()
    
    await msg.answer(f"🔎 Buscando ofertas de **{palabra}** en {msg.text}...", parse_mode="Markdown")
    empleos_encontrados = 0
    try:
        async with httpx.AsyncClient() as http_client:
            # Jobicy
            res_jobicy = await http_client.get(f"https://jobicy.com/api/v2/remote-jobs?count=4&tag={palabra}")
            if res_jobicy.status_code == 200:
                for job in res_jobicy.json().get("jobs", []):
                    await msg.answer(f"💼 **{job['jobTitle']}**\n🏢 {job['companyName']}\n📍 Remoto\n🔗 [Aplicar aquí]({job['url']})", parse_mode="Markdown", disable_web_page_preview=True)
                    empleos_encontrados += 1
            
            # Remotive
            res_remotive = await http_client.get(f"https://remotive.com/api/remote-jobs?limit=4&search={palabra}")
            if res_remotive.status_code == 200:
                for job in res_remotive.json().get("jobs", []):
                    await msg.answer(f"💼 **{job['title']}**\n🏢 {job['company_name']}\n📍 {job['candidate_required_location']}\n🔗 [Aplicar aquí]({job['url']})", parse_mode="Markdown", disable_web_page_preview=True)
                    empleos_encontrados += 1

        if empleos_encontrados == 0:
            await msg.answer(f"😔 No encontré ofertas para esa palabra. Prueba en inglés (ej. 'developer').")
    except Exception as e:
        await msg.answer(f"❌ Error al buscar empleos.")

# --- SISTEMA DE PAGOS ---
async def cobrar_herramienta_individual(uid, herramienta):
    titulos = {"cv": "Análisis de CV", "carta": "Carta de Presentación", "entrevista": "Simulador", "estafa": "Detector de Estafas", "cold_email": "Cold Email", "linkedin": "Optimizar LinkedIn"}
    await bot.send_message(uid, f"⚠️ Has agotado tus usos gratis.\n\nPuedes comprar **{titulos.get(herramienta, 'esta herramienta')}** por **150 Stars (~$3 USD)** o el **PASE PRO** en el menú.", parse_mode="Markdown")
    await bot.send_invoice(chat_id=uid, title=f"Desbloquear {titulos.get(herramienta, 'Herramienta')}", description="Acceso de por vida a esta herramienta.", payload=f"buy_{herramienta}", provider_token="", currency="XTR", prices=[LabeledPrice(label="Individual", amount=150)])

async def cobrar_pro(uid):
    await bot.send_invoice(chat_id=uid, title="PASE PRO (2 Meses)", description="Acceso ILIMITADO a TODAS las herramientas y al Cazador VIP por 2 meses.", payload="pro_2months", provider_token="", currency="XTR", prices=[LabeledPrice(label="Pase PRO", amount=500)])

async def cobrar_alerta_vip(uid):
    await bot.send_invoice(chat_id=uid, title="Cazador VIP (1 Mes)", description="Recibe ofertas de trabajo personalizadas todos los días en tu privado.", payload="vip_1month", provider_token="", currency="XTR", prices=[LabeledPrice(label="Cazador VIP", amount=300)])

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def pago_exitoso(msg: Message):
    uid = msg.from_user.id
    payload = msg.successful_payment.invoice_payload
    
    async with db_pool.acquire() as conn:
        if payload == "pro_2months":
            expira = datetime.now() + timedelta(days=60)
            await conn.execute("UPDATE usuarios SET pro_expira = $1 WHERE user_id = $2", expira, uid)
            await msg.answer("🎉 ¡Felicidades! Eres usuario **PASE PRO**. Tienes acceso total por 2 meses.", reply_markup=menu_principal())
        elif payload == "vip_1month":
            await msg.answer("🎉 ¡Cazador VIP Activado!\n\nAhora dime, ¿Qué puesto buscas? (Ej: Programador)")
            # (Aquí el bot pasaría al estado AlertaVIP.esperando_puesto)
        elif payload.startswith("buy_"):
            herramienta = payload.replace("buy_", "")
            await conn.execute(f"UPDATE usuarios SET pago_{herramienta} = TRUE WHERE user_id = $1", uid)
            await msg.answer(f"🎉 Has desbloqueado esta herramienta con éxito.", reply_markup=menu_principal())

# --- CAZADOR VIP: LÓGICA DE ALERTAS DIARIAS ---
async def guardar_alerta_vip(msg: Message, state: FSMContext):
    ubicacion = msg.text
    datos = await state.get_data()
    puesto = datos.get("puesto_vip", "")
    await state.clear()
    uid = msg.from_user.id

    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE usuarios SET alerta_puesto = $1, alerta_ubicacion = $2 WHERE user_id = $3", puesto, ubicacion, uid)
    
    await msg.answer(f"✅ Alerta configurada. Todos los días te enviaré ofertas de **{puesto}** en **{ubicacion}**.")

# --- TAREA DIARIA (SE EJECUTA CADA 24 HORAS) ---
async def enviar_alertas_diarias():
    print("⏰ Ejecutando envío de alertas diarias...")
    async with db_pool.acquire() as conn:
        usuarios_vip = await conn.fetch("SELECT user_id, alerta_puesto, alerta_ubicacion FROM usuarios WHERE alerta_puesto IS NOT NULL")
        
        for u in usuarios_vip:
            uid = u['user_id']
            puesto = u['alerta_puesto']
            try:
                async with httpx.AsyncClient() as http_client:
                    res = await http_client.get(f"https://jobicy.com/api/v2/remote-jobs?count=2&tag={puesto}")
                    if res.status_code == 200:
                        jobs = res.json().get("jobs", [])
                        if jobs:
                            await bot.send_message(uid, f"🔔 **Ofertas nuevas para ti ({puesto}):**", parse_mode="Markdown")
                            for job in jobs:
                                await bot.send_message(uid, f"💼 **{job['jobTitle']}**\n🏢 {job['companyName']}\n🔗 [Aplicar aquí]({job['url']})", parse_mode="Markdown", disable_web_page_preview=True)
            except:
                pass

# --- MODO DIOS (ADMIN) ---
@dp.message(Command("modo_admin"))
async def activar_modo_dios(msg: Message, state: FSMContext):
    if msg.from_user.id == ADMIN_ID:
        await state.set_state(AdminChat.en_progreso)
        await msg.answer("👑 **MODO DIOS ACTIVADO.** Pregúntame lo que quieras. Escribe `/salir` para volver.")
    else: await msg.answer("No tienes permiso.")

@dp.message(Command("salir"))
async def salir_modo_dios(msg: Message, state: FSMContext):
    if msg.from_user.id == ADMIN_ID:
        await state.clear()
        await msg.answer("Saliendo del Modo Dios.", reply_markup=menu_principal())

# --- SIMULADOR DE ENTREVISTA ---
@dp.message(Entrevista.esperando_puesto)
async def iniciar_entrevista(msg: Message, state: FSMContext):
    if not await verificar_uso(msg, "entrevista"): return
    await state.update_data(puesto=msg.text, pregunta_num=1, historial=[])
    await msg.answer(f"🎤 Entrevista para **{msg.text}**.\n\nPregunta 1: Cuéntame sobre ti.", parse_mode="Markdown")
    await state.set_state(Entrevista.en_progreso)

async def responder_entrevista(msg: Message, state: FSMContext):
    datos = await state.get_data()
    pregunta_num = datos.get("pregunta_num", 1)
    historial = datos.get("historial", [])
    historial.append({"role": "user", "content": msg.text})
    await bot.send_chat_action(chat_id=msg.chat.id, action="typing")
    try:
        messages = [{"role": "system", "content": f"Entrevistador para {datos['puesto']}. Evalúa brevemente y haz la siguiente pregunta."}] + historial
        response = await client.chat.completions.create(model="openai/gpt-oss-120b", messages=messages)
        respuesta_ia = response.choices[0].message.content
        historial.append({"role": "assistant", "content": respuesta_ia})
        if pregunta_num >= 5:
            await enviar_mensaje_seguro(msg.chat.id, f"{respuesta_ia}\n\n✅ **Fin de la simulación.**")
            await state.clear()
        else:
            await enviar_mensaje_seguro(msg.chat.id, respuesta_ia)
            await state.update_data(pregunta_num=pregunta_num + 1, historial=historial)
    except Exception as e:
        await msg.answer("Error.")

# --- INICIALIZACIÓN ---
async def main():
    global db_pool
    print("Iniciando bot...")
    while True:
        try:
            db_pool = await asyncpg.create_pool(DATABASE_URL)
            async with db_pool.acquire() as conn:
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS usuarios (
                        user_id BIGINT PRIMARY KEY,
                        usos_gratis INTEGER DEFAULT 2,
                        pro_expira TIMESTAMP,
                        alerta_puesto TEXT,
                        alerta_ubicacion TEXT,
                        pago_cv BOOLEAN DEFAULT FALSE,
                        pago_carta BOOLEAN DEFAULT FALSE,
                        pago_entrevista BOOLEAN DEFAULT FALSE,
                        pago_estafa BOOLEAN DEFAULT FALSE,
                        pago_cold_email BOOLEAN DEFAULT FALSE,
                        pago_linkedin BOOLEAN DEFAULT FALSE
                    )
                ''')
            print("✅ DB conectada. Tabla lista.")
            break
        except Exception as e:
            print(f"❌ Error DB: {e}. Reintentando...")
            await asyncio.sleep(5)

    # Iniciar el programador de alertas diarias (Cada 24 horas)
    scheduler.add_job(enviar_alertas_diarias, 'interval', hours=24)
    scheduler.start()

    await bot.delete_webhook(drop_pending_updates=True) 
    print("✅ Súper Bot encendido...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    keep_alive()
    asyncio.run(main())