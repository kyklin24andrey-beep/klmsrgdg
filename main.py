import os
import asyncio
import logging
import time
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    BufferedInputFile
)
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiohttp import web, ClientSession
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

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
hf = InferenceClient(MODEL, token=HF_TOKEN)

# ================== MEMORY ==================

queue = asyncio.Queue()

last_image_prompt = {}      # chat_id -> prompt
last_image_bytes = {}       # chat_id -> bytes
last_author = {}            # chat_id -> user_id

user_activity = defaultdict(lambda: deque(maxlen=10))
muted_until = defaultdict(int)

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

# ================== UI ==================

def image_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔁 Повторить", callback_data="repeat"),
            InlineKeyboardButton(text="🎭 Другой стиль", callback_data="style")
        ],
        [
            InlineKeyboardButton(text="🧠 Усилить", callback_data="enhance"),
            InlineKeyboardButton(text="❌ Удалить", callback_data="delete")
        ]
    ])

BOT_DESCRIPTION = (
    "🤖 Генератор изображений\n\n"
    "Команды:\n"
    "/gen <описание> — создать изображение\n"
    "/gen — покажет это описание\n\n"
    "Фишки:\n"
    "• Контекст группы (модификация последней картинки)\n"
    "• Inline-кнопки как у Iris\n"
    "• Антифлуд и очередь\n"
)

# ================== WORKER ==================

async def image_worker():
    while True:
        task = await queue.get()
        chat_id, user_id, prompt = task

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
                reply_markup=image_keyboard()
            )

        except Exception as e:
            await bot.send_message(chat_id, f"❌ Ошибка генерации: {e}")

        queue.task_done()

# ================== COMMAND ==================

@dp.message(Command("gen"))
async def gen_cmd(message: Message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    cooldown = antiflood(message.from_user.id)
    if cooldown:
        await message.reply(f"⏳ Подожди {cooldown} сек.")
        return

    prompt = message.text.replace("/gen", "").strip()

    if not prompt:
        await message.reply(BOT_DESCRIPTION)
        return

    await queue.put((message.chat.id, message.from_user.id, prompt))
    await message.reply("🎨 Принял. Генерирую...")

# ================== CALLBACKS ==================

@dp.callback_query(F.data == "repeat")
async def cb_repeat(call: CallbackQuery):
    cid = call.message.chat.id
    await queue.put((cid, call.from_user.id, last_image_prompt[cid]))
    await call.answer("🔁 Повторяю")

@dp.callback_query(F.data == "style")
async def cb_style(call: CallbackQuery):
    cid = call.message.chat.id
    prompt = last_image_prompt[cid] + ", different artistic style"
    await queue.put((cid, call.from_user.id, prompt))
    await call.answer("🎭 Новый стиль")

@dp.callback_query(F.data == "enhance")
async def cb_enhance(call: CallbackQuery):
    cid = call.message.chat.id
    prompt = last_image_prompt[cid] + ", ultra detailed, cinematic lighting, 8k"
    await queue.put((cid, call.from_user.id, prompt))
    await call.answer("🧠 Усилено")

@dp.callback_query(F.data == "delete")
async def cb_delete(call: CallbackQuery):
    cid = call.message.chat.id
    if call.from_user.id != last_author.get(cid):
        await call.answer("❌ Только автор", show_alert=True)
        return
    await call.message.delete()

# ================== SELF PINGER ==================

async def self_pinger():
    if not SELF_URL:
        return

    await asyncio.sleep(30)
    async with ClientSession() as session:
        while True:
            try:
                await session.get(SELF_URL, timeout=10)
                logging.info("Self-ping OK")
            except Exception as e:
                logging.warning(f"Ping error: {e}")
            await asyncio.sleep(8 * 60)

# ================== WEB ==================

async def health(_):
    return web.Response(text="OK")

async def main():
    asyncio.create_task(image_worker())
    asyncio.create_task(self_pinger())

    app = web.Application()
    app.router.add_get("/", health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
