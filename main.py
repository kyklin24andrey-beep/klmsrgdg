import os
import telebot
import requests
import io
import logging
from threading import Thread
from flask import Flask
from deep_translator import GoogleTranslator

# 1. Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 2. Инициализация Flask (чтобы Render не "усыплял" бота)
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is alive!", 200

def run_flask():
    # Render сам назначит порт через переменную окружения PORT
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# 3. Настройка бота
TOKEN = os.getenv('BOT_TOKEN') # Токен возьмем из настроек Render
bot = telebot.TeleBot(TOKEN)

# Глобальная переменная для ссылки (хранится в памяти, пока бот запущен)
COLAB_URL = ""

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "🚀 Бот готов к работе!\n\n"
                          "**Куда вставлять URL?**\n"
                          "Скопируйте ссылку из Colab (которая .trycloudflare.com) и отправьте боту команду:\n"
                          "`/seturl https://ваша-ссылка.trycloudflare.com/sdapi/v1/txt2img` \n\n"
                          "После этого пишите любой запрос на русском языке.")

@bot.message_handler(commands=['seturl'])
def set_url(message):
    global COLAB_URL
    # Извлекаем ссылку из сообщения
    text_parts = message.text.split(maxsplit=1)
    if len(text_parts) > 1:
        new_url = text_parts[1].strip()
        # Проверяем, что в ссылке есть нужный путь, если нет - добавляем
        if not new_url.endswith('/sdapi/v1/txt2img'):
            new_url = new_url.rstrip('/') + '/sdapi/v1/txt2img'
        
        COLAB_URL = new_url
        bot.reply_to(message, f"✅ URL успешно установлен!\nТеперь я буду отправлять запросы сюда:\n{COLAB_URL}")
        logging.info(f"URL обновлен пользователем: {COLAB_URL}")
    else:
        bot.reply_to(message, "❌ Ошибка! Напишите ссылку после команды, например:\n/seturl https://...trycloudflare.com")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if not COLAB_URL:
        bot.reply_to(message, "⚠️ Ошибка: Вы не установили адрес сервера!\nИспользуйте команду /seturl [ваша_ссылка_из_колаба]")
        return

    user_text = message.text
    msg = bot.reply_to(message, f"🔍 Перевожу: \"{user_text}\" и начинаю рисовать...")

    try:
        # Перевод на английский
        translated_text = GoogleTranslator(source='auto', target='en').translate(user_text)
        logging.info(f"Промпт: {user_text} -> {translated_text}")

        # Запрос в Colab
        response = requests.post(COLAB_URL, json={"prompt": translated_text}, timeout=300)
        
        if response.status_code == 200:
            photo = io.BytesIO(response.content)
            photo.name = 'result.png'
            bot.send_photo(message.chat.id, photo, caption=f"✅ Готово!\n🇬🇧 Prompt: {translated_text}")
            bot.delete_message(message.chat.id, msg.message_id)
        else:
            bot.edit_message_text(f"❌ Ошибка сервера Colab (код {response.status_code}). Проверьте, запущен ли там код.", 
                                  message.chat.id, msg.message_id)
            
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        bot.edit_message_text(f"❌ Произошла ошибка: {str(e)}", message.chat.id, msg.message_id)

if __name__ == '__main__':
    # Запуск Flask в отдельном потоке
    Thread(target=run_flask).start()
    logging.info("Бот запускается...")
    bot.polling(none_stop=True)
