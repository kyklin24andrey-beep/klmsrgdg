import asyncio, os, aiohttp, logging, random, time
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
from aiohttp import web

# --- ИНИЦИАЛИЗАЦИЯ ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN")
PORT = os.getenv("PORT", "8080")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
translator = GoogleTranslator(source='auto', target='en')
session: aiohttp.ClientSession = None

# Хранилище настроек пользователей
user_data = {} 

# Справочники
STYLES = {
    "🚫 Нет": "",
    "💎 Люкс": "luxury aesthetic, elegant, high-end, cinematic lighting",
    "⛩ Аниме": "anime masterwork, studio ghibli style, vibrant colors",
    "📸 Фото": "hyper-realistic, 8k raw photo, soft bokeh, masterpiece",
    "🌌 Киберпанк": "cyberpunk 2077 style, neon glow, futuristic city, sharp",
    "🎨 Масло": "classical oil painting, textured canvas, van gogh strokes"
}

HF_MODELS = [
    "black-forest-labs/FLUX.1-schnell",
    "stabilityai/stable-diffusion-3.5-large",
    "SG161222/Realistic_Vision_V6.0_B1_noVAE",
    "prompthero/openjourney-v4",
    "Lykon/DreamShaper"
]

# --- КЛАВИАТУРЫ ---

def get_main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🖼 Создать Фото"), KeyboardButton(text="🎬 Создать Видео")],
        [KeyboardButton(text="🎭 Стили"), KeyboardButton(text="🛠 Инструменты")],
        [KeyboardButton(text="📊 Моя Статистика")]
    ], resize_keyboard=True)

def get_tools_kb():
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🪄 Magic Prompt", callback_data="tool_magic"))
    builder.add(InlineKeyboardButton(text="🧹 Удалить фон", callback_data="tool_nobg"))
    builder.add(InlineKeyboardButton(text="🔍 Upscale (HQ)", callback_data="tool_upscale"))
    builder.adjust(1)
    return builder.as_markup()

# --- ЯДРО ГЕНЕРАЦИИ ---

async def translate_text(text):
    try: return translator.translate(text)
    except: return text

async def get_image_router(prompt, style_name):
    # Добавляем стиль
    full_prompt = f"{prompt}, {STYLES.get(style_name, '')}"
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    
    # 1. Пробуем Hugging Face Router
    for model_path in HF_MODELS:
        try:
            url = f"https://api-inference.huggingface.co/models/{model_path}"
            async with session.post(url, json={"inputs": full_prompt}, headers=headers, timeout=45) as r:
                if r.status == 200:
                    return await r.read(), f"HF: {model_path.split('/')[-1]}"
        except: continue
        
    # 2. Резервный канал (Pollinations)
    try:
        url = f"https://image.pollinations.ai/prompt/{full_prompt}?nologo=true&seed={random.randint(0,999)}"
        async with session.get(url, timeout=60) as r:
            if r.status == 200: return await r.read(), "Pollinations (Flux)"
    except: return None, None

async def get_video(prompt):
    # Экспериментальный эндпоинт для видео
    url = f"https://image.pollinations.ai/prompt/{prompt}?model=video&seed={random.randint(0,999)}"
    try:
        async with session.get(url, timeout=180) as r:
            if r.status == 200: return await r.read()
    except: return None

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    user_data[uid] = {"mode": "photo", "style": "🚫 Нет", "count": 0}
    await message.answer("🚀 **Добро пожаловать в AI-Комбайн 2025!**\n\nЯ использую систему роутинга между 7 нейросетями для стабильной работы.\n\nВыбери режим на кнопках ниже:", 
                         reply_markup=get_main_kb(), parse_mode="Markdown")

@dp.message(F.text == "🎭 Стили")
async def style_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    for s in STYLES.keys():
        builder.add(InlineKeyboardButton(text=s, callback_data=f"style_{s}"))
    builder.adjust(2)
    await message.answer("Выберите визуальный стиль для ваших работ:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("style_"))
async def set_style(call: types.CallbackQuery):
    style = call.data.replace("style_", "")
    user_data[call.from_user.id]["style"] = style
    await call.message.edit_text(f"✅ Стиль установлен на: **{style}**", parse_mode="Markdown")

@dp.message(F.text == "🛠 Инструменты")
async def tools_menu(message: types.Message):
    await message.answer("Дополнительные AI-функции:", reply_markup=get_tools_kb())

@dp.message(F.text == "🖼 Создать Фото")
async def set_photo(message: types.Message):
    user_data[message.from_user.id]["mode"] = "photo"
    await message.answer("📸 Режим фото активен. Опишите картинку:")

@dp.message(F.text == "🎬 Создать Видео")
async def set_video(message: types.Message):
    user_data[message.from_user.id]["mode"] = "video"
    await message.answer("📹 Режим видео активен. Напишите сценарий для ролика (до 5 сек):")

@dp.message(F.text)
async def handle_input(message: types.Message):
    uid = message.from_user.id
    if uid not in user_data: user_data[uid] = {"mode": "photo", "style": "🚫 Нет", "count": 0}
    
    # Игнорируем кнопки
    if message.text in ["🖼 Создать Фото", "🎬 Создать Видео", "🎭 Стили", "🛠 Инструменты", "📊 Моя Статистика"]: return

    conf = user_data[uid]
    status = await message.answer("🧪 **Нейросеть начала работу...**", parse_mode="Markdown")
    
    prompt_en = await translate_text(message.text)
    conf["count"] += 1

    if conf["mode"] == "video":
        await status.edit_text("🎬 **Рендеринг видео (до 2 мин)...**")
        v_data = await get_video(prompt_en)
        if v_data:
            await message.answer_video(BufferedInputFile(v_data, "v.mp4"), caption="🎬 Готово!")
            await status.delete()
        else:
            await status.edit_text("❌ Ошибка видео-движка. Попробуйте еще раз.")
    else:
        img_data, model_info = await get_image_router(prompt_en, conf["style"])
        if img_data:
            await message.answer_photo(
                BufferedInputFile(img_data, "i.png"), 
                caption=f"✅ **Результат**\n🎨 Стиль: `{conf['style']}`\n🤖 Модель: `{model_info}`",
                parse_mode="Markdown"
            )
            await status.delete()
        else:
            await status.edit_text("❌ Все модели сейчас заняты. Повторите запрос через минуту.")

# --- WEB SERVER (HEALTH CHECK) ---
async def handle_hc(request): return web.Response(text="Bot Alive")

async def main():
    global session
    session = aiohttp.ClientSession()
    # Запуск веб-сервера для Render
    app = web.Application()
    app.router.add_get("/", handle_hc)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(PORT)).start()
    
    print(">>> BOT IS ONLINE")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
