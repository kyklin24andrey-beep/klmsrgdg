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

# База данных в оперативной памяти
user_db = {}

# Константы моделей и стилей
MODELS = {
    "🚀 Flux.1 (Fast)": "black-forest-labs/FLUX.1-schnell",
    "📸 Realism XL": "stabilityai/stable-diffusion-3.5-large",
    "⛩ Anime V3": "cagliostrolab/animagine-xl-3.1",
    "🎨 Dreamshaper": "Lykon/DreamShaper"
}

STYLES = {
    "🚫 Без стиля": "",
    "🌌 Cyberpunk": "neon lighting, cyberpunk 2077 aesthetic, futuristic",
    "📸 Realistic": "8k uhd, photorealistic, raw photo, highly detailed",
    "🏮 Studio Ghibli": "hand-drawn, studio ghibli style, anime aesthetic",
    "💎 Premium Art": "masterpiece, trending on artstation, cinematic lighting",
    "🎮 3D Render": "unreal engine 5, octane render, 3d style, cute"
}

HELP_TEXT = (
    "📖 **ИНСТРУКЦИЯ ПО ИСПОЛЬЗОВАНИЮ:**\n\n"
    "🖼 **Фото:** Просто пиши запрос. Бот использует ТОП-модели (Flux/SDXL). "
    "Можно писать на русском — я сам переведу!\n\n"
    "🎬 **Видео:** Нажми кнопку 'РЕЖИМ: ВИДЕО'. Опиши действие (напр. 'кот бежит по луне'). "
    "Генерация занимает 30-90 секунд.\n\n"
    "🪄 **Magic Prompt:** Если включено, я сам добавлю в твой запрос детали "
    "(свет, тени, качество), чтобы картинка выглядела профессионально.\n\n"
    "⚙️ **Настройки:** Здесь можно сменить нейросеть или выбрать стиль (Аниме, Киберпанк и др.).\n\n"
    "📊 **Профиль:** Твой уровень и количество созданных шедевров.\n\n"
    "⚠️ *Подсказка: Если нейросеть занята, я автоматически переключусь на резервную!*"
)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_user(uid, name="User"):
    if uid not in user_db:
        user_db[uid] = {
            "mode": "photo", "style": "🚫 Без стиля", "model": "🚀 Flux.1 (Fast)",
            "stats": 0, "magic": True, "name": name, "last_gen": 0
        }
    return user_db[uid]

# --- КЛАВИАТУРЫ ---

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
    welcome = (
        f"🔥 **ПРИВЕТ, {message.from_user.first_name}!**\n"
        "Я — твой персональный ИИ-комбайн.\n\n" + HELP_TEXT
    )
    await message.answer(welcome, reply_markup=main_kb(u), parse_mode="Markdown")

@dp.message(F.text.startswith("🔄 РЕЖИМ:"))
async def toggle_mode(message: types.Message):
    u = get_user(message.from_user.id)
    u["mode"] = "video" if u["mode"] == "photo" else "photo"
    await message.answer(f"✅ Режим изменен на: **{u['mode'].upper()}**", reply_markup=main_kb(u), parse_mode="Markdown")

@dp.message(F.text.startswith("🪄 MAGIC:"))
async def toggle_magic(message: types.Message):
    u = get_user(message.from_user.id)
    u["magic"] = not u["magic"]
    await message.answer(f"🪄 Magic Prompt теперь: **{'ВКЛ' if u['magic'] else 'ВЫКЛ'}**", reply_markup=main_kb(u), parse_mode="Markdown")

@dp.message(F.text == "⚙️ НАСТРОЙКИ")
async def settings_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🤖 Выбрать модель", callback_data="menu_models"))
    builder.row(InlineKeyboardButton(text="🎨 Выбрать стиль", callback_data="menu_styles"))
    await message.answer("🛠 **Настройка ИИ под себя:**", reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "menu_models")
async def models_list(call: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    for m in MODELS.keys(): builder.add(InlineKeyboardButton(text=m, callback_data=f"set_mod_{m}"))
    builder.adjust(1)
    await call.message.edit_text("🤖 **Доступные нейросети:**", reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("set_mod_"))
async def set_model(call: types.CallbackQuery):
    m = call.data.replace("set_mod_", "")
    get_user(call.from_user.id)["model"] = m
    await call.answer(f"Выбрана модель: {m}")
    await call.message.delete()

@dp.message(F.text == "📊 ПРОФИЛЬ")
async def show_profile(message: types.Message):
    u = get_user(message.from_user.id)
    level = (u["stats"] // 10) + 1
    await message.answer(
        f"👤 **Имя:** {u['name']}\n"
        f"🏆 **Уровень:** {level}\n"
        f"⚡ **Создано работ:** {u['stats']}\n"
        f"🤖 **Модель:** {u['model']}\n"
        f"✨ **Стиль:** {u['style']}", parse_mode="Markdown"
    )

@dp.message(F.text)
async def handle_gen(message: types.Message):
    if message.text.startswith("/") or "РЕЖИМ" in message.text or "MAGIC" in message.text: return
    
    u = get_user(message.from_user.id)
    
    # Cooldown 5 секунд
    if time.time() - u["last_gen"] < 5:
        return await message.answer("⚠️ Подожди немного, ИИ разогревается!")
    
    status = await message.answer("📡 **Связь с нейросетью...**", parse_mode="Markdown")
    
    try:
        # Перевод и магия
        prompt_en = translator.translate(message.text)
        if u["magic"]: prompt_en += ", cinematic, masterpiece, 8k, highly detailed, trending on artstation"
        
        if u["mode"] == "video":
            await status.edit_text("🎬 **Генерирую анимацию (до 90 сек)...**")
            url = f"https://image.pollinations.ai/prompt/{prompt_en}?model=video&seed={random.randint(1,9999)}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=180) as r:
                    if r.status == 200:
                        data = await r.read()
                        await message.answer_video(BufferedInputFile(data, "v.mp4"), caption="🎬 Видео готово!")
                    else: raise Exception("API Error")
        else:
            await status.edit_text("🎨 **Рисую картину...**")
            model_path = MODELS.get(u["model"], MODELS["🚀 Flux.1 (Fast)"])
            full_prompt = f"{prompt_en}, {STYLES.get(u['style'], '')}"
            
            # Генерация
            image = client.text_to_image(full_prompt, model=model_path)
            img_buf = io.BytesIO()
            image.save(img_buf, format='PNG')
            
            u["stats"] += 1
            u["last_gen"] = time.time()
            await message.answer_photo(
                BufferedInputFile(img_buf.getvalue(), "i.png"),
                caption=f"✅ **Готово!**\n🤖 Модель: `{u['model']}`\n📊 Работа №{u['stats']}",
                parse_mode="Markdown"
            )

        await status.delete()
    except Exception as e:
        logging.error(e)
        await status.edit_text("❌ Ошибка. Возможно, промпт слишком сложный или сервер HF перегружен.")

# --- SERVER FOR RENDER ---
async def handle_ping(request): return web.Response(text="AI Active")

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
