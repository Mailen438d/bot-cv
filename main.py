import asyncio
import os
import threading
import io
import httpx
import asyncpg
from datetime import datetime, timedelta
from flask import Flask
from pypdf import PdfReader
from fpdf import FPDF
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, LabeledPrice, PreCheckoutQuery, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
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
def home(): return "✅ Bot encendido"
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
def keep_alive():
    t = threading.Thread(target=run_flask)
    t.start()

db_pool = None
scheduler = AsyncIOScheduler()

# --- TEXTOS DE IDIOMA ---
TEXTOS = {
    "es": {
        "bienvenida": "¡Hola! 💼 Soy tu **Súper Asistente de Carrera con IA**.\n\nTienes **2 usos gratuitos**. Puedes escribirme o enviarme una **nota de voz**.",
        "cv": "📄 Analizar mi CV ($5)", "carta": "✉️ Carta de Presentación ($5)",
        "entrevista": "🎤 Simulador de Entrevista ($10)", "estafa": "🕵️ Detector de Estafas ($5)",
        "cold_email": "🚀 Cold Email LinkedIn ($5)", "linkedin": "💼 Optimizar mi LinkedIn ($5)",
        "pdf": "📑 Descargar CV en PDF Profesional ($10)", "adaptar": "🌍 Adaptar CV a otro País ($8)",
        "empleos": "🔍 Buscar Empleos (GRATIS)", "vip": "🔔 Cazador VIP (300 Stars/mes)",
        "pro": "⭐ PASE PRO (500 Stars / 2 Meses)", "referido": "🎁 Invitar Amigos (Ganar Usos)",
        "info": "ℹ️ Información de las Herramientas", "idioma": "🌐 Cambiar Idioma (ES/EN)"
    },
    "en": {
        "bienvenida": "Hello! 💼 I am your **AI Career Super Assistant**.\n\nYou have **2 free uses**. You can write or send a **voice note**.",
        "cv": "📄 Analyze my Resume ($5)", "carta": "✉️ Cover Letter ($5)",
        "entrevista": "🎤 Interview Simulator ($10)", "estafa": "🕵️ Scam Detector ($5)",
        "cold_email": "🚀 LinkedIn Cold Email ($5)", "linkedin": "💼 Optimize my LinkedIn ($5)",
        "pdf": "📑 Download Resume as PDF ($10)", "adaptar": "🌍 Adapt Resume to Country ($8)",
        "empleos": "🔍 Find Jobs (FREE)", "vip": "🔔 VIP Hunter (300 Stars/month)",
        "pro": "⭐ PRO PASS (500 Stars / 2 Months)", "referido": "🎁 Invite Friends (Earn Uses)",
        "info": "ℹ️ Tools Information", "idioma": "🌐 Change Language (ES/EN)"
    }
}

# --- ESTADOS ---
class Herramientas(StatesGroup):
    esperando_cv = State()
    esperando_carta = State()
    esperando_estafa = State()
    esperando_cold_email = State()
    esperando_linkedin = State()
    esperando_pdf = State()
    esperando_pais_adaptar = State()
    esperando_texto_adaptar = State()

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

async def enviar_mensaje_seguro(chat_id, texto):
    texto_cortado = texto[:4000]
    try:
        await bot.send_message(chat_id=chat_id, text=texto_cortado, parse_mode="Markdown")
    except Exception:
        await bot.send_message(chat_id=chat_id, text=texto_cortado)

# --- MENÚ PRINCIPAL ---
def menu_principal(idioma="es"):
    t = TEXTOS.get(idioma, TEXTOS["es"])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t["cv"], callback_data="menu_cv"), InlineKeyboardButton(text=t["carta"], callback_data="menu_carta")],
        [InlineKeyboardButton(text=t["entrevista"], callback_data="menu_entrevista"), InlineKeyboardButton(text=t["estafa"], callback_data="menu_estafa")],
        [InlineKeyboardButton(text=t["cold_email"], callback_data="menu_cold_email"), InlineKeyboardButton(text=t["linkedin"], callback_data="menu_linkedin")],
        [InlineKeyboardButton(text=t["pdf"], callback_data="menu_pdf"), InlineKeyboardButton(text=t["adaptar"], callback_data="menu_adaptar")],
        [InlineKeyboardButton(text=t["empleos"], callback_data="menu_empleos")],
        [InlineKeyboardButton(text=t["vip"], callback_data="menu_vip"), InlineKeyboardButton(text=t["pro"], callback_data="menu_pro")],
        [InlineKeyboardButton(text=t["referido"], callback_data="menu_referido"), InlineKeyboardButton(text=t["info"], callback_data="menu_info")],
        [InlineKeyboardButton(text=t["idioma"], callback_data="menu_idioma")]
    ])
    return kb

@dp.message(CommandStart(deep_link=False))
async def start(msg: Message):
    uid = msg.from_user.id
    async with db_pool.acquire() as conn:
        usuario = await conn.fetchrow("SELECT * FROM usuarios WHERE user_id = $1", uid)
        if not usuario:
            await conn.execute("INSERT INTO usuarios (user_id, usos_gratis, idioma) VALUES ($1, $2, $3)", uid, 2, "es")
            idioma = "es"
        else:
            idioma = usuario['idioma'] or "es"
    
    await msg.answer(TEXTOS[idioma]["bienvenida"], reply_markup=menu_principal(idioma), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("menu_"))
async def manejar_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    accion = callback.data.split("_")[1]
    uid = callback.from_user.id
    
    async with db_pool.acquire() as conn:
        usuario = await conn.fetchrow("SELECT idioma FROM usuarios WHERE user_id = $1", uid)
        idioma = usuario['idioma'] if usuario and usuario['idioma'] else "es"

    if accion == "cv":
        await callback.message.answer("📄 Envíame el **texto de tu CV**, un **PDF** o una **nota de voz**.")
        await state.set_state(Herramientas.esperando_cv)
    elif accion == "carta":
        await callback.message.answer("✉️ Envíame la **oferta de trabajo** y te escribiré una carta.")
        await state.set_state(Herramientas.esperando_carta)
    elif accion == "estafa":
        await callback.message.answer("🕵️ Pega el mensaje de la oferta y te diré si es real o estafa.")
        await state.set_state(Herramientas.esperando_estafa)
    elif accion == "cold_email":
        await callback.message.answer("🚀 Pega la oferta o el perfil del reclutador.")
        await state.set_state(Herramientas.esperando_cold_email)
    elif accion == "linkedin":
        await callback.message.answer("💼 Pega tu perfil de LinkedIn.")
        await state.set_state(Herramientas.esperando_linkedin)
    elif accion == "pdf":
        await callback.message.answer("📑 Pega el texto de tu CV y lo convertiré en un PDF profesional.")
        await state.set_state(Herramientas.esperando_pdf)
    elif accion == "adaptar":
        await callback.message.answer("🌍 ¿A qué país quieres adaptar tu CV? (Ej: Canadá, España, USA, Alemania)")
        await state.set_state(Herramientas.esperando_pais_adaptar)
    elif accion == "entrevista":
        await callback.message.answer("🎤 ¿Para qué puesto quieres que te entreviste?")
        await state.set_state(Entrevista.esperando_puesto)
    elif accion == "empleos":
        await callback.message.answer("🔍 ¿Qué tipo de empleo buscas? (Ej: Programador, Ventas)")
        await state.set_state(BuscadorEmpleo.esperando_palabra)
    elif accion == "vip":
        await cobrar_alerta_vip(uid)
    elif accion == "pro":
        await cobrar_pro(uid)
    elif accion == "referido":
        bot_info = await bot.get_me()
        link = f"https://t.me/{bot_info.username}?start={uid}"
        await callback.message.answer(f"🎁 **Invita y gana**\n\n+3 usos por cada amigo:\n`{link}`", parse_mode="Markdown")
    elif accion == "info":
        info_texto = "ℹ️ **Información**\n\nUsa el menú para analizar tu CV, crear cartas, buscar empleos y más."
        await callback.message.answer(info_texto, parse_mode="Markdown")
    elif accion == "idioma":
        nuevo_idioma = "en" if idioma == "es" else "es"
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE usuarios SET idioma = $1 WHERE user_id = $2", nuevo_idioma, uid)
        await callback.message.answer("Language changed to English 🇬🇧" if nuevo_idioma == "en" else "Idioma cambiado a Español 🇪🇸", reply_markup=menu_principal(nuevo_idioma))

async def verificar_uso(message: Message, herramienta: str):
    uid = message.from_user.id
    async with db_pool.acquire() as conn:
        usuario = await conn.fetchrow("SELECT * FROM usuarios WHERE user_id = $1", uid)
        
        if 'pro_expira' in usuario.keys() and usuario['pro_expira']:
            if usuario['pro_expira'] > datetime.now(): return True
            
        columna = f"pago_{herramienta}"
        if columna in usuario.keys() and usuario[columna]: return True
        
        if usuario['usos_gratis'] > 0:
            nuevos = usuario['usos_gratis'] - 1
            await conn.execute("UPDATE usuarios SET usos_gratis = $1 WHERE user_id = $2", nuevos, uid)
            await message.answer(f"*(Te quedan {nuevos} usos gratis)*", parse_mode="Markdown")
            return True
        else:
            await cobrar_herramienta_individual(uid, herramienta)
            return False

def crear_pdf(texto_cv):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=11)
    texto_limpio = texto_cv.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 8, texto_limpio)
    ruta_pdf = f"cv_{datetime.now().timestamp()}.pdf"
    pdf.output(ruta_pdf)
    return ruta_pdf

async def procesar_con_ia(msg: Message, texto: str, herramienta: str, extra_data=None):
    await bot.send_chat_action(chat_id=msg.chat.id, action="typing")
    try:
        prompts = {
            "cv": "Analiza este CV y da consejos.",
            "carta": "Escribe una carta de presentación para esta oferta.",
            "estafa": "Analiza si esta oferta es una estafa. Sé contundente.",
            "cold_email": "Escribe un mensaje corto para LinkedIn.",
            "linkedin": "Reescribe este texto de LinkedIn para hacerlo profesional.",
            "pdf": "Reescribe este CV de forma profesional para imprimir.",
            "adaptar": f"Adapta este CV al formato de {extra_data}.",
            "admin": "Estás hablando con el creador. Responde técnico."
        }
        response = await client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "system", "content": prompts.get(herramienta, prompts["cv"])}, {"role": "user", "content": texto}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error con la IA: {e}"

@dp.message(F.text & ~F.text.startswith("/"))
async def manejar_texto(msg: Message, state: FSMContext):
    current_state = await state.get_state()
    uid = msg.from_user.id
    
    if current_state == AdminChat.en_progreso.state:
        if uid == ADMIN_ID:
            res = await procesar_con_ia(msg, msg.text, "admin")
            await enviar_mensaje_seguro(uid, res)
        return

    if current_state == BuscadorEmpleo.esperando_palabra.state:
        await state.update_data(busqueda=msg.text)
        await msg.answer("🌍 ¿País o ciudad? (Escribe 'Remoto')")
        await state.set_state(BuscadorEmpleo.esperando_pais)
        return
    elif current_state == BuscadorEmpleo.esperando_pais.state:
        await buscar_empleos(msg, state)
        return
    
    if current_state == Herramientas.esperando_pais_adaptar.state:
        await state.update_data(pais_destino=msg.text)
        await msg.answer("🌍 Perfecto. Ahora pega el **texto de tu CV** para adaptarlo.")
        await state.set_state(Herramientas.esperando_texto_adaptar)
        return

    if current_state == Entrevista.en_progreso.state:
        await responder_entrevista(msg, state)
        return
    elif current_state == Entrevista.esperando_puesto.state:
        if not await verificar_uso(msg, "entrevista"): return
        await state.update_data(puesto=msg.text, pregunta_num=1, historial=[])
        await msg.answer(f"🎤 Entrevista para **{msg.text}**.\n\nPregunta 1: Cuéntame sobre ti.", parse_mode="Markdown")
        await state.set_state(Entrevista.en_progreso)
        return

    mapeo = {
        Herramientas.esperando_cv.state: "cv",
        Herramientas.esperando_carta.state: "carta",
        Herramientas.esperando_estafa.state: "estafa",
        Herramientas.esperando_cold_email.state: "cold_email",
        Herramientas.esperando_linkedin.state: "linkedin"
    }

    if current_state in mapeo:
        herramienta = mapeo[current_state]
        await state.clear()
        if not await verificar_uso(msg, herramienta): return
        res = await procesar_con_ia(msg, msg.text, herramienta)
        await enviar_mensaje_seguro(uid, res)
    elif current_state == Herramientas.esperando_pdf.state:
        await state.clear()
        if not await verificar_uso(msg, "pdf"): return
        await msg.answer("⏳ Generando PDF...")
        texto_pdf = await procesar_con_ia(msg, msg.text, "pdf")
        try:
            ruta = crear_pdf(texto_pdf)
            await msg.answer_document(FSInputFile(ruta), caption="📑 Aquí tienes tu CV en PDF.")
            os.remove(ruta)
        except Exception as e:
            await msg.answer(f"Error al crear PDF: {e}")
    elif current_state == Herramientas.esperando_texto_adaptar.state:
        datos = await state.get_data()
        pais = datos.get("pais_destino", "Canadá")
        await state.clear()
        if not await verificar_uso(msg, "adaptar"): return
        await msg.answer(f"⏳ Adaptando tu CV al formato de **{pais}**...")
        res = await procesar_con_ia(msg, msg.text, "adaptar", extra_data=pais)
        await enviar_mensaje_seguro(uid, res)
    else:
        if not await verificar_uso(msg, "cv"): return
        res = await procesar_con_ia(msg, msg.text, "cv")
        await enviar_mensaje_seguro(uid, res)

@dp.message(F.voice)
async def manejar_audio(msg: Message, state: FSMContext):
    current_state = await state.get_state()
    mapeo = {Herramientas.esperando_cv.state: "cv", Herramientas.esperando_carta.state: "carta", Herramientas.esperando_estafa.state: "estafa", Herramientas.esperando_pdf.state: "pdf"}
    herramienta = mapeo.get(current_state, "cv")
    await state.clear()
    if not await verificar_uso(msg, herramienta): return
    await msg.answer("🎤 Escuchando audio...")
    try:
        file = await bot.get_file(msg.voice.file_id)
        file_bytes = await bot.download_file(file.file_path)
        transcription = await client.audio.transcriptions.create(file=("audio.ogg", file_bytes.read()), model="whisper-large-v3")
        texto_transcrito = transcription.text
        await msg.answer(f"🗣️ *Entendido:* {texto_transcrito}", parse_mode="Markdown")
        if herramienta == "pdf":
            texto_pdf = await procesar_con_ia(msg, texto_transcrito, "pdf")
            ruta = crear_pdf(texto_pdf)
            await msg.answer_document(FSInputFile(ruta), caption="📑 Tu CV en PDF.")
            os.remove(ruta)
        else:
            res = await procesar_con_ia(msg, texto_transcrito, herramienta)
            await enviar_mensaje_seguro(msg.from_user.id, res)
    except Exception as e:
        await msg.answer(f"❌ Error audio: {e}")

async def buscar_empleos(msg: Message, state: FSMContext):
    pais = msg.text.lower()
    datos = await state.get_data()
    palabra = datos.get("busqueda", "").lower()
    await state.clear()
    await msg.answer(f"🔎 Buscando **{palabra}**...")
    enc = 0
    try:
        async with httpx.AsyncClient() as client_http:
            res_j = await client_http.get(f"https://jobicy.com/api/v2/remote-jobs?count=10&tag={palabra}")
            if res_j.status_code == 200:
                for job in res_j.json().get("jobs", []):
                    if palabra in str(job.get('jobTitle','')).lower() or palabra in str(job.get('jobExcerpt','')).lower():
                        await msg.answer(f"💼 **{job['jobTitle']}**\n🏢 {job['companyName']}\n🔗 [Aplicar]({job['url']})", parse_mode="Markdown", disable_web_page_preview=True)
                        enc += 1
            res_r = await client_http.get(f"https://remotive.com/api/remote-jobs?limit=10&search={palabra}")
            if res_r.status_code == 200:
                for job in res_r.json().get("jobs", []):
                    if palabra in str(job.get('title','')).lower():
                        await msg.answer(f"💼 **{job['title']}**\n🏢 {job['company_name']}\n🔗 [Aplicar]({job['url']})", parse_mode="Markdown", disable_web_page_preview=True)
                        enc += 1
        if enc == 0: await msg.answer("😔 Sin resultados exactos. Prueba en inglés.")
    except: await msg.answer("❌ Error buscador.")

async def cobrar_herramienta_individual(uid, herramienta):
    titulos = {"cv": "CV", "carta": "Carta", "entrevista": "Entrevista", "estafa": "Estafas", "cold_email": "Cold Email", "linkedin": "LinkedIn", "pdf": "CV en PDF", "adaptar": "Adaptar CV"}
    await bot.send_message(uid, f"⚠️ Sin usos gratis. Compra **{titulos.get(herramienta, 'esto')}** por 150 Stars o el PASE PRO.", parse_mode="Markdown")
    await bot.send_invoice(chat_id=uid, title=f"Comprar {titulos.get(herramienta, 'Herramienta')}", description="Acceso de por vida.", payload=f"buy_{herramienta}", provider_token="", currency="XTR", prices=[LabeledPrice(label="Individual", amount=150)])

async def cobrar_pro(uid):
    await bot.send_invoice(chat_id=uid, title="PASE PRO (2 Meses)", description="Acceso ILIMITADO a todo.", payload="pro_2months", provider_token="", currency="XTR", prices=[LabeledPrice(label="Pase PRO", amount=500)])

async def cobrar_alerta_vip(uid):
    await bot.send_invoice(chat_id=uid, title="Cazador VIP (1 Mes)", description="Ofertas diarias.", payload="vip_1month", provider_token="", currency="XTR", prices=[LabeledPrice(label="Cazador VIP", amount=300)])

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
            await msg.answer("🎉 ¡Eres PRO! Tienes acceso total por 2 meses.")
        elif payload == "vip_1month":
            await msg.answer("🎉 ¡Cazador VIP Activado!\n\n¿Qué puesto buscas?")
            await bot.set_state(uid, AlertaVIP.esperando_puesto)
        elif payload.startswith("buy_"):
            h = payload.replace("buy_", "")
            await conn.execute(f"UPDATE usuarios SET pago_{h} = TRUE WHERE user_id = $1", uid)
            await msg.answer(f"🎉 Herramienta desbloqueada con éxito.")

async def guardar_alerta_vip(msg: Message, state: FSMContext):
    ubicacion = msg.text
    datos = await state.get_data()
    puesto = datos.get("puesto_vip", "")
    await state.clear()
    uid = msg.from_user.id
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE usuarios SET alerta_puesto = $1, alerta_ubicacion = $2 WHERE user_id = $3", puesto, ubicacion, uid)
    await msg.answer(f"✅ Alerta configurada para **{puesto}**.")

async def enviar_alertas_diarias():
    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id, alerta_puesto FROM usuarios WHERE alerta_puesto IS NOT NULL")
        for u in users:
            try:
                async with httpx.AsyncClient() as c:
                    res = await c.get(f"https://jobicy.com/api/v2/remote-jobs?count=2&tag={u['alerta_puesto']}")
                    if res.status_code == 200 and res.json().get("jobs"):
                        await bot.send_message(u['user_id'], f"🔔 **Ofertas nuevas para ti:**", parse_mode="Markdown")
                        for j in res.json()["jobs"]:
                            await bot.send_message(u['user_id'], f"💼 **{j['jobTitle']}**\n🏢 {j['companyName']}\n🔗 [Aplicar]({j['url']})", parse_mode="Markdown")
            except: pass

@dp.message(Command("modo_admin"))
async def activar_modo_dios(msg: Message, state: FSMContext):
    if msg.from_user.id == ADMIN_ID:
        await state.set_state(AdminChat.en_progreso)
        await msg.answer("👑 **MODO DIOS ACTIVADO.** Escribe `/salir` para volver.")
    else: await msg.answer("No tienes permiso.")

@dp.message(Command("salir"))
async def salir_modo_dios(msg: Message, state: FSMContext):
    if msg.from_user.id == ADMIN_ID:
        await state.clear()
        await msg.answer("Saliendo del Modo Dios.", reply_markup=menu_principal())

async def responder_entrevista(msg: Message, state: FSMContext):
    datos = await state.get_data()
    num = datos.get("pregunta_num", 1)
    hist = datos.get("historial", [])
    hist.append({"role": "user", "content": msg.text})
    await bot.send_chat_action(chat_id=msg.chat.id, action="typing")
    try:
        msgs = [{"role": "system", "content": f"Entrevistador para {datos['puesto']}. Evalúa brevemente y haz la siguiente pregunta."}] + hist
        res = await client.chat.completions.create(model="openai/gpt-oss-120b", messages=msgs)
        r_ia = res.choices[0].message.content
        hist.append({"role": "assistant", "content": r_ia})
        if num >= 5:
            await enviar_mensaje_seguro(msg.chat.id, f"{r_ia}\n\n✅ **Fin.**")
            await state.clear()
        else:
            await enviar_mensaje_seguro(msg.chat.id, r_ia)
            await state.update_data(pregunta_num=num + 1, historial=hist)
    except: await msg.answer("Error.")

# --- INICIALIZACIÓN (CON TIMEOUT PARA EVITAR CONGELAMIENTO) ---
async def main():
    global db_pool
    
    while True:
        try:
            print("🔄 Intentando conectar a PostgreSQL...", flush=True)
            # Añadimos un timeout de 15 segundos para que no se quede colgado para siempre
            db_pool = await asyncpg.create_pool(DATABASE_URL, timeout=15)
            
            async with db_pool.acquire() as conn:
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS usuarios (
                        user_id BIGINT PRIMARY KEY,
                        usos_gratis INTEGER DEFAULT 2,
                        pro_expira TIMESTAMP,
                        alerta_puesto TEXT,
                        alerta_ubicacion TEXT,
                        idioma TEXT DEFAULT 'es'
                    )
                ''')
                await conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS pro_expira TIMESTAMP;")
                await conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS alerta_puesto TEXT;")
                await conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS alerta_ubicacion TEXT;")
                await conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS idioma TEXT DEFAULT 'es';")
                await conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS pago_cv BOOLEAN DEFAULT FALSE;")
                await conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS pago_carta BOOLEAN DEFAULT FALSE;")
                await conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS pago_entrevista BOOLEAN DEFAULT FALSE;")
                await conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS pago_estafa BOOLEAN DEFAULT FALSE;")
                await conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS pago_cold_email BOOLEAN DEFAULT FALSE;")
                await conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS pago_linkedin BOOLEAN DEFAULT FALSE;")
                await conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS pago_pdf BOOLEAN DEFAULT FALSE;")
                await conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS pago_adaptar BOOLEAN DEFAULT FALSE;")
                
            print("✅ Base de datos conectada y tablas actualizadas.", flush=True)
            break
        except Exception as e:
            print(f"❌ Error conectando a la DB: {e}. Reintentando en 5 segundos...", flush=True)
            await asyncio.sleep(5)

    scheduler.add_job(enviar_alertas_diarias, 'interval', hours=24)
    scheduler.start()

    await bot.delete_webhook(drop_pending_updates=True) 
    print("✅ Súper Bot encendido y escuchando en Telegram...", flush=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    keep_alive()
    asyncio.run(main())