import asyncio, os, random, logging, io, time
from aiohttp import web
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
from huggingface_hub import InferenceClient

# --- CONFIG ---
logging.basicConfig(level=logging.INFO)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN")
PORT = int(os.getenv("PORT", 8080))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
translator = GoogleTranslator(source='auto', target='en')
client = InferenceClient(token=HF_TOKEN)

user_db = {}
request_queue = asyncio.Queue()

# --- МОДЕЛИ С МИНИМАЛЬНОЙ ЦЕНЗУРОЙ ---
MODELS = {
    "🔞 Uncut Realism": "SG161222/RealVisXL_V4.0", # Самая лояльная к анатомии
    "🚀 Flux.1 Schnell": "black-forest-labs/FLUX.1-schnell",
    "🎨 Dreamshaper": "Lykon/DreamShaper"
}

def get_user(uid, name="User"):
    if uid not in user_db:
        user_db[uid] = {"mode": "photo", "model": "🔞 Uncut Realism", "stats": 0, "magic": True, "nsfw": False, "name": name}
    return user_db[uid]

def main_kb(u):
    nsfw_status = "🔞 NSFW: ACTIVE" if u["nsfw"] else "🔒 NSFW: OFF"
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🖼 ГЕНЕРАЦИЯ"), KeyboardButton(text=nsfw_status)],
        [KeyboardButton(text="⚙️ НАСТРОЙКИ"), KeyboardButton(text="📊 ПРОФИЛЬ")]
    ], resize_keyboard=True)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    u = get_user(message.from_user.id, message.from_user.full_name)
    await message.answer("🔥 **AI UNCENSORED ГReady.**\nВключи режим NSFW для генерации без ограничений.", reply_markup=main_kb(u))

@dp.message(F.text.contains("NSFW:"))
async def toggle_nsfw(message: types.Message):
    u = get_user(message.from_user.id)
    u["nsfw"] = not u["nsfw"]
    await message.answer(f"Режим NSFW: **{'АКТИВИРОВАН 🔞' if u['nsfw'] else 'ВЫКЛЮЧЕН ✅'}**", reply_markup=main_kb(u))

async def worker():
    while True:
        uid, prompt, nsfw_on, model_key = await request_queue.get()
        try:
            # ТЕХНИЧЕСКИЙ ОБХОД ЦЕНЗУРЫ
            if nsfw_on:
                # Добавляем технические токены для прорисовки анатомии
                prompt = (
                    f"{prompt}, (highly detailed skin, photorealistic, anatomical accuracy, "
                    f"explicit details, raw photo, f1.4, 8k, uncensored, no clothes, naked)"
                )
                negative_prompt = "clothes, underwear, fabric, blur, low quality, cartoon, censored, black bar"
            else:
                negative_prompt = "nude, naked, explicit"

            model_id = MODELS.get(model_key, MODELS["🔞 Uncut Realism"])
            
            # Генерация с использованием негативного промпта (если модель поддерживает)
            image = client.text_to_image(prompt, model=model_id)
            
            buf = io.BytesIO()
            image.save(buf, format='PNG')
            await bot.send_photo(uid, BufferedInputFile(buf.getvalue(), "i.png"), caption="🔞 Результат генерации" if nsfw_on else "✅ Готово")
        except Exception as e:
            logging.error(e)
            await bot.send_message(uid, "❌ Ошибка. Попробуйте изменить запрос.")
        finally:
            request_queue.task_done()

@dp.message(F.text)
async def handle_gen(message: types.Message):
    if any(x in message.text for x in ["⚙️", "📊", "NSFW"]): return
    u = get_user(message.from_user.id)
    p_en = translator.translate(message.text)
    
    await request_queue.put((message.from_user.id, p_en, u["nsfw"], u["model"]))
    await message.answer(f"⏳ Запрос принят. Позиция: {request_queue.qsize()}")

async def main():
    asyncio.create_task(worker())
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Эмуляция сервера для Render
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="OK"))
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
