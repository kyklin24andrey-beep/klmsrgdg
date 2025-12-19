import asyncio, os, logging, io, time, gc
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
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
    "style_none": ("🚫 Без стиля", ""),
    "style_real": ("📸 Realism", "raw photo, 8k uhd, dslr, soft lighting, high quality, film grain"),
    "style_anime": ("🌸 Anime", "anime style, studio ghibli, makoto shinkai, vibrant colors, masterpiece"),
    "style_gta": ("🔫 GTA Art", "GTA V loading screen art, grand theft auto style, vector art, cel shaded"),
    "style_cyber": ("🤖 Cyberpunk", "cyberpunk 2077 style, neon lights, night city, futuristic, synthwave"),
    "style_pixar": ("🧸 3D Pixar", "3d render, disney pixar style, octane render, cute, volumetric lighting"),
    "style_fantasy": ("💀 Dark Fantasy", "dark fantasy, elden ring style, gloomy, gothic, intricate details"),
    "style_80s": ("📼 Retro 80s", "vaporwave, 1980s retro, neon grid, vhs glitch effect, synthpop"),
    "style_voxel": ("🧊 Voxel", "voxel art, minecraft style, isometric view, blocky, 3d blocks"),
    "style_oil": ("🖌️ Oil Paint", "oil painting, impasto, thick brush strokes, canvas texture, artistic"),
    "style_noir": ("🕵️ Film Noir", "film noir, black and white, dramatic shadows, 1940s style")
}

# --- ФУНКЦИИ ---

def get_user(uid, name="User"):
    if uid not in user_db:
        user_db[uid] = {"style_id": "style_none", "nsfw": False, "name": name, "count": 0}
    return user_db[uid]

def get_main_kb(uid):
    u = get_user(uid)
    nsfw_status = "🔞 NSFW: ON" if u["nsfw"] else "🔒 NSFW: OFF"
    style_name = STYLES[u["style_id"]][0]
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🖼 ГЕНЕРАЦИЯ"), KeyboardButton(text=f"🎭 {style_name}")],
        [KeyboardButton(text="⚙️ ВЫБРАТЬ СТИЛЬ"), KeyboardButton(text=nsfw_status)]
    ], resize_keyboard=True)

def get_styles_inline():
    buttons = []
    # Создаем кнопки по 2 в ряд
    row = []
    for sid, (name, _) in STYLES.items():
        row.append(InlineKeyboardButton(text=name, callback_data=f"set_{sid}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row: buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- WORKER ---

async def image_worker():
    while True:
        uid, user_prompt, nsfw_on, style_id = await request_queue.get()
        try:
            u = get_user(uid)
            style_prompt = STYLES[style_id][1]
            
            enhance = "masterpiece, sharp focus, ultra detailed"
            if nsfw_on:
                final_prompt = f"{user_prompt}, {style_prompt}, uncensored, explicit anatomy, naked, {enhance}"
            else:
                final_prompt = f"{user_prompt}, {style_prompt}, {enhance}"

            await bot.send_chat_action(uid, "upload_photo")
            image = client.text_to_image(final_prompt, model=MODEL_ID)
            
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=85)
            output.seek(0)

            u["count"] += 1
            await bot.send_photo(
                uid, 
                BufferedInputFile(output.read(), filename="image.jpg"),
                caption=f"✨ **Готово!**\n🎨 Стиль: `{STYLES[style_id][0]}`",
                parse_mode="Markdown",
                reply_markup=get_main_kb(uid)
            )
        except Exception as e:
            logging.error(f"Gen Error: {e}")
            await bot.send_message(uid, "⚠️ Сбой генерации. Попробуйте снова.")
        finally:
            gc.collect()
            request_queue.task_done()

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def start(message: types.Message):
    u = get_user(message.from_user.id, message.from_user.full_name)
    await message.answer(
        f"👋 **Привет! Я Flux Generator.**\nНажми кнопку ниже, чтобы выбрать стиль.",
        reply_markup=get_main_kb(message.from_user.id),
        parse_mode="Markdown"
    )

@dp.message(F.text == "⚙️ ВЫБРАТЬ СТИЛЬ")
async def show_style_menu(message: types.Message):
    await message.answer("🎨 **Выберите желаемый стиль для генерации:**", 
                         reply_markup=get_styles_inline(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("set_"))
async def set_style_callback(callback: types.CallbackQuery):
    style_id = callback.data.replace("set_", "")
    u = get_user(callback.from_user.id)
    u["style_id"] = style_id
    
    style_name = STYLES[style_id][0]
    await callback.answer(f"✅ Выбран стиль: {style_name}")
    await callback.message.edit_text(f"✅ Текущий стиль: **{style_name}**\nТеперь отправь мне текст для рисования!", 
                                     parse_mode="Markdown")
    # Обновляем основную клавиатуру (опционально отправляем новое сообщение)
    await bot.send_message(callback.from_user.id, "Меню обновлено 👇", reply_markup=get_main_kb(callback.from_user.id))

@dp.message(F.text.contains("NSFW:"))
async def toggle_nsfw(message: types.Message):
    u = get_user(message.from_user.id)
    u["nsfw"] = not u["nsfw"]
    await message.answer(f"Режим NSFW: **{'ВКЛЮЧЕН 🔞' if u['nsfw'] else 'ВЫКЛЮЧЕН ✅'}**", 
                         reply_markup=get_main_kb(message.from_user.id), parse_mode="Markdown")

@dp.message(F.text)
async def handle_text(message: types.Message):
    if message.text in ["🖼 ГЕНЕРАЦИЯ", "⚙️ ВЫБРАТЬ СТИЛЬ"] or "NSFW:" in message.text or message.text.startswith("🎭"):
        return

    u = get_user(message.from_user.id)
    try:
        translated = translator.translate(message.text)
        await request_queue.put((message.from_user.id, translated, u["nsfw"], u["style_id"]))
        await message.answer(f"⏳ Запрос в очереди... Стиль: *{STYLES[u['style_id']][0]}*", parse_mode="Markdown")
    except:
        await message.answer("⚠️ Ошибка перевода.")

# --- ЗАПУСК ---

async def main():
    asyncio.create_task(image_worker())
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is OK"))
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
