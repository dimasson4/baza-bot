import os
import re
import hmac
import time
import json
import telebot
import requests
from threading import Thread
from huggingface_hub import InferenceClient
from http.server import HTTPServer, BaseHTTPRequestHandler

BOT_TOKEN = os.environ.get("BOT_TOKEN")
HF_API_KEY = os.environ.get("HF_API_KEY")
DZENGI_API_KEY = os.environ.get("DZENGI_API_KEY")
DZENGI_SECRET_KEY = os.environ.get("DZENGI_SECRET_KEY")

bot = telebot.TeleBot(BOT_TOKEN)

client = InferenceClient(
    model="meta-llama/Llama-3.3-70B-Instruct",
    token=HF_API_KEY
)

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        return

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

PROTOCOL_V14_4 = """
ИНСТРУКЦИЯ ДЛЯ ИИ: Ты — риск-офицер. Вывод JSON запрещен. Твой ответ — только чистый визуальный дашборд. В конце обязана быть скрытая строка API.
0. КОНТЕКСТ: Дата 04.06.2026. При отсутствии баланса прими его равным $65.54. Инструмент: только ETH/USD.
1. АЛГОРИТМ: Валидация API-плашки разрешена. Время валидно 10 минут. Направление по вектору Тренд 4h и Стакан (>60%).
2. МАТЕМАТИКА: СЛ = 18.50 пунктов, ТП = 37.00 пунктов. Формула лота: Лот = (Баланс * 0.02) / (18.50 * 1.02).
3. ЭТАЛОННЫЙ ОТВЕТ:
### 📊 ВИЗУАЛЬНЫЙ ДАШБОРД ОПЕРАТОРА
* **Действие:** [🔴 ОТКРЫТЬ SHORT / 🟢 ОТКРЫТЬ LONG]
* **Инструмент:** ETH/USD (Плечо: х10)
* **Размер позиции:** [Значение лота] ETH
* **Цена входа (Limit):** [Значение]
* **Защитный стоп (SL):** [Значение]
* **Цель прибыли (TP):** [Значение]
<!-- API:{"v":"14.4","dir":"[SHORT/LONG]","lot":"[Значение]","ep":[Значение],"sl":[Значение],"tp":[Значение],"bu_tr":0,"bu_sl":0,"hash":0} -->
"""

@bot.message_handler(func=lambda message: "ETH/USD" in message.text)
def handle_market_log(message):
    chat_id = message.chat.id
    current_status = os.environ.get("TRADING_STATUS", "ON").strip().upper()
    if current_status == "OFF":
        bot.send_message(chat_id, "⚠️ *ТОРГОВЛЯ ЗАБЛОКИРОВАНА!*", parse_mode="Markdown")
        return

    status_msg = bot.send_message(chat_id, "🤖 *ИИ обрабатывает лог через шлюз HF...*", parse_mode="Markdown")
    full_prompt = f"{PROTOCOL_V14_4}\n\nЛОГ:\n{message.text}"
    
    try:
        response = client.chat_completion(messages=[{"role": "user", "content": full_prompt}], max_tokens=1000, temperature=0.1)
        ai_text = response.choices.message.content
        api_match = re.search(r"<!-- API:(.*?) -->", ai_text)
        clean_text = re.sub(r"<!-- API:(.*?) -->", "", ai_text).strip()
        bot.delete_message(chat_id, status_msg.message_id)
        
        if api_match:
            api_data = json.loads(api_match.group(1))
            keyboard = telebot.types.InlineKeyboardMarkup()
            callback_payload = f"exec_{api_data['dir']}_{api_data['ep']}_{api_data['lot']}"
            keyboard.add(telebot.types.InlineKeyboardButton(text=f"🚀 Отправить {api_data['dir']} на биржу ({api_data['lot']} ETH)", callback_data=callback_payload))
            bot.send_message(chat_id, clean_text, reply_markup=keyboard, parse_mode="Markdown")
        else:
            bot.send_message(chat_id, clean_text)
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {str(e)}", chat_id, status_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("exec_"))
def execute_order_callback(call):
    _, direction, entry_price, lot = call.data.split("_")
    chat_id = call.message.chat.id
    
    bot.answer_callback_query(call.id, text="🚀 Запуск авто-подбора аккаунта...")
    status_msg = bot.send_message(chat_id, "⏳ _Считываю ваш реальный торговый счет на Dzengi..._", parse_mode="Markdown")
    
    # ШАГ 1: Динамически запрашиваем конфигурацию пользователя для поиска реального accountId
    config_url = "https://dzengi.com"
    timestamp = int(time.time() * 1000)
    query_config = f"timestamp={timestamp}"
    sig_config = hmac.new(DZENGI_SECRET_KEY.encode('utf-8'), query_config.encode('utf-8'), digestmod='sha256').hexdigest()
    
    headers = {"X-MBX-APIKEY": DZENGI_API_KEY, "Content-Type": "application/x-www-form-urlencoded"}
    
    real_account_id = None
    try:
        res_config = requests.get(f"{config_url}?{query_config}&signature={sig_config}", headers=headers, timeout=10)
        config_json = res_config.json()
        # Извлекаем левередж-аккаунт с поддержкой суффикса
        real_account_id = config_json.get("userId")  # Торговое ядро Dzengi принимает userId как дефолтный аккаунт-индекс
    except:
        pass

    # Если через конфиг не вытащили, используем дефолтное системное авто-определение ("")
    account_to_send = real_account_id if real_account_id else ""

    # ШАГ 2: Отправка реального маржинального ордера
    url_endpoints = [
        "https://dzengi.com",
        "https://currency.com"
    ]
    
    side = "BUY" if direction == "LONG" else "SELL"
    payload = {
        "symbol": "ETH/USD_LEVERAGE",
        "side": side,
        "quantity": float(lot),
        "type": "MARKET",
        "timestamp": int(time.time() * 1000)
    }
    if account_to_send:
        payload["accountId"] = account_to_send

    # Сборка подписи
    q_str = f"symbol=ETH%2FUSD_LEVERAGE&side={side}"
    if account_to_send:
        q_str += f"&accountId={account_to_send}"
    q_str += f"&quantity={lot}&type={MARKET}&timestamp={payload['timestamp']}"
    
    signature = hmac.new(DZENGI_SECRET_KEY.encode('utf-8'), q_str.encode('utf-8'), digestmod='sha256').hexdigest()
    payload["signature"] = signature

    success = False
    raw_response = "Нет ответа сервера"
    
    for target_url in url_endpoints:
        try:
            response = requests.post(target_url, headers=headers, data=payload, timeout=8)
            raw_response = response.text
            if response.status_code == 200:
                success = True
                break
        except:
            continue

    if success:
        bot.edit_message_text(
            f"✅ *МАРЖИНАЛЬНЫЙ ОРДЕР ИСПОЛНЕН!*\n🔹 *Инструмент:* ETH/USD (Leverage)\n🔹 *Направление:* `{direction}`\n🔹 *Объем:* `{lot} ETH`\n🔹 *Статус:* `Позиция успешно открыта по рынку!`",
            chat_id, status_msg.message_id, parse_mode="Markdown"
        )
    else:
        bot.edit_message_text(
            f"❌ *Отказано торговым ядром!*\n🔹 Ответ биржи: `{raw_response[:150]}`",
            chat_id, status_msg.message_id, parse_mode="Markdown"
        )

if __name__ == "__main__":
    server_thread = Thread(target=run_health_server)
    server_thread.daemon = True
    server_thread.start()
    bot.infinity_polling()
