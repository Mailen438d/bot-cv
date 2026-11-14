import asyncio
import os
import threading
import io
import httpx
from flask import Flask
from pypdf import PdfReader
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, LabeledPrice, PreCheckoutQuery, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from groq import AsyncGroq

# ==========================================
# CONFIGURACIÓN Y LLAVES
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
client = AsyncGroq(api_key=GROQ_API_KEY)

# ==========================================
# 🚨 PON TU ID DE TELEGRAM AQUÍ ABAJO (Sin comillas)
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
# ----------------------------------

usuarios = {}

# --- ESTADOS ---
class Entrevista(StatesGroup):
    esperando_puesto = State()
    en_progreso = State()

class BuscadorEmpleo(StatesGroup):
    esperando_palabra = State()
    esperando_pais = State()

class AdminChat(StatesGroup):
    en_progreso = State()

# --- MENÚ PRINCIPAL ---
def menu_principal():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Analizar mi CV", callback_data="menu_cv")],
        [InlineKeyboardButton(text="✉️ Crear Carta de Presentación", callback_data="menu_carta")],
        [InlineKeyboardButton(text="🎤 Simulador de Entrevista", callback_data="menu_entrevista")],
        [InlineKeyboardButton(text="💼 Buscar Empleos (Filtro por País)", callback_data="menu_empleos")],
        [InlineKeyboardButton(text="⭐ Hacerme Premium (Ilimitado)", callback_data="menu_premium")]
    ])
    return kb

@dp.message(CommandStart())
async def start(msg: Message):
    uid = msg.from_user.id
    if uid not in usuarios:
        usuarios[uid] = {"pago_activo": False, "usos_gratis": 2}
    
    texto = (
        "¡Hola! 💼 Soy tu **Asistente de Carrera Profesional con IA**.\n\n"
        "Selecciona una opción del menú para empezar. Tienes **2 usos gratuitos**.\n"
        "Si quieres acceso ilimitado, hazte Premium."
    )
    await msg.answer(texto, reply_markup=menu_principal(), parse_mode="Markdown")

# --- MANEJADOR DE BOTONES ---
@dp.callback_query(F.data.startswith("menu_"))
async def manejar_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid = callback.from_user.id
    if uid not in usuarios:
        usuarios[uid] = {"pago_activo": False, "usos_gratis": 2}

    accion = callback.data.split("_")[1]

    if accion == "cv":
        await callback.message.answer("📄 Envíame el **texto de tu CV** y te daré consejos para mejorarlo.")
    elif accion == "carta":
        await callback.message.answer("✉️ Envíame la **oferta de trabajo** (el texto) y te escribiré una carta de presentación perfecta.")
    elif accion == "entrevista":
        await callback.message.answer("🎤 ¿Para qué puesto quieres que te entreviste? (Ej: Desarrollador Web, Gerente de Ventas)")
        await state.set_state(Entrevista.esperando_puesto)
    elif accion == "empleos":
        await callback.message.answer("💼 ¿Qué tipo de empleo buscas? (Ej: Programador, Marketing, Soporte)\n\nEscribe la palabra clave:")
        await state.set_state(BuscadorEmpleo.esperando_palabra)
    elif accion == "premium":
        await cobrar_usuario(uid)

# --- FUNCIÓN PARA VERIFICAR PAGOS ---
async def verificar_uso(message: Message):
    uid = message.from_user.id
    if usuarios[uid]["pago_activo"]: return True
    
    if usuarios[uid]["usos_gratis"] > 0:
        usuarios[uid]["usos_gratis"] -= 1
        await message.answer(f"*(Te quedan {usuarios[uid]['usos_gratis']} usos gratis)*", parse_mode="Markdown")
        return True
    else:
        await cobrar_usuario(uid)
        return False

# --- BUSCADOR DE EMPLEOS REAL CON FILTRO DE PAÍS ---
@dp.message(BuscadorEmpleo.esperando_palabra)
async def preguntar_pais(msg: Message, state: FSMContext):
    palabra = msg.text
    await state.update_data(busqueda=palabra)
    await msg.answer(f"🌍 Entendido. Buscas **{palabra}**.\n\nAhora dime, ¿en qué país o región vives? (Ej: España, México, LATAM, USA, Worldwide)")
    await state.set_state(BuscadorEmpleo.esperando_pais)

@dp.message(BuscadorEmpleo.esperando_pais)
async def buscar_empleos_filtrados(msg: Message, state: FSMContext):
    pais = msg.text.lower()
    datos = await state.get_data()
    palabra = datos.get("busqueda", "")
    await state.clear()
    
    if not await verificar_uso(msg): return
        
    await msg.answer(f"🔎 Buscando ofertas de **{palabra}** para **{msg.text}**...")
    
    try:
        async with httpx.AsyncClient() as http_client:
            # Buscamos 30 ofertas para tener de dónde filtrar
            response = await http_client.get(f"https://remotive.com/api/remote-jobs?limit=30&search={palabra}")
            data = response.json()
            
            if not data.get("jobs"):
                await msg.answer("No encontré ofertas para esa palabra. Intenta con otra.")
                return
                
            empleos_encontrados = 0
            
            for job in data["jobs"]:
                loc_oferta = job['candidate_required_location'].lower()
                
                # Lógica de filtrado: Si la oferta es mundial, o contiene el país del usuario
                if "worldwide" in loc_oferta or pais in loc_oferta or "anywhere" in loc_oferta:
                    texto = f"💼 **{job['title']}**\n🏢 {job['company_name']}\n📍 {job['candidate_required_location']}\n🔗 [Aplicar aquí]({job['url']})"
                    await msg.answer(texto, parse_mode="Markdown", disable_web_page_preview=True)
                    empleos_encontrados += 1
                    
                    if empleos_encontrados >= 8: # Mostrar máximo 8
                        break
            
            if empleos_encontrados == 0:
                await msg.answer(f"😔 No encontré ofertas específicas para **{msg.text}**. Prueba buscando 'Worldwide' o 'LATAM'.")
                
    except Exception as e:
        await msg.answer(f"Error al buscar empleos. Intenta de nuevo.")

# --- 🚨 MODO DIOS (ADMIN) ---
@dp.message(Command("modo_admin"))
async def activar_modo_dios(msg: Message, state: FSMContext):
    if msg.from_user.id == ADMIN_ID:
        await state.set_state(AdminChat.en_progreso)
        await msg.answer("👑 **MODO DIOS ACTIVADO.**\n\nAhora puedes hacerme cualquier pregunta (programación, negocios, redacción) sin gastar usos gratis. Para salir, escribe `/salir`.")
    else:
        await msg.answer("No tienes permiso para usar este comando.")

@dp.message(Command("salir"))
async def salir_modo_dios(msg: Message, state: FSMContext):
    if msg.from_user.id == ADMIN_ID:
        await state.clear()
        await msg.answer("Saliendo del Modo Dios. Volviendo al menú normal.", reply_markup=menu_principal())

@dp.message(AdminChat.en_progreso)
async def responder_admin(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    
    await bot.send_chat_action(chat_id=msg.chat.id, action="typing")
    try:
        response = await client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": "Estás hablando con el creador y dueño del bot. Responde de forma directa, técnica y sin filtros de atención al cliente. Ayúdalo con lo que necesite."},
                {"role": "user", "content": msg.text}
            ]
        )
        await msg.answer(response.choices[0].message.content[:4000], parse_mode="Markdown")
    except Exception as e:
        await msg.answer(f"Error: {e}")

# --- LÓGICA DE TEXTO (CV Y CARTAS) ---
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
            messages=[
                {"role": "system", "content": "Eres un experto en RRHH. Si el texto parece un CV, dale consejos de mejora. Si parece una oferta de trabajo, escribe una carta de presentación persuasiva basada en ella. Responde en español, de forma concisa."},
                {"role": "user", "content": msg.text}
            ]
        )
        await msg.answer(response.choices[0].message.content[:4000], parse_mode="Markdown")
    except Exception as e:
        await msg.answer("Error con la IA. Intenta de nuevo.")

# --- LÓGICA DE LEER PDFs ---
@dp.message(F.document)
async def procesar_pdf(msg: Message):
    if not msg.document.file_name.lower().endswith('.pdf'):
        await msg.answer("Por favor, sube solo archivos PDF.")
        return

    if not await verificar_uso(msg): return

    await msg.answer("⏳ Leyendo tu PDF y analizando...")
    await bot.send_chat_action(chat_id=msg.chat.id, action="typing")

    try:
        file = await bot.get_file(msg.document.file_id)
        file_bytes = await bot.download_file(file.file_path)
        reader = PdfReader(io.BytesIO(file_bytes.read()))
        texto = ""
        for page in reader.pages[:5]:
            texto += page.extract_text() or ""

        if not texto:
            await msg.answer("No pude leer el texto de este PDF.")
            return

        response = await client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": "Eres un reclutador experto. Analiza este CV y da consejos concisos para mejorarlo."},
                {"role": "user", "content": texto[:3000]}
            ]
        )
        await msg.answer(response.choices[0].message.content[:4000], parse_mode="Markdown")
    except Exception as e:
        await msg.answer(f"Error al procesar el PDF.")

# --- SIMULADOR DE ENTREVISTA ---
@dp.message(Entrevista.esperando_puesto)
async def iniciar_entrevista(msg: Message, state: FSMContext):
    if not await verificar_uso(msg): return
    
    puesto = msg.text
    await state.update_data(puesto=puesto, pregunta_num=1, historial=[])
    await msg.answer(f"🎤 Perfecto. Vamos a simular una entrevista para **{puesto}**.\n\nPregunta 1: Cuéntame sobre ti y tu experiencia.")
    await state.set_state(Entrevista.en_progreso)

async def responder_entrevista(msg: Message, state: FSMContext):
    datos = await state.get_data()
    pregunta_num = datos.get("pregunta_num", 1)
    historial = datos.get("historial", [])
    historial.append({"role": "user", "content": msg.text})
    
    await bot.send_chat_action(chat_id=msg.chat.id, action="typing")
    try:
        messages = [{"role": "system", "content": f"Eres un entrevistador de RRHH. Estás entrevistando a alguien para el puesto de {datos['puesto']}. Evalúa la respuesta brevemente y haz la siguiente pregunta."}] + historial
        response = await client.chat.completions.create(model="openai/gpt-oss-120b", messages=messages)
        respuesta_ia = response.choices[0].message.content
        historial.append({"role": "assistant", "content": respuesta_ia})
        
        if pregunta_num >= 5:
            await msg.answer(f"{respuesta_ia[:4000]}\n\n✅ **Fin de la simulación.** ¡Buen trabajo!")
            await state.clear()
        else:
            await msg.answer(respuesta_ia[:4000], parse_mode="Markdown")
            await state.update_data(pregunta_num=pregunta_num + 1, historial=historial)
    except Exception as e:
        await msg.answer("Error en la entrevista.")

# --- SISTEMA DE COBRO ---
async def cobrar_usuario(uid):
    await bot.send_invoice(
        chat_id=uid,
        title="Acceso Premium Ilimitado",
        description="Desbloquea CVs, Cartas, Entrevistas y Búsquedas sin límites por 30 días.",
        payload="premium_unlimited",
        provider_token="", 
        currency="XTR",    
        prices=[LabeledPrice(label="Premium", amount=300)]
    )

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def pago_exitoso(msg: Message):
    uid = msg.from_user.id
    usuarios[uid]["pago_activo"] = True
    usuarios[uid]["usos_gratis"] = 9999
    await msg.answer("¡Pago recibido! 🎉 Ya eres **Premium**. Tienes acceso ilimitado.", reply_markup=menu_principal())

async def main():
    print("✅ Súper Bot encendido y listo para operar...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    keep_alive()
    asyncio.run(main())