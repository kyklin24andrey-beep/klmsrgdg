import asyncio
import os
import random
import logging
from aiohttp import web
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
from huggingface_hub import InferenceClient

# --- НАСТРОЙКИ ---
logging.basicConfig(level=logging.INFO)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN") # Ваш новый Fine-grained токен
PORT = int(os.getenv("PORT", 8080))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
translator = GoogleTranslator(source='auto', target='en')

# Список топовых моделей для роутинга (Text-to-Image)
MODELS = [
    "black-forest-labs/FLUX.1-schnell",
    "stabilityai/stable-diffusion-3.5-large",
    "XLabs-AI/Flux-Realism-LoRA", 
    "RunDiffusion/Juggernaut-XL-v9",
    "prompthero/openjourney"
]

# Стили для промптов
STYLES = {
    "🚫 Без стиля": "",
    "💎 Фотореализм": "hyper-realistic, 8k, highly detailed, masterpieces, photography, sharp focus",
    "⛩ Аниме": "anime style, vibrant colors, studio ghibli aesthetic, high quality digital art",
    "🌌 Киберпанк": "cyberpunk aesthetic, neon lighting, futuristic, high contrast, detailed",
    "🎨 Масло": "oil painting texture, visible brushstrokes, classical art masterpiece",
    "🎮 Игровой": "unreal engine 5 render, video game style, 3d, volumetric lighting"
}

# Инициализация клиента HF
client = InferenceClient(token=HF_TOKEN)

# Данные пользователей (в памяти)
user_settings = {}

# --- КЛАВИАТУРЫ ---
def main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🖼 Создать Фото"), KeyboardButton(text="🎬 Создать Видео")],
        [KeyboardButton(text="🎭 Выбрать Стиль"), KeyboardButton(text="📊 Статус")],
    ], resize_keyboard=True)

# --- ЛОГИКА ГЕНЕРАЦИИ ---

async def generate_image(prompt, user_style):
    full_prompt = f"{prompt}, {STYLES.get(user_style, '')}"
    
    # Пытаемся пройтись по списку моделей, если одна занята
    for model in MODELS:
        try:
            # Используем новый метод Inference Providers
            image = client.text_to_image(full_prompt, model=model)
            # Конвертируем PIL Image в байты
            import io
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='PNG')
            return img_byte_arr.getvalue(), model
        except Exception as e:
            logging.warning(f"Модель {model} выдала ошибку: {e}. Пробую следующую...")
            continue
    return None, None

async def generate_video(prompt):
    # Видео генерируем через Pollinations (самый быстрый бесплатный API для видео сейчас)
    url = f"https://image.pollinations.ai/prompt/{prompt}?model=video&seed={random.randint(1, 999999)}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=120) as resp:
                if resp.status == 200:
                    return await resp.read()
        except:
            return None

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def start(message: types.Message):
    user_settings[message.from_user.id] = {"style": "🚫 Без стиля", "mode": "photo"}
    await message.answer(
        "🔥 **Бот запущен и готов к работе!**\n\nИспользую технологию **HF Inference Providers 2025**.\nВыбирай режим и пиши запрос!",
        reply_markup=main_kb(), parse_mode="Markdown"
    )

@dp.message(F.text == "🎭 Выбрать Стиль")
async def style_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    for s in STYLES.keys():
        builder.add(InlineKeyboardButton(text=s, callback_data=f"set_style_{s}"))
    builder.adjust(2)
    await message.answer("Выберите стиль для генерации:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("set_style_"))
async def set_style(call: types.CallbackQuery):
    style = call.data.replace("set_style_", "")
    user_settings[call.from_user.id]["style"] = style
    await call.message.edit_text(f"✅ Установлен стиль: **{style}**", parse_mode="Markdown")

@dp.message(F.text == "🖼 Создать Фото")
async def mode_photo(message: types.Message):
    user_settings[message.from_user.id]["mode"] = "photo"
    await message.answer("📸 Принято. Теперь просто напиши, что нарисовать (на любом языке):")

@dp.message(F.text == "🎬 Создать Видео")
async def mode_video(message: types.Message):
    user_settings[message.from_user.id]["mode"] = "video"
    await message.answer("📹 Видео-режим активен. Напиши описание для короткого ролика:")

@dp.message(F.text)
async def handle_request(message: types.Message):
    uid = message.from_user.id
    if uid not in user_settings:
        user_settings[uid] = {"style": "🚫 Без стиля", "mode": "photo"}
    
    if message.text in ["🖼 Создать Фото", "🎬 Создать Видео", "🎭 Выбрать Стиль", "📊 Статус"]:
        return

    wait_msg = await message.answer("⏳ **Нейросеть думает...** Ожидайте результата.", parse_mode="Markdown")
    
    try:
        # Перевод
        prompt_en = translator.translate(message.text)
        mode = user_settings[uid]["mode"]
        
        if mode == "photo":
            img_data, model_name = await generate_image(prompt_en, user_settings[uid]["style"])
            if img_data:
                await message.answer_photo(
                    BufferedInputFile(img_data, filename="ai_result.png"),
                    caption=f"✅ Готово!\n🤖 Модель: `{model_name}`\n🎭 Стиль: `{user_settings[uid]['style']}`",
                    parse_mode="Markdown"
                )
            else:
                await message.answer("❌ Извини, все сервера сейчас перегружены. Попробуй через минуту.")
        
        elif mode == "video":
            video_data = await generate_video(prompt_en)
            if video_data:
                await message.answer_video(
                    BufferedInputFile(video_data, filename="ai_video.mp4"),
                    caption="🎬 Видео успешно создано!"
                )
            else:
                await message.answer("❌ Ошибка при создании видео.")

    except Exception as e:
        logging.error(e)
        await message.answer("🔧 Произошла техническая ошибка. Попробуй позже.")
    finally:
        await wait_msg.delete()

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def handle(request):
    return web.Response(text="Bot is running!")

async def main():
    # Запуск Health Check сервера
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    
    # Запуск бота
    print("Бот успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
