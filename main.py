import asyncio, os, logging, io, time, gc
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
from huggingface_hub import InferenceClient

# --- НАСТРОЙКИ ---
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

# --- ТОЛЬКО FLUX ---
MODEL_ID = "black-forest-labs/FLUX.1-schnell"

# --- 10 КРУТЫХ СТИЛЕЙ ---
STYLES = {
    "🚫 Без стиля": "",
    "📸 Realism": "raw photo, 8k uhd, dslr, soft lighting, high quality, film grain, fujifilm xt3",
    "🌸 Anime": "anime style, studio ghibli, makoto shinkai, vibrant colors, highly detailed background",
    "🔫 GTA Art": "GTA V loading screen art, grand theft auto style, vector art, cel shaded, sharp lines",
    "🤖 Cyberpunk": "cyberpunk 2077 style, neon lights, night city, chrome, synthwave, futuristic",
    "🧸 3D Pixar": "3d render, disney pixar style, octane render, cute, volumetric lighting, cartoon, 4k",
    "💀 Dark Fantasy": "dark fantasy, elden ring style, gloomy, gothic, intricate details, scary, fog, monster",
    "📼 Retro 80s": "vaporwave, 1980s retro, neon grid, vhs glitch effect, pastel gradient, synthpop",
    "🧊 Voxel/Lego": "voxel art, minecraft style, isometric view, 8-bit, blocky, 3d blocks",
    "🖌️ Oil Paint": "oil painting, impasto, claude monet style, thick brush strokes, canvas texture, artistic",
    "🕵️ Film Noir": "film noir, black and white, dramatic shadows, detective movie style, high contrast, 1940s"
}

# --- ФУНКЦИИ ---

def get_user(uid, name="User"):
    if uid not in user_db:
        # По умолчанию ставим "Без стиля"
        user_db[uid] = {"style": "🚫 Без стиля", "nsfw": False, "name": name, "count": 0}
    return user_db[uid]

def main_kb(uid):
    u = get_user(uid)
    nsfw_status = "🔞 NSFW: ON" if u["nsfw"] else "🔒 NSFW: OFF"
    # Динамическая клавиатура показывающая текущий стиль
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🖼 ГЕНЕРАЦИЯ"), KeyboardButton(text=f"🎨 {u['style']}")],
        [KeyboardButton(text="⚙️ СМЕНИТЬ СТИЛЬ ⏩"), KeyboardButton(text=nsfw_status)]
    ], resize_keyboard=True)

# --- WORKER (ГЕНЕРАТОР) ---

async def image_worker():
    while True:
        uid, user_prompt, nsfw_on, style_key = await request_queue.get()
        try:
            u = get_user(uid)
            style_prompt = STYLES.get(style_key, "")
            
            # Магия промптов
            enhance = "masterpiece, sharp focus, ultra detailed"
            
            if nsfw_on:
                final_prompt = f"{user_prompt}, {style_prompt}, uncensored, explicit anatomy, naked, {enhance}"
            else:
                final_prompt = f"{user_prompt}, {style_prompt}, {enhance}"

            await bot.send_chat_action(uid, "upload_photo")
            
            # Запрос к FLUX
            image = client.text_to_image(final_prompt, model=MODEL_ID)
            
            # Оптимизация памяти (JPEG)
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=85)
            output.seek(0)

            u["count"] += 1
            await bot.send_photo(
                uid, 
                BufferedInputFile(output.read(), filename="image.jpg"),
                caption=f"✨ **Готово!**\n🎨 Стиль: `{style_key}`",
                parse_mode="Markdown",
                reply_markup=main_kb(uid)
            )

        except Exception as e:
            logging.error(f"Gen Error: {e}")
            await bot.send_message(uid, "⚠️ Сбой генерации. Попробуйте снова.")
        finally:
            gc.collect() # Чистим память Render
            request_queue.task_done()

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def start(message: types.Message):
    u = get_user(message.from_user.id, message.from_user.full_name)
    await message.answer(
        f"👋 **Привет! Я Flux Generator.**\n\n"
        f"Я умею рисовать в **10 разных стилях** (GTA, Аниме, Реализм и др).\n"
        f"Просто выбери стиль и напиши, что нарисовать!",
        reply_markup=main_kb(message.from_user.id),
        parse_mode="Markdown"
    )

@dp.message(F.text == "⚙️ СМЕНИТЬ СТИЛЬ ⏩")
async def change_style(message: types.Message):
    u = get_user(message.from_user.id)
    # Получаем список всех стилей
    style_names = list(STYLES.keys())
    # Ищем индекс текущего и берем следующий
    current_index = style_names.index(u["style"])
    next_style = style_names[(current_index + 1) % len(style_names)]
    
    u["style"] = next_style
    await message.answer(f"🎨 Стиль изменен на: **{next_style}**", reply_markup=main_kb(message.from_user.id), parse_mode="Markdown")

@dp.message(F.text.contains("NSFW:"))
async def toggle_nsfw(message: types.Message):
    u = get_user(message.from_user.id)
    u["nsfw"] = not u["nsfw"]
    status = "ВКЛЮЧЕН 🔞" if u["nsfw"] else "ВЫКЛЮЧЕН ✅"
    await message.answer(f"Режим NSFW: **{status}**", reply_markup=main_kb(message.from_user.id), parse_mode="Markdown")

@dp.message(F.text)
async def handle_text(message: types.Message):
    # Игнорируем нажатия на кнопки меню
    if message.text in ["🖼 ГЕНЕРАЦИЯ", "⚙️ СМЕНИТЬ СТИЛЬ ⏩"] or "NSFW:" in message.text or message.text.startswith("🎨"):
        if message.text == "🖼 ГЕНЕРАЦИЯ":
            await message.answer("Просто напиши мне текст, и я начну рисовать!")
        return

    u = get_user(message.from_user.id)
    
    try:
        # Перевод на английский (Flux лучше понимает EN)
        translated = translator.translate(message.text)
        
        await request_queue.put((message.from_user.id, translated, u["nsfw"], u["style"]))
        
        q_pos = request_queue.qsize()
        await message.answer(f"⏳ Принято! Позиция в очереди: **{q_pos}**\n🎨 Стиль: *{u['style']}*", parse_mode="Markdown")
    except:
        await message.answer("⚠️ Не удалось перевести запрос. Попробуйте на английском.")

# --- ЗАПУСК ---

async def web_health(request):
    return web.Response(text="Bot is OK")

async def main():
    asyncio.create_task(image_worker())
    
    app = web.Application()
    app.router.add_get("/", web_health)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
