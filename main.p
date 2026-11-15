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
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from groq import AsyncGroq

# ==========================================
# CONFIGURACIÓN Y LLAVES (Se leen de Render)
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
client = AsyncGroq(api_key=GROQ_API_KEY)

# ==========================================
# 🚨 PON TU ID DE TELEGRAM AQUÍ (Sin comillas)
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

# Variable global para la base de datos
db_pool = None

# --- ESTADOS ---
class Entrevista(StatesGroup):
    esperando_puesto = State()
    en_progreso = State()

class BuscadorEmpleo(StatesGroup):
    esperando_palabra = State()
    esperando_pais = State()

class AdminChat(StatesGroup):
    en_progreso = State()

# --- 🛡️ FUNCIÓN MAESTRA PARA ENVIAR MENSAJES ---
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
        [InlineKeyboardButton(text="💼 Buscar Empleos (Valor: $5)", callback_data="menu_empleos")],
        [InlineKeyboardButton(text="⭐ Obtener TODO por 300 Stars", callback_data="menu_premium")]
    ])
    return kb

@dp.message(CommandStart())
async def start(msg: Message):
    uid = msg.from_user.id
    
    async with db_pool.acquire() as conn:
        usuario = await conn.fetchrow("SELECT * FROM usuarios WHERE user_id = $1", uid)
        if not usuario:
            await conn.execute("INSERT INTO usuarios (user_id, pago_activo, usos_gratis) VALUES ($1, $2, $3)", uid, False, 2)
    
    texto = (
        "¡Hola! 💼 Soy tu **Asistente de Carrera Profesional con IA**.\n\n"
        "Selecciona una opción del menú. Tienes **2 usos gratuitos** para probar.\n"
        "*(Nota: Usar estas herramientas con profesionales cuesta más de $25. Aquí puedes tenerlas todas por menos de $4).*"
    )
    await msg.answer(texto, reply_markup=menu_principal(), parse_mode="Markdown")

# --- MANEJADOR DE BOTONES ---
@dp.callback_query(F.data.startswith("menu_"))
async def manejar_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    accion = callback.data.split("_")[1]

    if accion == "cv":
        await callback.message.answer("📄 Envíame el **texto de tu CV** y te daré consejos de un experto para mejorarlo.")
    elif accion == "carta":
        await callback.message.answer("✉️ Envíame la **oferta de trabajo** (el texto) y te escribiré una carta de presentación persuasiva.")
    elif accion == "entrevista":
        await callback.message.answer("🎤 ¿Para qué puesto quieres que te entreviste? (Ej: Desarrollador Web, Gerente de Ventas)")
        await state.set_state(Entrevista.esperando_puesto)
    elif accion == "empleos":
        await callback.message.answer("💼 ¿Qué tipo de empleo buscas? (Ej: Programador, Marketing, Soporte)\n\nEscribe la palabra clave:")
        await state.set_state(BuscadorEmpleo.esperando_palabra)
    elif accion == "premium":
        await cobrar_usuario(callback.from_user.id)

# --- 🛡️ VERIFICACIÓN DE USOS CON BASE DE DATOS ---
async def verificar_uso(message: Message):
    uid = message.from_user.id
    
    async with db_pool.acquire() as conn:
        usuario = await conn.fetchrow("SELECT * FROM usuarios WHERE user_id = $1", uid)
        
        if not usuario:
            await conn.execute("INSERT INTO usuarios (user_id, pago_activo, usos_gratis) VALUES ($1, $2, $3)", uid, False, 2)
            return True

        if usuario['pago_activo']:
            return True
        
        if usuario['usos_gratis'] > 0:
            nuevos_usos = usuario['usos_gratis'] - 1
            await conn.execute("UPDATE usuarios SET usos_gratis = $1 WHERE user_id = $2", nuevos_usos, uid)
            await message.answer(f"*(Te quedan {nuevos_usos} usos gratis)*", parse_mode="Markdown")
            return True
        else:
            await cobrar_usuario(uid)
            return False

# --- BUSCADOR DE EMPLEOS ---
@dp.message(BuscadorEmpleo.esperando_palabra)
async def preguntar_pais(msg: Message, state: FSMContext):
    palabra = msg.text
    await state.update_data(busqueda=palabra)
    await msg.answer(f"🌍 Entendido. Buscas **{palabra}**.\n\nAhora dime, ¿en qué país o región vives? (Ej: España, México, LATAM, USA)")
    await state.set_state(BuscadorEmpleo.esperando_pais)

@dp.message(BuscadorEmpleo.esperando_pais)
async def buscar_empleos_filtrados(msg: Message, state: FSMContext):
    pais = msg.text.lower()
    datos = await state.get_data()
    palabra = datos.get("busqueda", "")
    await state.clear()
    
    if not await verificar_uso(msg): return
        
    await msg.answer(f"🔎 Buscando ofertas de **{palabra}** para **{msg.text}**...", parse_mode="Markdown")
    
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(f"https://remotive.com/api/remote-jobs?limit=30&search={palabra}")
            data = response.json()
            
            if not data.get("jobs"):
                await msg.answer("No encontré ofertas para esa palabra. Intenta con otra.")
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
        await msg.answer("👑 **MODO DIOS ACTIVADO.**\n\nPregúntame lo que quieras. Para salir, escribe `/salir`.")
    else:
        await msg.answer("No tienes permiso.")

@dp.message(Command("salir"))
async def salir_modo_dios(msg: Message, state: FSMContext):
    if msg.from_user.id == ADMIN_ID:
        await state.clear()
        await msg.answer("Saliendo del Modo Dios.", reply_markup=menu_principal())

@dp.message(AdminChat.en_progreso)
async def responder_admin(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    await bot.send_chat_action(chat_id=msg.chat.id, action="typing")
    try:
        response = await client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "system", "content": "Estás hablando con el creador. Responde técnico y directo."}, {"role": "user", "content": msg.text}]
        )
        await enviar_mensaje_seguro(msg.chat.id, response.choices[0].message.content)
    except Exception as e:
        await msg.answer(f"Error: {e}")

# --- LÓGICA DE TEXTO ---
@dp.message(F.text & ~F.text.startswith("/"))
async def procesar_texto_general(msg: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state == Entrevista.en_progreso.state:
        await responder_entrevista(msg, state)
        return

    if not await verificar_uso(msg): return
    await bot.send_chat_action(chat_id=msg.chat.id, action="typing")
    try:
        response = await client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "system", "content": "Eres experto en RRHH. Analiza el CV o escribe una carta de presentación. Conciso."}, {"role": "user", "content": msg.text}]
        )
        await enviar_mensaje_seguro(msg.chat.id, response.choices[0].message.content)
    except Exception as e:
        await msg.answer("Error con la IA.")

# --- LÓGICA DE PDF ---
@dp.message(F.document)
async def procesar_pdf(msg: Message):
    if not msg.document.file_name.lower().endswith('.pdf'):
        await msg.answer("Sube solo PDF.")
        return
    if not await verificar_uso(msg): return
    await msg.answer("⏳ Leyendo PDF...")
    await bot.send_chat_action(chat_id=msg.chat.id, action="typing")
    try:
        file = await bot.get_file(msg.document.file_id)
        file_bytes = await bot.download_file(file.file_path)
        reader = PdfReader(io.BytesIO(file_bytes.read()))
        texto = "".join([page.extract_text() or "" for page in reader.pages[:5]])
        if not texto: return await msg.answer("PDF sin texto legible.")
        response = await client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "system", "content": "Analiza este CV y da consejos."}, {"role": "user", "content": texto[:3000]}]
        )
        await enviar_mensaje_seguro(msg.chat.id, response.choices[0].message.content)
    except Exception as e:
        await msg.answer(f"Error al leer PDF.")

# --- SIMULADOR ---
@dp.message(Entrevista.esperando_puesto)
async def iniciar_entrevista(msg: Message, state: FSMContext):
    if not await verificar_uso(msg): return
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

# --- COBRO ---
async def cobrar_usuario(uid):
    await bot.send_invoice(chat_id=uid, title="Premium Ilimitado", description="Acceso total 30 días.", payload="premium", provider_token="", currency="XTR", prices=[LabeledPrice(label="Premium", amount=300)])

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def pago_exitoso(msg: Message):
    uid = msg.from_user.id
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE usuarios SET pago_activo = TRUE WHERE user_id = $1", uid)
    await msg.answer("¡Pago recibido! 🎉 Ya eres Premium.", reply_markup=menu_principal())

# --- PRINCIPAL BLINDADO ---
async def main():
    global db_pool
    print("Iniciando bot...")
    
    while True:
        try:
            print("Intentando conectar a PostgreSQL...")
            db_pool = await asyncpg.create_pool(DATABASE_URL)
            async with db_pool.acquire() as conn:
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS usuarios (
                        user_id BIGINT PRIMARY KEY,
                        pago_activo BOOLEAN DEFAULT FALSE,
                        usos_gratis INTEGER DEFAULT 2
                    )
                ''')
            print("✅ DB conectada. Tabla lista.")
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