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
from PIL import Image

# --- КОНФИГУРАЦИЯ ---
logging.basicConfig(level=logging.INFO)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN")
PORT = int(os.getenv("PORT", 8080))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
translator = GoogleTranslator(source='auto', target='en')
client = InferenceClient(token=HF_TOKEN)

# База данных и очередь
user_db = {}
request_queue = asyncio.Queue()

MODELS = {
    "🚀 Flux.1": "black-forest-labs/FLUX.1-schnell",
    "📸 Realism": "stabilityai/stable-diffusion-xl-base-1.0",
    "🎨 Dreamshaper": "Lykon/DreamShaper"
}

# --- ПОМОЩНИКИ ---

def get_user(uid, name="User"):
    if uid not in user_db:
        user_db[uid] = {
            "mode": "photo", "style": "🚫 Без стиля", "model": "🚀 Flux.1",
            "stats": 0, "magic": True, "name": name, "temp_img": None
        }
    return user_db[uid]

def main_kb(u):
    magic_status = "🪄 MAGIC: ON" if u["magic"] else "🪄 MAGIC: OFF"
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🖼 ГЕНЕРАЦИЯ"), KeyboardButton(text="🎬 ВИДЕО")],
        [KeyboardButton(text="⚙️ НАСТРОЙКИ"), KeyboardButton(text="📊 ПРОФИЛЬ")],
        [KeyboardButton(text=magic_status), KeyboardButton(text="💡 ОПТИМИЗИРОВАТЬ")]
    ], resize_keyboard=True)

# --- ФУНКЦИЯ 17: PROMPT ENGINEER ---
async def optimize_prompt(text):
    prompt_eng = f"Transform this simple idea into a highly detailed, professional stable diffusion prompt: {text}. Output only the optimized prompt."
    try:
        # Используем бесплатную модель для текста
        res = client.text_generation(prompt_eng, model="mistralai/Mistral-7B-Instruct-v0.2", max_new_tokens=100)
        return res.strip()
    except:
        return text

# --- ФУНКЦИЯ 18: ОБРАБОТЧИК ОЧЕРЕДИ ---
async def worker():
    while True:
        task = await request_queue.get()
        uid, message, prompt, mode, model, img_data = task
        try:
            u = get_user(uid)
            if mode == "video":
                url = f"https://image.pollinations.ai/prompt/{prompt}?model=video"
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(url) as r:
                        video = await r.read()
                        await bot.send_video(uid, BufferedInputFile(video, "v.mp4"), caption="🎬 Ваше видео!")
            else:
                # ФУНКЦИЯ 10/13: Image-to-Image
                if img_data:
                    # Если есть картинка, используем ее как основу
                    image = client.image_to_image(img_data, prompt=prompt, model="stabilityai/stable-diffusion-xl-refiner-1.0")
                else:
                    image = client.text_to_image(prompt, model=MODELS[model])
                
                img_buf = io.BytesIO()
                image.save(img_buf, format='PNG')
                u["stats"] += 1
                await bot.send_photo(uid, BufferedInputFile(img_buf.getvalue(), "i.png"), caption=f"✅ Готово! (#{u['stats']})")
        except Exception as e:
            logging.error(f"Ошибка воркера: {e}")
            await bot.send_message(uid, "❌ Произошла ошибка. Попробуй другой запрос.")
        finally:
            request_queue.task_done()

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    u = get_user(message.from_user.id, message.from_user.full_name)
    help_text = (
        "🔥 **ULTIMATE AI BOT 2025!**\n\n"
        "🔟 **Inpainting:** Пришли фото, а затем напиши, что изменить.\n"
        "1️⃣3️⃣ **Img2Img:** Я перерисую твой набросок в шедевр.\n"
        "1️⃣7️⃣ **Optimizer:** Кнопка 'ОПТИМИЗИРОВАТЬ' улучшит твой промпт.\n"
        "1️⃣8️⃣ **Очередь:** Теперь бот не зависает, все запросы в очереди.\n\n"
        "Просто напиши запрос или пришли фото!"
    )
    await message.answer(help_text, reply_markup=main_kb(u), parse_mode="Markdown")

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    u = get_user(message.from_user.id)
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    img_bytes = await bot.download_file(file_info.file_path)
    u["temp_img"] = img_bytes.read()
    await message.answer("🖼 **Фото получено!** Теперь напиши, что добавить или изменить на нем.")

@dp.message(F.text == "💡 ОПТИМИЗИРОВАТЬ")
async def btn_opt(message: types.Message):
    await message.answer("Напиши свою простую идею, и я превращу её в мощный промпт!")

@dp.message(F.text == "🪄 MAGIC: ON")
@dp.message(F.text == "🪄 MAGIC: OFF")
async def toggle_magic(message: types.Message):
    u = get_user(message.from_user.id)
    u["magic"] = not u["magic"]
    await message.answer(f"Magic Prompt: {'ВКЛ' if u['magic'] else 'ВЫКЛ'}", reply_markup=main_kb(u))

@dp.message(F.text)
async def handle_text(message: types.Message):
    if message.text in ["🖼 ГЕНЕРАЦИЯ", "🎬 ВИДЕО", "⚙️ НАСТРОЙКИ", "📊 ПРОФИЛЬ", "💡 ОПТИМИЗИРОВАТЬ"]: return
    
    u = get_user(message.from_user.id)
    prompt = translator.translate(message.text)
    
    # Если нажата кнопка оптимизации (условно) или просто длинный текст
    if len(message.text) < 30 and u["magic"]:
        prompt = await optimize_prompt(prompt)

    # Ставим в очередь
    await request_queue.put((message.from_user.id, message, prompt, u["mode"], u["model"], u.get("temp_img")))
    u["temp_img"] = None # Сбрасываем фото после постановки в очередь
    
    q_size = request_queue.qsize()
    await message.answer(f"⏳ Запрос добавлен в очередь. Ваше место: **{q_size}**", parse_mode="Markdown")

# --- ВЕБ-СЕРВЕР ---
async def handle_ping(request): return web.Response(text="AI Active")

async def main():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    asyncio.create_task(worker()) # Запуск воркера очереди
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
