import asyncio, os, logging, io, time, gc
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
from huggingface_hub import InferenceClient

# --- ИНИЦИАЛИЗАЦИЯ ---
logging.basicConfig(level=logging.INFO)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN")
PORT = int(os.getenv("PORT", 8080))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
translator = GoogleTranslator(source='auto', target='en')
client = InferenceClient(token=HF_TOKEN)

# База данных (в памяти)
user_db = {}
# Очередь запросов для контроля нагрузки на RAM
request_queue = asyncio.Queue()

# Список моделей
MODELS = {
    "💎 Realism XL": "SG161222/RealVisXL_V4.0",
    "⚡ Flux Speed": "black-forest-labs/FLUX.1-schnell",
    "🎨 Artistic": "Lykon/DreamShaper"
}

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_user(uid, name="User"):
    if uid not in user_db:
        user_db[uid] = {"model": "💎 Realism XL", "nsfw": False, "name": name, "count": 0}
    return user_db[uid]

def main_kb(uid):
    u = get_user(uid)
    nsfw_btn = "🔞 NSFW: ON" if u["nsfw"] else "🔒 NSFW: OFF"
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🖼 Сгенерировать"), KeyboardButton(text=nsfw_btn)],
        [KeyboardButton(text="⚙️ Сменить модель"), KeyboardButton(text="📊 Статистика")]
    ], resize_keyboard=True)

# --- ENGINE (СЕРДЦЕ БОТА) ---

async def image_worker():
    """Фоновый воркер для обработки очереди (экономит RAM на Render)"""
    while True:
        uid, user_prompt, nsfw_on, model_key = await request_queue.get()
        try:
            u = get_user(uid)
            model_id = MODELS.get(model_key, MODELS["💎 Realism XL"])
            
            # Авто-улучшение промпта (Prompt Magic)
            enhancement = "highres, 8k, highly detailed, masterpiece, sharp focus, cinematic lighting"
            if nsfw_on:
                final_prompt = f"{user_prompt}, uncensored, explicit anatomy, naked, highly detailed skin, {enhancement}"
            else:
                final_prompt = f"{user_prompt}, highly detailed, {enhancement}"

            # Сообщаем пользователю, что начали рисовать
            status_msg = await bot.send_message(uid, f"🎨 Рисую через `{model_key}`...", parse_mode="Markdown")
            await bot.send_chat_action(uid, "upload_photo")

            # Сама генерация
            image = client.text_to_image(final_prompt, model=model_id)
            
            # Оптимизация для Render (сжатие JPEG для экономии памяти)
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=90)
            output.seek(0)

            # Отправка
            u["count"] += 1
            await bot.send_photo(
                uid, 
                BufferedInputFile(output.read(), filename="art.jpg"),
                caption=f"✨ **Готово!**\nМодель: `{model_key}`\nРежим: `{'NSFW 🔞' if nsfw_on else 'Safe ✅'}`",
                parse_mode="Markdown"
            )
            await status_msg.delete()

        except Exception as e:
            logging.error(f"Worker Error: {e}")
            await bot.send_message(uid, "❌ Ошибка API. Попробуйте другой промпт или смените модель.")
        finally:
            # Очистка памяти после каждой итерации
            gc.collect() 
            request_queue.task_done()

# --- ОБРАБОТЧИКИ СООБЩЕНИЙ ---

@dp.message(Command("start"))
async def start(message: types.Message):
    u = get_user(message.from_user.id, message.from_user.full_name)
    await message.answer(
        f"🚀 **AI-Генератор активен!**\n\nПришли мне текст, и я превращу его в шедевр.\nТекущая модель: `{u['model']}`",
        reply_markup=main_kb(message.from_user.id),
        parse_mode="Markdown"
    )

@dp.message(F.text.contains("NSFW:"))
async def toggle_nsfw(message: types.Message):
    u = get_user(message.from_user.id)
    u["nsfw"] = not u["nsfw"]
    status = "ВКЛЮЧЕН 🔞" if u["nsfw"] else "ВЫКЛЮЧЕН ✅"
    await message.answer(f"Режим NSFW теперь: **{status}**", reply_markup=main_kb(message.from_user.id), parse_mode="Markdown")

@dp.message(F.text == "⚙️ Сменить модель")
async def next_model(message: types.Message):
    u = get_user(message.from_user.id)
    m_list = list(MODELS.keys())
    curr_idx = m_list.index(u["model"])
    u["model"] = m_list[(curr_idx + 1) % len(m_list)]
    await message.answer(f"🤖 Выбрана модель: **{u['model']}**", reply_markup=main_kb(message.from_user.id), parse_mode="Markdown")

@dp.message(F.text == "📊 Статистика")
async def stats(message: types.Message):
    u = get_user(message.from_user.id)
    await message.answer(f"👤 {u['name']}\n🖼 Создано картинок: {u['count']}\n🛠 Модель: {u['model']}")

@dp.message(F.text)
async def handle_prompt(message: types.Message):
    if message.text in ["🖼 Сгенерировать", "⚙️ Сменить модель", "📊 Статистика"] or "NSFW:" in message.text:
        return

    u = get_user(message.from_user.id)
    
    try:
        # Быстрый перевод
        translated_text = translator.translate(message.text)
        # Добавляем в очередь
        await request_queue.put((message.from_user.id, translated_text, u["nsfw"], u["model"]))
        
        q_size = request_queue.qsize()
        await message.answer(f"⏳ Запрос принят! Ваше место в очереди: **{q_size}**", parse_mode="Markdown")
    except Exception as e:
        await message.answer("⚠️ Ошибка перевода. Попробуй еще раз или на английском.")

# --- ЗАПУСК НА RENDER ---

async def web_healthcheck(request):
    return web.Response(text="I'm alive!", status=200)

async def main():
    # Запуск фонового процесса генерации
    asyncio.create_task(image_worker())
    
    # Веб-сервер для "удержания" Render
    app = web.Application()
    app.router.add_get("/", web_healthcheck)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запускаем всё вместе
    await asyncio.gather(
        site.start(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    asyncio.run(main())
