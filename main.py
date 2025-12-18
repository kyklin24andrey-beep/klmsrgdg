import telebot
import requests
import io
import logging
from deep_translator import GoogleTranslator

# Настройка логов
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TOKEN = "ТВОЙ_ТОКЕН_БОТА"
bot = telebot.TeleBot(TOKEN)

# Глобальная переменная для ссылки из Colab
COLAB_URL = ""

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "Привет! Я бот-генератор картинок.\n\n"
                          "1. Сначала установи ссылку из Colab командой:\n"
                          "/seturl https://ваша-ссылка.trycloudflare.com/sdapi/v1/txt2img\n"
                          "2. Потом просто пиши мне, что нарисовать (можно по-русски!).")

@bot.message_handler(commands=['seturl'])
def set_url(message):
    global COLAB_URL
    new_url = message.text.replace('/seturl ', '').strip()
    if "trycloudflare.com" in new_url:
        COLAB_URL = new_url
        bot.reply_to(message, f"✅ Ссылка обновлена и готова к работе!")
        logging.info(f"Новый URL установлен: {COLAB_URL}")
    else:
        bot.reply_to(message, "❌ Ошибка: Ссылка должна содержать 'trycloudflare.com'")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if not COLAB_URL:
        bot.reply_to(message, "⚠️ Ошибка: Ссылка на сервер Colab не установлена.\nИспользуйте /seturl [ссылка]")
        return

    user_text = message.text
    bot.reply_to(message, f"⏳ Перевожу и готовлю генерацию для: \"{user_text}\"...")

    try:
        # 1. Автоматический перевод на английский
        translated_text = GoogleTranslator(source='auto', target='en').translate(user_text)
        logging.info(f"Оригинал: {user_text} | Перевод: {translated_text}")

        # 2. Отправка переведенного промпта в Colab
        logging.info("Запрос отправлен в Colab...")
        response = requests.post(COLAB_URL, json={"prompt": translated_text}, timeout=300)
        
        if response.status_code == 200:
            photo = io.BytesIO(response.content)
            photo.name = 'art.png'
            bot.send_photo(message.chat.id, photo, caption=f"✨ Запрос: {translated_text}")
            logging.info("✅ Картинка отправлена!")
        else:
            bot.reply_to(message, f"❌ Сервер Colab ответил ошибкой: {response.status_code}")
            
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        bot.reply_to(message, f"Произошла ошибка: {str(e)}")

if __name__ == '__main__':
    logging.info("Бот запущен...")
    bot.polling(none_stop=True)
