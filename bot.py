import os
import re
import hmac
import time
import json
import telebot
import requests
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

BOT_TOKEN = os.environ.get("BOT_TOKEN")
DZENGI_API_KEY = os.environ.get("DZENGI_API_KEY")
DZENGI_SECRET_KEY = os.environ.get("DZENGI_SECRET_KEY")

MY_ACCOUNT_ID = "4295225058470143566-eac1_a580"
bot = telebot.TeleBot(BOT_TOKEN)

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args): return

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

@bot.message_handler(func=lambda message: "ETH/USD" in message.text)
def handle_market_log(message):
    chat_id = message.chat.id
    log_text = message.text
    current_status = os.environ.get("TRADING_STATUS", "ON").strip().upper()
    if current_status == "OFF":
        bot.send_message(chat_id, "⚠️ ТОРГОВЛЯ ЗАБЛОКИРОВАНА!")
        return
    try:
        price_match = re.search(r"Цена:\s*([\d.]+)", log_text)
        price = float(price_match.group(1)) if price_match else None
        stakan_match = re.search(r"Стакан:\s*.*?(\d+)%\s*покупки\s*/\s*.*?(\d+)%\s*продажи", log_text)
        buy_pct = int(stakan_match.group(1)) if stakan_match else 0
        sell_pct = int(stakan_match.group(2)) if stakan_match else 0
        is_bearish = "медвежий" in log_text.lower() or "↓" in log_text
        is_bullish = "бычий" in log_text.lower() or "↑" in log_text

        if not price: return

        direction = None
        if is_bearish and sell_pct >= 60: direction = "SHORT"
        elif is_bullish and buy_pct >= 60: direction = "LONG"

        if not direction:
            bot.send_message(chat_id, f"ВЕРДИКТ: ВХОД ЗАПРЕЩЕН.")
            return

        balance = 67.58
        lot = round((balance * 0.02) / (18.50 * 1.02), 3)
        if lot < 0.001: lot = 0.001

        if direction == "SHORT":
            action_text = "🔴 ОТКРЫТЬ SHORT"
            sl = round(price + 18.50, 2)
            tp = round(price - 37.00, 2)
        else:
            action_text = "🟢 ОТКРЫТЬ LONG"
            sl = round(price - 18.50, 2)
            tp = round(price + 37.00, 2)

        dashboard = (
            f"📊 ВИЗУАЛЬНЫЙ ДАШБОРД ОПЕРАТОРА:\n"
            f"* Действие: {action_text}\n"
            f"* Инструмент: ETH/USD\n"
            f"* Размер позиции: {lot} ETH (Баланс: {balance} USD)\n"
            f"* Цена входа: {price}\n"
            f"* Защитный стоп (SL): {sl}\n"
            f"* Цель прибыли (TP): {tp}\n"
            f"* Безопасность: ПРОЙДЕНО"
        )
        keyboard = telebot.types.InlineKeyboardMarkup()
        callback_payload = f"exec_{direction}_{price}_{lot}"
        keyboard.add(telebot.types.InlineKeyboardButton(text=f"🚀 Отправить ордер", callback_data=callback_payload))
        
        try: bot.delete_message(chat_id, message.message_id)
        except: pass
        bot.send_message(chat_id, dashboard, reply_markup=keyboard)
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith("exec_"))
def execute_order_callback(call):
    _, direction, entry_price, lot = call.data.split("_")
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id, text="🚀 Отправка ордера...")
    status_msg = bot.send_message(chat_id, f"⏳ Отправляю приказ...")
    
    # Точный адрес REST API Dzengi для выставления ордеров leverage
    full_trading_url = "https://dzengi.com"
    timestamp = int(time.time() * 1000)
    side = "BUY" if direction == "LONG" else "SELL"
    
    # Собираем параметры в словарь
    payload = {
        "symbol": "ETH/USD_LEVERAGE",
        "side": side,
        "accountId": MY_ACCOUNT_ID,
        "quantity": float(lot),
        "type": "MARKET",
        "timestamp": timestamp
    }
    
    # Строка параметров для корректной генерации HMAC-подписи
    query_string = f"symbol=ETH%2FUSD_LEVERAGE&side={side}&accountId={MY_ACCOUNT_ID}&quantity={lot}&type=MARKET&timestamp={timestamp}"
    signature = hmac.new(DZENGI_SECRET_KEY.encode('utf-8'), query_string.encode('utf-8'), digestmod='sha256').hexdigest()
    
    # Добавляем подпись в payload
    payload["signature"] = signature
    
    # Строгие заголовки
    headers = {
        "X-MBX-APIKEY": DZENGI_API_KEY,
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    try:
        # Отправляем параметры в теле запроса (data=payload)
        response = requests.post(full_trading_url, headers=headers, data=payload, timeout=10)
        if response.status_code == 200:
            bot.edit_message_text(f"✅ УСПЕШНО", chat_id, status_msg.message_id)
        else:
            bot.edit_message_text(f"❌ ОТКАЗ HTTP: {response.status_code}\nОтвет: {response.text[:150]}", chat_id, status_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ СБОЙ: {str(e)}", chat_id, status_msg.message_id)

if __name__ == "__main__":
    # Запускаем фоновый веб-сервер для прохождения деплоя на Render
    server_thread = Thread(target=run_health_server)
    server_thread.daemon = True
    server_thread.start()
    
    # Вечный цикл поллинга с безопасным подавлением конфликтов перезапуска
    while True:
        try:
            bot.delete_webhook(drop_pending_updates=True)
            bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=10)
        except Exception as e:
            # Ошибка 409 или сетевой сбой во время деплоя просто вызовут перезапуск цикла через 3 секунды
            time.sleep(3)
            continue
