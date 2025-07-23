import requests
import json
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

def send_telegram_message(chat_id, text, reply_markup=None, message_id=None, parse_mode="Markdown"):
    """Telegram Bot API orqali xabar yuborish/tahrirlash"""
    url = f"{settings.TELEGRAM_API_BASE_URL}{settings.TELEGRAM_BOT_TOKEN}/"
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode
    }
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)

    try:
        if message_id:
            url += "editMessageText"
            payload['message_id'] = message_id
        else:
            url += "sendMessage"

        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Telegram xabar yuborishda xato: {e}")
        return None

def send_telegram_location(chat_id, latitude, longitude):
    """Telegram Bot API orqali lokatsiya yuborish"""
    url = f"{settings.TELEGRAM_API_BASE_URL}{settings.TELEGRAM_BOT_TOKEN}/sendLocation"
    payload = {
        'chat_id': chat_id,
        'latitude': latitude,
        'longitude': longitude
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Telegram lokatsiya yuborishda xato: {e}")
        return None
