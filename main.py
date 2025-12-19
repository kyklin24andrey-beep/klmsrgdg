import asyncio, os, random, logging, io, time
from aiohttp import web
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
from huggingface_hub import InferenceClient

# --- ЛОГИРОВАНИЕ ---
logging.basicConfig(level=logging.INFO)
load_dotenv()

# --- ПРОВЕРКА ТОКЕНОВ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN")
PORT = int(os.getenv("PORT", 8080))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
translator = GoogleTranslator(source='auto', target='en')
client = InferenceClient(token=HF_TOKEN)

user_db = {}

# --- ОБНОВЛЕННЫЕ РАБОЧИЕ МОДЕЛИ 2025 ---
MODELS = {
    "🚀 Flux.1 (Лучшая)": "black-forest-labs/FLUX.1-schnell",
    "📸 Realism (Стабильная)": "stabilityai/stable-diffusion-xl-base-1.0",
    "⛩ Anime (Новая)": "cagliostrolab/animagine-xl-3.1",
    "🎨 Dreamshaper (V8)": "Lykon/DreamShaper"
}

STYLES = {
    "🚫 Без стиля": "",
    "🌌 Cyberpunk": "neon lights, cyberpunk, futuristic city background",
    "📸 Realistic": "8k resolution, photorealistic, cinematic lighting, masterpiece",
    "🏮 Studio Ghibli": "anime style, studio ghibli aesthetic, soft painting",
    "💎 Premium Art": "highly detailed, artistic, digital illustration, trending on artstation",
    "🎮 3D Render": "unreal engine 5, octane render, stylized 3d"
}

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_user(uid, name="User"):
    if uid not in user_db:
        user_db[uid] = {
            "mode": "photo", "style": "🚫 Без стиля", "model": "🚀 Flux.1 (Лучшая)",
            "stats": 0, "magic": True, "name": name, "last_gen": 0
        }
    return user_db[uid]

def main_kb(u):
    magic_status = "ON ✅" if u["magic"] else "OFF ❌"
    mode_status = "ФОТО 🖼" if u["mode"] == "photo" else "ВИДЕО 🎬"
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=f"🔄 РЕЖИМ: {mode_status}")],
        [KeyboardButton(text="⚙️ НАСТРОЙКИ"), KeyboardButton(text="📊 ПРОФИЛЬ")],
        [KeyboardButton(text=f"🪄 MAGIC: {magic_status}")]
    ], resize_keyboard=True)

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    u = get_user(message.from_user.id, message.from_user.full_name)
    welcome = f"🔥 **ПРИВЕТ, {message.from_user.first_name}!**\nЯ — твой ИИ-бот. Пиши запрос или используй кнопки!"
    await message.answer(welcome, reply_markup=main_kb(u), parse_mode="Markdown")

@dp.message(F.text == "⚙️ НАСТРОЙКИ")
async def settings_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🤖 Выбрать модель", callback_data="menu_models"))
    builder.row(InlineKeyboardButton(text="🎨 Выбрать стиль", callback_data="menu_styles"))
    await message.answer("🛠 **Настройка ИИ:**", reply_markup=builder.as_markup(), parse_mode="Markdown")

# --- ПОЧИНЕННЫЕ КНОПКИ ВЫБОРА ---

@dp.callback_query(F.data == "menu_models")
async def models_list(call: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    for m in MODELS.keys(): builder.add(InlineKeyboardButton(text=m, callback_data=f"set_mod_{m}"))
    builder.adjust(1)
    await call.message.edit_text("🤖 **Выберите нейросеть:**", reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "menu_styles")
async def styles_list(call: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    for s in STYLES.keys(): builder.add(InlineKeyboardButton(text=s, callback_data=f"set_sty_{s}"))
    builder.adjust(2)
    await call.message.edit_text("🎨 **Выберите стиль:**", reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("set_mod_"))
async def set_model(call: types.CallbackQuery):
    m = call.data.replace("set_mod_", "")
    get_user(call.from_user.id)["model"] = m
    await call.answer(f"✅ Модель {m} выбрана!")
    await call.message.edit_text(f"🤖 Текущая модель: **{m}**", parse_mode="Markdown")

@dp.callback_query(F.data.startswith("set_sty_"))
async def set_style(call: types.CallbackQuery):
    s = call.data.replace("set_sty_", "")
    get_user(call.from_user.id)["style"] = s
    await call.answer(f"✅ Стиль {s} применен!")
    await call.message.edit_text(f"🎨 Текущий стиль: **{s}**", parse_mode="Markdown")

# --- ЛОГИКА ГЕНЕРАЦИИ ---

@dp.message(F.text.startswith("🔄 РЕЖИМ:"))
async def toggle_mode(message: types.Message):
    u = get_user(message.from_user.id)
    u["mode"] = "video" if u["mode"] == "photo" else "photo"
    await message.answer(f"✅ Режим: **{u['mode'].upper()}**", reply_markup=main_kb(u), parse_mode="Markdown")

@dp.message(F.text.startswith("🪄 MAGIC:"))
async def toggle_magic(message: types.Message):
    u = get_user(message.from_user.id)
    u["magic"] = not u["magic"]
    await message.answer(f"🪄 Magic: **{'ВКЛ' if u['magic'] else 'ВЫКЛ'}**", reply_markup=main_kb(u), parse_mode="Markdown")

@dp.message(F.text)
async def handle_gen(message: types.Message):
    if message.text.startswith("/") or "РЕЖИМ" in message.text or "MAGIC" in message.text or "НАСТРОЙКИ" in message.text: return
    
    u = get_user(message.from_user.id)
    status = await message.answer("📡 **Связь с ИИ...**", parse_mode="Markdown")
    
    try:
        prompt_en = translator.translate(message.text)
        if u["magic"]: prompt_en += ", highly detailed, 8k, masterpiece"

        if u["mode"] == "video":
            await status.edit_text("🎬 **Генерация видео...**")
            url = f"https://image.pollinations.ai/prompt/{prompt_en}?model=video"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as r:
                    data = await r.read()
                    await message.answer_video(BufferedInputFile(data, "v.mp4"))
        else:
            await status.edit_text("🎨 **Рисую...**")
            model_path = MODELS.get(u["model"], MODELS["🚀 Flux.1 (Лучшая)"])
            full_prompt = f"{prompt_en}, {STYLES.get(u['style'], '')}"
            
            image = client.text_to_image(full_prompt, model=model_path)
            img_buf = io.BytesIO()
            image.save(img_buf, format='PNG')
            
            u["stats"] += 1
            await message.answer_photo(BufferedInputFile(img_buf.getvalue(), "i.png"), 
                                     caption=f"✅ Готово! Модель: {u['model']}")

        await status.delete()
    except Exception as e:
        logging.error(e)
        await status.edit_text("❌ Ошибка сервера. Попробуйте другой промпт.")

# --- ЗАПУСК ---
async def handle_ping(request): return web.Response(text="OK")

async def main():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
