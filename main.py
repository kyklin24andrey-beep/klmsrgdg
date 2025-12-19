import asyncio
import os
import random
import logging
import io
from aiohttp import web
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
from huggingface_hub import InferenceClient

# --- НАСТРОЙКИ И ЛОГИ ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

# Проверка переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN")
PORT = int(os.getenv("PORT", 8080))

if not BOT_TOKEN or not HF_TOKEN:
    logger.error("КРИТИЧЕСКАЯ ОШИБКА: Токены BOT_TOKEN или HF_TOKEN не найдены в переменных окружения!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
translator = GoogleTranslator(source='auto', target='en')

# Список топовых моделей для роутинга
MODELS = [
    "black-forest-labs/FLUX.1-schnell",
    "stabilityai/stable-diffusion-3.5-large",
    "XLabs-AI/Flux-Realism-LoRA", 
    "RunDiffusion/Juggernaut-XL-v9"
]

STYLES = {
    "🚫 Без стиля": "",
    "💎 Фотореализм": "hyper-realistic, 8k, raw photo, masterpieces, photography, sharp focus",
    "⛩ Аниме": "anime style, vibrant colors, studio ghibli aesthetic, high quality digital art",
    "🌌 Киберпанк": "cyberpunk aesthetic, neon lighting, futuristic, sharp details",
    "🎨 Масло": "oil painting texture, classical art masterpiece",
    "🎮 Игровой": "unreal engine 5 render, video game style, 3d, volumetric lighting"
}

# Инициализация клиента HF
client = InferenceClient(token=HF_TOKEN)

# Данные пользователей в памяти
user_settings = {}

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_user_config(uid):
    """Безопасное получение настроек пользователя без KeyError"""
    if uid not in user_settings:
        user_settings[uid] = {
            "style": "🚫 Без стиля", 
            "mode": "photo",
            "last_time": 0
        }
    return user_settings[uid]

# --- КЛАВИАТУРЫ ---

def main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🖼 Создать Фото"), KeyboardButton(text="🎬 Создать Видео")],
        [KeyboardButton(text="🎭 Выбрать Стиль"), KeyboardButton(text="📊 Инфо")],
    ], resize_keyboard=True)

# --- ЯДРО ГЕНЕРАЦИИ ---

async def generate_image(prompt, user_style):
    full_prompt = f"{prompt}, {STYLES.get(user_style, '')}"
    for model in MODELS:
        try:
            # Генерация через Inference Providers
            image = client.text_to_image(full_prompt, model=model)
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='PNG')
            return img_byte_arr.getvalue(), model
        except Exception as e:
            logger.warning(f"Модель {model} занята, пробую следующую...")
            continue
    return None, None

async def generate_video(prompt):
    url = f"https://image.pollinations.ai/prompt/{prompt}?model=video&seed={random.randint(1, 999999)}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=150) as resp:
                if resp.status == 200:
                    return await resp.read()
        except Exception as e:
            logger.error(f"Ошибка видео: {e}")
            return None

# --- ОБРАБОТЧИКИ СОБЫТИЙ ---

@dp.message(Command("start"))
async def start(message: types.Message):
    get_user_config(message.from_user.id) # Инициализация
    await message.answer(
        "🔥 **Бот ИИ БЕЗ ЦЕНЗУРЫ запущен!**\n\nЯ использую систему роутинга между топовыми нейросетями. Выбирай режим и твори!",
        reply_markup=main_kb(), parse_mode="Markdown"
    )

@dp.message(F.text == "🎭 Выбрать Стиль")
async def style_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    for s in STYLES.keys():
        builder.add(InlineKeyboardButton(text=s, callback_data=f"set_style_{s}"))
    builder.adjust(2)
    await message.answer("Выберите визуальный стиль:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("set_style_"))
async def set_style(call: types.CallbackQuery):
    style = call.data.replace("set_style_", "")
    get_user_config(call.from_user.id)["style"] = style
    await call.message.edit_text(f"✅ Установлен стиль: **{style}**", parse_mode="Markdown")

@dp.message(F.text == "🖼 Создать Фото")
async def mode_photo(message: types.Message):
    get_user_config(message.from_user.id)["mode"] = "photo"
    await message.answer("📸 Режим ФОТО активен. Пришлите описание:")

@dp.message(F.text == "🎬 Создать Видео")
async def mode_video(message: types.Message):
    get_user_config(message.from_user.id)["mode"] = "video"
    await message.answer("📹 Режим ВИДЕО активен. Опишите сюжет для ролика:")

@dp.message(F.text == "📊 Инфо")
async def show_info(message: types.Message):
    await message.answer("🤖 Бот работает на базе **Hugging Face Inference**.\nПоддержка видео: **Pollinations AI**.\nХостинг: **Render**.")

@dp.message(F.text)
async def handle_request(message: types.Message):
    uid = message.from_user.id
    conf = get_user_config(uid)
    
    if message.text in ["🖼 Создать Фото", "🎬 Создать Видео", "🎭 Выбрать Стиль", "📊 Инфо"]:
        return

    # Защита от спама (cooldown 3 сек)
    if time.time() - conf["last_time"] < 3:
        return await message.answer("⚠️ Не частите! Подождите пару секунд.")
    conf["last_time"] = time.time()

    wait_msg = await message.answer("🧪 **ИИ начал работу...**", parse_mode="Markdown")
    
    try:
        # Авто-перевод
        prompt_en = translator.translate(message.text)
        
        if conf["mode"] == "video":
            await wait_msg.edit_text("📽 **Рендеринг видео (это долго)...**")
            data = await generate_video(prompt_en)
            if data:
                await message.answer_video(BufferedInputFile(data, filename="ai_vid.mp4"), caption="🎬 Ваше видео!")
                await wait_msg.delete()
            else:
                await wait_msg.edit_text("❌ Ошибка генерации видео. Попробуйте позже.")
        
        else:
            img_data, model_name = await generate_image(prompt_en, conf["style"])
            if img_data:
                await message.answer_photo(
                    BufferedInputFile(img_data, filename="ai_img.png"),
                    caption=f"✅ Готово!\n🤖 Модель: `{model_name}`\n🎭 Стиль: `{conf['style']}`",
                    parse_mode="Markdown"
                )
                await wait_msg.delete()
            else:
                await wait_msg.edit_text("❌ Сервера нейросетей перегружены. Попробуйте с другим стилем.")

    except Exception as e:
        logger.error(f"Ошибка в handle_request: {e}")
        await wait_msg.edit_text("🔧 Технический сбой. Попробуйте другой промпт.")

import time # Нужен для cooldown

# --- ВЕБ-СЕРВЕР (HEALTH CHECK) ---

async def handle_ping(request):
    return web.Response(text="I am alive!")

async def main():
    # 1. Запуск сервера для Render
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    # 2. Очистка старых обновлений (исправляет ConflictError)
    await bot.delete_webhook(drop_pending_updates=True)
    
    # 3. Запуск
    logger.info(f"Бот запущен на порту {PORT}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
