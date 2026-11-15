import asyncio
import os
import threading
import io
import httpx
import asyncpg
from flask import Flask
from pypdf import PdfReader
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, LabeledPrice, PreCheckoutQuery, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from groq import AsyncGroq

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
def home(): return "✅ Bot Multipropósito encendido 24/7"
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
def keep_alive():
    t = threading.Thread(target=run_flask)
    t.start()

db_pool = None

# --- ESTADOS ---
class Analisis(StatesGroup):
    esperando_cv = State()
    esperando_carta = State()

class Entrevista(StatesGroup):
    esperando_puesto = State()
    en_progreso = State()

class BuscadorEmpleo(StatesGroup):
    esperando_palabra = State()
    esperando_pais = State()

class AdminChat(StatesGroup):
    en_progreso = State()

# --- FUNCIÓN MAESTRA PARA ENVIAR MENSAJES ---
async def enviar_mensaje_seguro(chat_id, texto):
    texto_cortado = texto[:4000]
    try:
        await bot.send_message(chat_id=chat_id, text=texto_cortado, parse_mode="Markdown")
    except Exception:
        await bot.send_message(chat_id=chat_id, text=texto_cortado)

# --- MENÚ PRINCIPAL CON PRECIOS POR SEPARADO ---
def menu_principal():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Analizar mi CV (150 Stars / $3)", callback_data="menu_cv")],
        [InlineKeyboardButton(text="✉️ Carta de Presentación (150 Stars / $3)", callback_data="menu_carta")],
        [InlineKeyboardButton(text="🎤 Simulador de Entrevista (150 Stars / $3)", callback_data="menu_entrevista")],
        [InlineKeyboardButton(text="💼 Buscar Empleos (150 Stars / $3)", callback_data="menu_empleos")],
        [InlineKeyboardButton(text="🎁 Invitar Amigos (Ganar Usos)", callback_data="menu_referido")],
        [InlineKeyboardButton(text="⭐ Obtener TODO por 300 Stars ($6)", callback_data="menu_premium")]
    ])
    return kb

# --- INICIO NORMAL ---
@dp.message(CommandStart(deep_link=False))
async def start(msg: Message):
    uid = msg.from_user.id
    async with db_pool.acquire() as conn:
        usuario = await conn.fetchrow("SELECT * FROM usuarios WHERE user_id = $1", uid)
        if not usuario:
            await conn.execute("INSERT INTO usuarios (user_id, pago_activo, usos_gratis) VALUES ($1, $2, $3)", uid, False, 2)
    
    texto = (
        "¡Hola! 💼 Soy tu **Asistente de Carrera Profesional con IA**.\n\n"
        "Tienes **2 usos gratuitos** para probar. Luego puedes comprar cada herramienta por separado por solo **150 Stars (~$3 USD)** o el paquete completo por 300 Stars.\n\n"
        "Puedes escribirme o enviarme una **nota de voz**."
    )
    await msg.answer(texto, reply_markup=menu_principal(), parse_mode="Markdown")

# --- INICIO CON ENLACE DE REFERIDO ---
@dp.message(CommandStart(deep_link=True))
async def start_with_ref(msg: Message, command: CommandObject):
    uid = msg.from_user.id
    referrer_id = None
    try:
        referrer_id = int(command.args)
    except:
        pass

    async with db_pool.acquire() as conn:
        usuario = await conn.fetchrow("SELECT * FROM usuarios WHERE user_id = $1", uid)
        if not usuario:
            await conn.execute("INSERT INTO usuarios (user_id, pago_activo, usos_gratis) VALUES ($1, $2, $3)", uid, False, 2)
            if referrer_id and referrer_id != uid:
                await conn.execute("UPDATE usuarios SET usos_gratis = usos_gratis + 3 WHERE user_id = $1", referrer_id)
                try:
                    await bot.send_message(referrer_id, "🎉 ¡Alguien se ha unido con tu enlace! Has ganado **+3 usos gratis**.", parse_mode="Markdown")
                except:
                    pass

    await msg.answer("¡Hola! 💼 Has entrado con una invitación. ¡Disfruta tus usos gratis!\n\nEscribe o envía una nota de voz para empezar.", reply_markup=menu_principal(), parse_mode="Markdown")

# --- MANEJADOR DE BOTONES ---
@dp.callback_query(F.data.startswith("menu_"))
async def manejar_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    accion = callback.data.split("_")[1]
    uid = callback.from_user.id

    if accion == "cv":
        await callback.message.answer("📄 Envíame el **texto de tu CV**, un **PDF** o una **nota de voz** explicándome tu perfil.")
        await state.set_state(Analisis.esperando_cv)
    elif accion == "carta":
        await callback.message.answer("✉️ Envíame la **oferta de trabajo** (texto, PDF o audio) y te escribiré una carta de presentación.")
        await state.set_state(Analisis.esperando_carta)
    elif accion == "entrevista":
        await callback.message.answer("🎤 ¿Para qué puesto quieres que te entreviste? (Ej: Desarrollador Web, Gerente de Ventas)")
        await state.set_state(Entrevista.esperando_puesto)
    elif accion == "empleos":
        await callback.message.answer("💼 ¿Qué tipo de empleo buscas? (Ej: Programador, Marketing, Soporte)\n\nEscribe la palabra clave:")
        await state.set_state(BuscadorEmpleo.esperando_palabra)
    elif accion == "referido":
        bot_info = await bot.get_me()
        link = f"https://t.me/{bot_info.username}?start={uid}"
        texto_ref = f"🎁 **Gana usos gratis**\n\nPor cada amigo que se una usando tu enlace, ganarás **+3 usos**.\n\n`{link}`"
        await callback.message.answer(texto_ref, parse_mode="Markdown")
    elif accion == "premium":
        await cobrar_paquete_completo(uid)

# --- VERIFICACIÓN DE USOS Y COBROS INDIVIDUALES ---
async def verificar_uso(message: Message, herramienta: str):
    uid = message.from_user.id
    async with db_pool.acquire() as conn:
        usuario = await conn.fetchrow("SELECT * FROM usuarios WHERE user_id = $1", uid)
        if not usuario:
            await conn.execute("INSERT INTO usuarios (user_id, pago_activo, usos_gratis) VALUES ($1, $2, $3)", uid, False, 2)
            return True

        if usuario['pago_activo']: return True
        
        # Revisar si ya compró esta herramienta en específico
        columna = f"pago_{herramienta}"
        if columna in usuario.keys() and usuario[columna]:
            return True

        if usuario['usos_gratis'] > 0:
            nuevos_usos = usuario['usos_gratis'] - 1
            await conn.execute("UPDATE usuarios SET usos_gratis = $1 WHERE user_id = $2", nuevos_usos, uid)
            await message.answer(f"*(Te quedan {nuevos_usos} usos gratis)*", parse_mode="Markdown")
            return True
        else:
            await cobrar_herramienta_individual(uid, herramienta)
            return False

async def cobrar_herramienta_individual(uid, herramienta):
    titulos = {
        "cv": "Análisis de CV",
        "carta": "Carta de Presentación",
        "entrevista": "Simulador de Entrevista",
        "empleos": "Buscador de Empleos"
    }
    await bot.send_message(uid, f"⚠️ Has agotado tus usos gratis para **{titulos.get(herramienta, 'esta herramienta')}**.\n\nPuedes comprar esta herramienta por **150 Stars (~$3 USD)** o comprar el pase completo en el menú por 300 Stars.", parse_mode="Markdown")
    
    await bot.send_invoice(
        chat_id=uid,
        title=f"Desbloquear {titulos.get(herramienta, 'Herramienta')}",
        description="Paga una sola vez y accede a esta herramienta sin límites.",
        payload=f"buy_{herramienta}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Acceso Individual", amount=150)] # 150 Stars = ~3 USD
    )

# --- 🎙️ RECONOCIMIENTO DE VOZ ---
@dp.message(F.voice)
async def procesar_audio(msg: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state == Analisis.esperando_carta.state:
        herramienta = "carta"
    elif current_state == Entrevista.en_progreso.state:
        await msg.answer("Durante la entrevista, por favor escribe tus respuestas.")
        return
    else:
        herramienta = "cv"
    
    await state.clear()
    if not await verificar_uso(msg, herramienta): return
    
    await msg.answer("🎤 Escuchando tu audio...")
    try:
        file = await bot.get_file(msg.voice.file_id)
        file_bytes = await bot.download_file(file.file_path)
        transcription = await client.audio.transcriptions.create(
            file=("audio.ogg", file_bytes.read()),
            model="whisper-large-v3",
        )
        texto_transcrito = transcription.text
        await msg.answer(f"🗣️ *He entendido:* {texto_transcrito}\n\nProcesando...", parse_mode="Markdown")
        await procesar_con_ia(msg, texto_transcrito, herramienta)
    except Exception as e:
        await msg.answer(f"❌ Error al procesar el audio: {e}")

# --- BUSCADOR DE EMPLEOS ---
@dp.message(BuscadorEmpleo.esperando_palabra)
async def preguntar_pais(msg: Message, state: FSMContext):
    await state.update_data(busqueda=msg.text)
    await msg.answer(f"🌍 Entendido. Ahora dime, ¿en qué país o región vives? (Ej: España, México, LATAM, USA)")
    await state.set_state(BuscadorEmpleo.esperando_pais)

@dp.message(BuscadorEmpleo.esperando_pais)
async def buscar_empleos_filtrados(msg: Message, state: FSMContext):
    pais = msg.text.lower()
    datos = await state.get_data()
    palabra = datos.get("busqueda", "")
    await state.clear()
    
    if not await verificar_uso(msg, "empleos"): return
        
    await msg.answer(f"🔎 Buscando ofertas de **{palabra}** para **{msg.text}**...", parse_mode="Markdown")
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(f"https://remotive.com/api/remote-jobs?limit=30&search={palabra}")
            data = response.json()
            if not data.get("jobs"):
                await msg.answer("No encontré ofertas para esa palabra.")
                return
                
            empleos_encontrados = 0
            for job in data["jobs"]:
                loc_oferta = job['candidate_required_location'].lower()
                if "worldwide" in loc_oferta or pais in loc_oferta or "anywhere" in loc_oferta:
                    texto = f"💼 **{job['title']}**\n🏢 {job['company_name']}\n📍 {job['candidate_required_location']}\n🔗 [Aplicar aquí]({job['url']})"
                    await msg.answer(texto, parse_mode="Markdown", disable_web_page_preview=True)
                    empleos_encontrados += 1
                    if empleos_encontrados >= 8: break
            
            if empleos_encontrados == 0:
                await msg.answer(f"😔 No encontré ofertas para **{msg.text}**. Prueba buscando 'Worldwide' o 'LATAM'.", parse_mode="Markdown")
    except Exception as e:
        await msg.answer(f"Error al buscar empleos.")

# --- MODO DIOS (ADMIN) ---
@dp.message(Command("modo_admin"))
async def activar_modo_dios(msg: Message, state: FSMContext):
    if msg.from_user.id == ADMIN_ID:
        await state.set_state(AdminChat.en_progreso)
        await msg.answer("👑 **MODO DIOS ACTIVADO.**\n\nPregúntame lo que quieras (texto o audio). Para salir, escribe `/salir`.")
    else:
        await msg.answer("No tienes permiso.")

@dp.message(Command("salir"))
async def salir_modo_dios(msg: Message, state: FSMContext):
    if msg.from_user.id == ADMIN_ID:
        await state.clear()
        await msg.answer("Saliendo del Modo Dios.", reply_markup=menu_principal())

# --- LÓGICA DE TEXTO ---
@dp.message(F.text & ~F.text.startswith("/"))
async def procesar_texto_general(msg: Message, state: FSMContext):
    current_state = await state.get_state()
    
    if current_state == AdminChat.en_progreso.state:
        if msg.from_user.id == ADMIN_ID:
            await procesar_con_ia(msg, msg.text, "admin")
        return

    if current_state == Analisis.esperando_cv.state:
        herramienta = "cv"
    elif current_state == Analisis.esperando_carta.state:
        herramienta = "carta"
    elif current_state == Entrevista.en_progreso.state:
        await responder_entrevista(msg, state)
        return
    else:
        herramienta = "cv" # Por defecto
        
    await state.clear()
    if not await verificar_uso(msg, herramienta): return
    await procesar_con_ia(msg, msg.text, herramienta)

# --- FUNCIÓN CENTRAL DE IA ---
async def procesar_con_ia(msg: Message, texto: str, herramienta: str):
    await bot.send_chat_action(chat_id=msg.chat.id, action="typing")
    try:
        if herramienta == "admin":
            prompt = "Estás hablando con el creador. Responde técnico y directo."
        elif herramienta == "carta":
            prompt = "Eres un experto en RRHH. Escribe una carta de presentación persuasiva basada en esta oferta de trabajo."
        else:
            prompt = "Eres un reclutador experto. Analiza este CV y da consejos concisos para mejorarlo."

        response = await client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": texto}]
        )
        await enviar_mensaje_seguro(msg.chat.id, response.choices[0].message.content)
    except Exception as e:
        await msg.answer("Error con la IA.")

# --- LÓGICA DE PDF ---
@dp.message(F.document)
async def procesar_pdf(msg: Message, state: FSMContext):
    if not msg.document.file_name.lower().endswith('.pdf'):
        await msg.answer("Sube solo PDF.")
        return
        
    current_state = await state.get_state()
    herramienta = "carta" if current_state == Analisis.esperando_carta.state else "cv"
    await state.clear()
    
    if not await verificar_uso(msg, herramienta): return
    
    await msg.answer("⏳ Leyendo PDF...")
    await bot.send_chat_action(chat_id=msg.chat.id, action="typing")
    try:
        file = await bot.get_file(msg.document.file_id)
        file_bytes = await bot.download_file(file.file_path)
        reader = PdfReader(io.BytesIO(file_bytes.read()))
        texto = "".join([page.extract_text() or "" for page in reader.pages[:5]])
        if not texto: return await msg.answer("PDF sin texto legible.")
        
        prompt = "Analiza esta oferta de trabajo y escribe una carta." if herramienta == "carta" else "Analiza este CV y da consejos."
        response = await client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": texto[:3000]}]
        )
        await enviar_mensaje_seguro(msg.chat.id, response.choices[0].message.content)
    except Exception as e:
        await msg.answer(f"Error al leer PDF.")

# --- SIMULADOR ---
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
        messages = [{"role": "system", "content": f"Entrevistador para {datos['puesto']}. Evalúa y pregunta."}] + historial
        response = await client.chat.completions.create(model="openai/gpt-oss-120b", messages=messages)
        respuesta_ia = response.choices[0].message.content
        historial.append({"role": "assistant", "content": respuesta_ia})
        if pregunta_num >= 5:
            await enviar_mensaje_seguro(msg.chat.id, f"{respuesta_ia}\n\n✅ **Fin.**")
            await state.clear()
        else:
            await enviar_mensaje_seguro(msg.chat.id, respuesta_ia)
            await state.update_data(pregunta_num=pregunta_num + 1, historial=historial)
    except Exception as e:
        await msg.answer("Error.")

# --- COBRO PAQUETE COMPLETO ---
async def cobrar_paquete_completo(uid):
    await bot.send_invoice(
        chat_id=uid, 
        title="Acceso Premium Ilimitado (Todo)", 
        description="Desbloquea TODAS las herramientas sin límites para siempre.", 
        payload="premium_unlimited", 
        provider_token="", 
        currency="XTR", 
        prices=[LabeledPrice(label="Premium (Todo incluido)", amount=300)] # 300 Stars = ~6 USD
    )

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def pago_exitoso(msg: Message):
    uid = msg.from_user.id
    payload = msg.successful_payment.invoice_payload
    
    async with db_pool.acquire() as conn:
        if payload == "premium_unlimited":
            await conn.execute("UPDATE usuarios SET pago_activo = TRUE WHERE user_id = $1", uid)
            await msg.answer("¡Pago recibido! 🎉 Ya eres **Premium**. Tienes acceso ilimitado a TODAS las herramientas.", reply_markup=menu_principal())
        elif payload.startswith("buy_"):
            herramienta = payload.replace("buy_", "")
            columna = f"pago_{herramienta}"
            await conn.execute(f"UPDATE usuarios SET {columna} = TRUE WHERE user_id = $1", uid)
            await msg.answer(f"¡Pago recibido! 🎉 Has desbloqueado esta herramienta con éxito.", reply_markup=menu_principal())

# --- PRINCIPAL BLINDADO ---
async def main():
    global db_pool
    print("Iniciando bot...")
    while True:
        try:
            print("Intentando conectar a PostgreSQL...")
            db_pool = await asyncpg.create_pool(DATABASE_URL)
            async with db_pool.acquire() as conn:
                # Crear tabla si no existe
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS usuarios (
                        user_id BIGINT PRIMARY KEY,
                        pago_activo BOOLEAN DEFAULT FALSE,
                        usos_gratis INTEGER DEFAULT 2,
                        pago_cv BOOLEAN DEFAULT FALSE,
                        pago_carta BOOLEAN DEFAULT FALSE,
                        pago_entrevista BOOLEAN DEFAULT FALSE,
                        pago_empleos BOOLEAN DEFAULT FALSE
                    )
                ''')
                # Añadir columnas nuevas por si la tabla ya existía
                await conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS pago_cv BOOLEAN DEFAULT FALSE;")
                await conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS pago_carta BOOLEAN DEFAULT FALSE;")
                await conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS pago_entrevista BOOLEAN DEFAULT FALSE;")
                await conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS pago_empleos BOOLEAN DEFAULT FALSE;")
                
            print("✅ DB conectada y actualizada. Tabla lista.")
            break
        except Exception as e:
            print(f"❌ Error conectando a la DB: {e}. Reintentando en 5 segundos...")
            await asyncio.sleep(5)

    await bot.delete_webhook(drop_pending_updates=True) 
    print("✅ Súper Bot encendido...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    keep_alive()
    asyncio.run(main())