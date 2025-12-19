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

BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN")
PORT = int(os.getenv("PORT", 8080))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
translator = GoogleTranslator(source='auto', target='en')
client = InferenceClient(token=HF_TOKEN)

user_db = {}
request_queue = asyncio.Queue()

# --- МОДЕЛИ И СТИЛИ ---
MODELS = {
    "🚀 Flux.1": "black-forest-labs/FLUX.1-schnell",
    "📸 Realism": "stabilityai/stable-diffusion-xl-base-1.0",
    "🎨 Dreamshaper": "Lykon/DreamShaper"
}

STYLES = {
    "🚫 Без стиля": "",
    "🌌 Cyberpunk": "neon, futuristic",
    "📸 Realistic": "8k, masterpiece, photography",
    "⛩ Anime": "anime style, studio ghibli",
    "🎮 3D Render": "unreal engine 5, octane render"
}

# --- ФУНКЦИИ ПОДДЕРЖКИ ---
def get_user(uid, name="User"):
    if uid not in user_db:
        user_db[uid] = {
            "mode": "photo", "style": "🚫 Без стиля", "model": "🚀 Flux.1",
            "stats": 0, "magic": True, "name": name, "temp_img": None
        }
    return user_db[uid]

def main_kb(u):
    # Динамические названия кнопок
    magic_status = "🪄 MAGIC: ON" if u["magic"] else "🪄 MAGIC: OFF"
    mode_status = "🖼 РЕЖИМ: ФОТО" if u["mode"] == "photo" else "🎬 РЕЖИМ: ВИДЕО"
    
    kb = [
        [KeyboardButton(text=mode_status)],
        [KeyboardButton(text="⚙️ НАСТРОЙКИ"), KeyboardButton(text="📊 ПРОФИЛЬ")],
        [KeyboardButton(text=magic_status), KeyboardButton(text="💡 ОПТИМИЗИРОВАТЬ")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# --- ОБРАБОТЧИКИ КНОПОК (ГЛАВНОЕ МЕНЮ) ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    u = get_user(message.from_user.id, message.from_user.full_name)
    await message.answer(f"🔥 **Бот активирован!**\nВыбирай функции на кнопках ниже:", 
                         reply_markup=main_kb(u), parse_mode="Markdown")

@dp.message(F.text.contains("РЕЖИМ:"))
async def toggle_mode(message: types.Message):
    u = get_user(message.from_user.id)
    u["mode"] = "video" if u["mode"] == "photo" else "photo"
    await message.answer(f"✅ Режим изменен на: **{u['mode'].upper()}**", reply_markup=main_kb(u), parse_mode="Markdown")

@dp.message(F.text.contains("MAGIC:"))
async def toggle_magic(message: types.Message):
    u = get_user(message.from_user.id)
    u["magic"] = not u["magic"]
    await message.answer(f"🪄 Magic Prompt: **{'ВКЛ' if u['magic'] else 'ВЫКЛ'}**", reply_markup=main_kb(u), parse_mode="Markdown")

@dp.message(F.text == "📊 ПРОФИЛЬ")
async def show_profile(message: types.Message):
    u = get_user(message.from_user.id)
    await message.answer(f"👤 **Профиль:** {u['name']}\n🏆 **Создано:** {u['stats']}\n🤖 **Модель:** {u['model']}", parse_mode="Markdown")

@dp.message(F.text == "⚙️ НАСТРОЙКИ")
async def settings_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🤖 Выбрать модель", callback_data="set_model_list"))
    builder.row(InlineKeyboardButton(text="🎨 Выбрать стиль", callback_data="set_style_list"))
    await message.answer("⚙️ **Настройки генерации:**", reply_markup=builder.as_markup(), parse_mode="Markdown")

# --- ОБРАБОТЧИКИ CALLBACK (ИНЛАЙН КНОПКИ) ---

@dp.callback_query(F.data == "set_model_list")
async def cb_models(call: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    for m in MODELS.keys(): builder.add(InlineKeyboardButton(text=m, callback_data=f"save_mod_{m}"))
    builder.adjust(1)
    await call.message.edit_text("🤖 Выберите модель:", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "set_style_list")
async def cb_styles(call: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    for s in STYLES.keys(): builder.add(InlineKeyboardButton(text=s, callback_data=f"save_sty_{s}"))
    builder.adjust(2)
    await call.message.edit_text("🎨 Выберите стиль:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("save_mod_"))
async def save_mod(call: types.CallbackQuery):
    m = call.data.replace("save_mod_", "")
    get_user(call.from_user.id)["model"] = m
    await call.answer(f"Выбрана модель: {m}")
    await call.message.delete()

@dp.callback_query(F.data.startswith("save_sty_"))
async def save_sty(call: types.CallbackQuery):
    s = call.data.replace("save_sty_", "")
    get_user(call.from_user.id)["style"] = s
    await call.answer(f"Стиль {s} применен!")
    await call.message.delete()

# --- ЛОГИКА ГЕНЕРАЦИИ (ВОРКЕР) ---

async def worker():
    while True:
        task = await request_queue.get()
        uid, prompt, mode, model, style_tag, img_data = task
        try:
            full_prompt = f"{prompt}, {style_tag}"
            if mode == "video":
                url = f"https://image.pollinations.ai/prompt/{prompt}?model=video"
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(url) as r:
                        data = await r.read()
                        await bot.send_video(uid, BufferedInputFile(data, "v.mp4"))
            else:
                image = client.text_to_image(full_prompt, model=MODELS[model])
                buf = io.BytesIO(); image.save(buf, format='PNG')
                await bot.send_photo(uid, BufferedInputFile(buf.getvalue(), "i.png"), 
                                     caption=f"✅ Готово! Модель: {model}")
                user_db[uid]["stats"] += 1
        except:
            await bot.send_message(uid, "❌ Ошибка. Попробуйте другой промпт.")
        finally:
            request_queue.task_done()

@dp.message(F.text)
async def handle_text(message: types.Message):
    if message.text in ["💡 ОПТИМИЗИРОВАТЬ", "⚙️ НАСТРОЙКИ", "📊 ПРОФИЛЬ"] or "РЕЖИМ" in message.text or "MAGIC" in message.text:
        return # Игнорируем нажатия кнопок как текст
        
    u = get_user(message.from_user.id)
    p_en = translator.translate(message.text)
    if u["magic"]: p_en += ", masterpiece, highly detailed, 8k"
    
    await request_queue.put((message.from_user.id, p_en, u["mode"], u["model"], STYLES[u["style"]], None))
    await message.answer(f"⏳ Запрос в очереди (Позиция: {request_queue.qsize()})")

# --- ЗАПУСК ---
async def handle_hc(request): return web.Response(text="OK")

async def main():
    app = web.Application(); app.router.add_get("/", handle_hc)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    asyncio.create_task(worker())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
