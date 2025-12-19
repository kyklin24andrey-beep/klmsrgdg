import os
import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Dict, Any

from aiogram import Bot
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    BufferedInputFile
)
import aiohttp
from aiohttp import web
from huggingface_hub import InferenceClient
from deep_translator import GoogleTranslator
from PIL import Image
import io
from dotenv import load_dotenv

# ================== CONFIG ==================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN")
SELF_URL = os.getenv("SELF_URL")
PORT = int(os.getenv("PORT", 8080))

MODEL = "black-forest-labs/FLUX.1-dev"

logging.basicConfig(level=logging.INFO)

# Создаем бота
bot = Bot(token=BOT_TOKEN)
hf = InferenceClient(MODEL, token=HF_TOKEN)

# ================== MEMORY ==================

queue = asyncio.Queue()

# Хранение состояний пользователей
user_states: Dict[int, Dict[str, Any]] = {}
last_image_prompt: Dict[int, str] = {}
last_image_bytes: Dict[int, bytes] = {}
last_author: Dict[int, int] = {}

user_activity = defaultdict(lambda: deque(maxlen=10))
muted_until = defaultdict(int)

# ================== STYLES & NSFR ==================

STYLES = {
    "anime": "anime style, anime illustration",
    "gta": "GTA-style, satirical, exaggerated, video game art",
    "realistic": "photorealistic, hyperrealistic, detailed lighting",
    "oil_painting": "oil painting, canvas texture, brush strokes",
    "watercolor": "watercolor painting, soft edges, translucent colors",
    "pixel_art": "pixel art, retro gaming, 8-bit or 16-bit style",
    "cyberpunk": "cyberpunk, neon lights, futuristic, high-tech",
    "surreal": "surrealist, dreamlike, abstract, bizarre",
    "cartoon": "cartoon style, bright colors, simple shapes",
    "gothic": "gothic, dark fantasy, ornate, medieval influence"
}

NSFR_PROMPT = ", explicit, nudity, sexual content, adult themes"

# ================== ANTIFLOOD ==================

def antiflood(user_id: int) -> int | None:
    now = time.time()

    if muted_until[user_id] > now:
        return int(muted_until[user_id] - now)

    activity = user_activity[user_id]
    activity.append(now)

    recent = [t for t in activity if now - t < 30]

    if len(recent) >= 5:
        muted_until[user_id] = now + 300
        return 300
    if len(recent) >= 3:
        return 60
    if len(recent) >= 1:
        return 15
    return None

# ================== HELPERS ==================

def get_style_keyboard():
    keyboard = []
    for key, label in zip(STYLES.keys(), STYLES.values()):
        keyboard.append([InlineKeyboardButton(text=label, callback_data=f"style_{key}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_nsfr_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, NSFR", callback_data="nsfr_yes")],
        [InlineKeyboardButton(text="❌ Нет, без NSFR", callback_data="nsfr_no")]
    ])

def get_image_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔁 Повторить", callback_data="repeat"),
            InlineKeyboardButton(text="🎭 Другой стиль", callback_data="style_change")
        ],
        [
            InlineKeyboardButton(text="🧠 Усилить", callback_data="enhance"),
            InlineKeyboardButton(text="❌ Удалить", callback_data="delete")
        ]
    ])


# ================== COMMAND HANDLER ==================

async def handle_start_command(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return
    await message.reply("Привет! Используйте команду /gen для создания изображения.")

async def handle_gen_command(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        return

    user_id = message.from_user.id
    cooldown = antiflood(user_id)
    if cooldown:
        await message.reply(f"⏳ Подожди {cooldown} сек.")
        return
# Инициализируем состояние пользователя
    user_states[user_id] = {"step": "choosing_style"}
    
    await message.reply("🎨 Выберите стиль:", reply_markup=get_style_keyboard())

# ================== CALLBACK QUERY HANDLERS ==================

async def handle_callback_query(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    state = user_states.get(user_id, {}).get("step", "idle")

    if data.startswith("style_") and state == "choosing_style":
        style_key = data.split("_")[1]
        user_states[user_id]["selected_style"] = STYLES[style_key]
        user_states[user_id]["step"] = "choosing_nsfr"
        
        await bot.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            text=f"Выбран стиль: {STYLES[style_key]}\n\nТеперь выберите: NSFR контент?",
            reply_markup=get_nsfr_keyboard()
        )
        await bot.answer_callback_query(callback_query.id)

    elif data.startswith("nsfr_") and state == "choosing_nsfr":
        user_states[user_id]["nsfr"] = data == "nsfr_yes"
        user_states[user_id]["step"] = "awaiting_prompt"
        
        await bot.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            text=f"NSFR: {'Да' if user_states[user_id]['nsfr'] else 'Нет'}\n\nВведите ваш запрос:"
        )
        await bot.answer_callback_query(callback_query.id)

    elif data == "repeat" and state == "idle":
        cid = callback_query.message.chat.id
        if cid in last_image_prompt:
            await queue.put((cid, user_id, last_image_prompt[cid]))
        await bot.answer_callback_query(callback_query.id, text="🔁 Повторяю")
        
    elif data == "style_change" and state == "idle":
        user_states[user_id] = {"step": "choosing_style"}
        await bot.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            text="🎨 Выберите новый стиль:",
            reply_markup=get_style_keyboard()
        )
        await bot.answer_callback_query(callback_query.id)

    elif data == "enhance" and state == "idle":
        cid = callback_query.message.chat.id
        if cid in last_image_prompt:
            enhanced_prompt = last_image_prompt[cid] + ", ultra detailed, cinematic lighting, 8k"
            await queue.put((cid, user_id, enhanced_prompt))
        await bot.answer_callback_query(callback_query.id, text="🧠 Усилено")

    elif data == "delete" and state == "idle":
        cid = callback_query.message.chat.id
        if cid in last_author and user_id != last_author.get(cid):
            await bot.answer_callback_query(
                callback_query.id,
                text="❌ Только автор",
                show_alert=True
            )
            return
        try:
            await bot.delete_message(chat_id=cid, message_id=callback_query.message.message_id)
        except Exception as e:
            logging.warning(f"Could not delete message: {e}")
        # Не нужно вызывать answer_callback_query после удаления, если не нужен alert

# ================== MESSAGE HANDLERS ==================

async def handle_message(message: Message):
    user_id = message.from_user.id
    state_info = user_states.get(user_id, {})
    step = state_info.get("step", "idle")

    if step == "awaiting_prompt":
        selected_style = state_info.get("selected_style", "")
        nsfr = state_info.get("nsfr", False)
        
        final_prompt = message.text.strip()
        if selected_style:
            final_prompt += f", {selected_style}"
        if nsfr:
            final_prompt += NSFR_PROMPT
await queue.put((message.chat.id, user_id, final_prompt))
        
        # Сброс состояния
        user_states[user_id] = {"step": "idle"}
        
        await message.reply("🎨 Принял. Генерирую...")
    elif step == "idle" and message.text and message.text.startswith('/'):
        # Если пользователь ввел другую команду, когда ждал промт, игнорируем
        pass
    else:
        # Если сообщение пришло вне процесса настройки
        pass


# ================== WORKER ==================

async def image_worker():
    while True:
        chat_id, user_id, prompt = await queue.get()

        try:
            prompt_en = GoogleTranslator(source="auto", target="en").translate(prompt)

            image = hf.text_to_image(
                prompt=prompt_en,
                height=1024,
                width=1024,
                guidance_scale=7
            )

            buf = io.BytesIO()
            image.save(buf, format="PNG")
            data = buf.getvalue()

            last_image_prompt[chat_id] = prompt
            last_image_bytes[chat_id] = data
            last_author[chat_id] = user_id

            await bot.send_photo(
                chat_id,
                BufferedInputFile(data, "image.png"),
                caption=f"🖼 {prompt}",
                reply_markup=get_image_keyboard()
            )

        except Exception as e:
            logging.error(f"Ошибка генерации: {e}")
            await bot.send_message(chat_id, f"❌ Ошибка генерации: {e}")

        queue.task_done()


# ================== SELF PINGER ==================

async def self_pinger():
    if not SELF_URL:
        return

    await asyncio.sleep(30)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                await session.get(SELF_URL, timeout=10)
                logging.info("Self-ping OK")
            except Exception as e:
                logging.warning(f"Ping error: {e}")
            await asyncio.sleep(8 * 60)


# ================== WEBHOOK SETUP ==================

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"

async def set_webhook():
    webhook_url = f"{SELF_URL}{WEBHOOK_PATH}"
    async with aiohttp.ClientSession() as session:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
        payload = {'url': webhook_url}
        async with session.post(url, json=payload) as resp:
            result = await resp.json()
            logging.info(f"Set webhook response: {result}")


# ================== WEB HANDLER FOR TELEGRAM UPDATES ==================

async def handle_telegram_update(request):
    """Обработчик входящих обновлений от Telegram через webhook"""
    try:
        update_json = await request.json()
        logging.debug(f"Received update: {update_json}")

        if 'message' in update_json:
            message_data = update_json['message']
            message = Message.model_validate(message_data)
            
            # Обработка команд
            if message.text == '/start':
                 await handle_start_command(message)
            elif message.text and message.text.startswith('/gen'):
                 await handle_gen_command(message)
            else:
                 # Обработка обычного текстового сообщения
                 await handle_message(message)
                 
        elif 'callback_query' in update_json:
            query_data = update_json['callback_query']
            callback_query = CallbackQuery.model_validate(query_data)
            await handle_callback_query(callback_query)

        return web.Response(text="OK")
    except Exception as e:
        logging.error(f"Error handling update: {e}", exc_info=True)
        return web.Response(status=500)


# ================== HEALTH CHECK ==================

async def health(_):
    return web.Response(text="OK")


# ================== MAIN ASYNC FUNCTION ==================
async def on_startup(app):
    """Выполняется при запуске приложения aiohttp"""
    logging.info("Setting up webhook...")
    await set_webhook()
    logging.info("Starting background tasks...")
    asyncio.create_task(image_worker())
    asyncio.create_task(self_pinger())


async def main():
    # Создаем приложение aiohttp
    app = web.Application()
    app.add_routes([web.post(WEBHOOK_PATH, handle_telegram_update)])
    app.add_routes([web.get("/", health)])

    # Коллбэк для выполнения действий при запуске
    app.on_startup.append(on_startup)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    logging.info(f"Bot is running on port {PORT}, webhook path is {WEBHOOK_PATH}, waiting for updates...")

    # Блокируем выполнение, пока сервер работает
    try:
        while True:
            await asyncio.sleep(3600)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logging.info("Shutting down...")
    finally:
        await runner.cleanup()


if name == "main":
    asyncio.run(main())
