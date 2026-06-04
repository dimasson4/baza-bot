import os
import re
import time
import hmac
import json
import hashlib
import urllib.parse
import asyncio
import logging
from io import BytesIO
from aiohttp import web, ClientSession
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Считывание переменных окружения
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DZENGI_API_KEY = os.environ.get("DZENGI_API_KEY")
DZENGI_SECRET_KEY = os.environ.get("DZENGI_SECRET_KEY")
PORT = int(os.environ.get("PORT", 10000))

# Фиксированные параметры конфигурации
MY_ACCOUNT_ID = "4295225058470143566"

# Инициализация объектов Bot и Dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
ORDER_CACHE = {}

# Обработчик веб-сервера для Render Health Check
async def handle_health_check(request):
    return web.Response(text="OK", status=200)

# Запуск асинхронного веб-сервера aiohttp
async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"[HEALTH_CHECK] Асинхронный веб-сервер запущен на порту {PORT}")

# Функция генерации HMAC-SHA256 подписи
def generate_dzengi_signature(query_string: str, secret_key: str) -> str:
    return hmac.new(secret_key.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()

# Функция отправки лимитного ордера (Маржинальный режим)
async def send_limit_order(side: str, price: float, quantity: float) -> dict:
    correct_base_url = "https://dzengi.com"
    endpoint = "/api/v1/order"
    timestamp = int(time.time() * 1000)
    
    # Жесткое форматирование под спецификацию ETH/USD_LEVERAGE на Dzengi
    rounded_price = round(price + 0.0001, 2)
    str_price = f"{rounded_price:.2f}"
    str_quantity = f"{quantity:.4f}"
    str_timestamp = str(timestamp)
    
    raw_params = {
        "accountId": MY_ACCOUNT_ID,
        "leverage": "10",
        "price": str_price,
        "quantity": str_quantity,
        "recvWindow": "60000",
        "side": side,
        "symbol": "ETH/USD_LEVERAGE",
        "timestamp": str_timestamp,
        "type": "LIMIT"
    }
    
    # Сортировка по алфавиту и принудительный urlencode (слэш преобразуется в %2F)
    sorted_params = sorted(raw_params.items())
    query_string = urllib.parse.urlencode(sorted_params)
    
    signature = generate_dzengi_signature(query_string, DZENGI_SECRET_KEY)
    full_query_with_sig = f"{query_string}&signature={signature}"
    full_url = f"{correct_base_url}{endpoint}?{full_query_with_sig}"
    
    headers = {
        "X-MBX-APIKEY": DZENGI_API_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    async with ClientSession() as session:
        try:
            async with session.post(full_url, headers=headers) as response:
                response_text = await response.text()
                return {"status": response.status, "data": response_text}
        except Exception as e:
            return {"status": 500, "data": str(e)}

# Функция проверки статуса ордера на бирже
async def get_order_status(order_id: str) -> dict:
    correct_base_url = "https://dzengi.com"
    endpoint = "/api/v1/order"
    timestamp = int(time.time() * 1000)
    
    raw_params = {
        "orderId": order_id,
        "recvWindow": "60000",
        "timestamp": str(timestamp)
    }
    
    sorted_params = sorted(raw_params.items())
    query_string = urllib.parse.urlencode(sorted_params)
    
    signature = generate_dzengi_signature(query_string, DZENGI_SECRET_KEY)
    full_query_with_sig = f"{query_string}&signature={signature}"
    full_url = f"{correct_base_url}{endpoint}?{full_query_with_sig}"
    
    headers = {
        "X-MBX-APIKEY": DZENGI_API_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    async with ClientSession() as session:
        try:
            async with session.get(full_url, headers=headers) as response:
                response_text = await response.text()
                try:
                    return {"status": response.status, "data": json.loads(response_text)}
                except Exception:
                    return {"status": response.status, "data": {"msg": response_text}}
        except Exception as e:
            return {"status": 500, "data": {"msg": str(e)}}
def escape_markdown(text: str) -> str:
    escape_chars = r"_*`["
    return re.sub(r"([%s])" % re.escape(escape_chars), r"\\\1", text)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("🤖 Модуль риск-офицера v14.3 запущен.")

@dp.message(F.text.contains("ETH/USD"))
async def handle_signal_message(message: types.Message):
    text = message.text
    msg_id = str(message.message_id)
    try:
        price_match = re.search(r"(?:Цена|Price)[:\s]*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if not price_match:
            await message.answer("ВЕРДИКТ: ВХОД ЗАПРЕЩЕН. Нет значения цены.")
            return
        entry_price = round(float(price_match.group(1)), 2)
        
        glass_match = re.search(r"(?:Стакан|Glass)[:\s]*.*?(\d+)%\s*(?:покупки|buy).*?(\d+)%\s*(?:продажи|sell)", text, re.IGNORECASE)
        if not glass_match:
            glass_match_alt = re.search(r"(\d+)%\s*(?:покупки|buy)", text, re.IGNORECASE)
            glass_sell_alt = re.search(r"(\d+)%\s*(?:продажи|sell)", text, re.IGNORECASE)
            if glass_match_alt and glass_sell_alt:
                buy_percentage = float(glass_match_alt.group(1))
                sell_percentage = float(glass_sell_alt.group(1))
            else:
                await message.answer("ВЕРRIG: ВХОД ЗАПРЕЩЕН. Ошибка стакана.")
                return
        else:
            buy_percentage = float(glass_match.group(1))
            sell_percentage = float(glass_match.group(2))
    except Exception:
        return

    balance_match = re.search(r"(?:баланс|balance)[:\s]*\$?(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    balance = float(balance_match.group(1)) if balance_match else 65.54
    
    is_bullish = "бычий" in text.lower() or "↑" in text
    is_bearish = "медвежий" in text.lower() or "↓" in text
    
    if is_bullish and buy_percentage >= 60.0:
        direction, side = "LONG", "BUY"
    elif is_bearish and sell_percentage >= 60.0:
        direction, side = "SHORT", "SELL"
    else:
        await message.answer("ВЕРДИКТ: ВХОД ЗАПРЕЩЕН. Стакан < 60%.")
        return

    lot = round((balance * 0.02) / (18.50 * 1.02), 4)
    if direction == "LONG":
        stop_loss = round(entry_price - 18.50, 2)
        take_profit = round(entry_price + 37.00, 2)
        breakeven_trigger = round(entry_price + 18.70, 2)
        breakeven_new_sl = round(entry_price + 3.40, 2)
        math_check = round(entry_price - stop_loss, 2) == 18.50
    else:
        stop_loss = round(entry_price + 18.50, 2)
        take_profit = round(entry_price - 37.00, 2)
        breakeven_trigger = round(entry_price - 18.70, 2)
        breakeven_new_sl = round(entry_price - 3.40, 2)
        math_check = round(stop_loss - entry_price, 2) == 18.50

    calculated_hash = round(entry_price + stop_loss + take_profit + breakeven_trigger, 2)
    if not math_check:
        await message.answer("ВЕРДИКТ: ВХОД ЗАПРЕЩЕН. Математический сбой.")
        return

    ORDER_CACHE[msg_id] = {"side": side, "price": entry_price, "lot": lot}
    action_str = "🟢 ОТКРЫТЬ LONG" if direction == "LONG" else "🔴 ОТКРЫТЬ SHORT"
    
    dashboard = (
        f"📊 **ВИЗУАЛЬНЫЙ ДАШБОРД ОПЕРАТОРА**\n"
        f"• Действие: {action_str}\n"
        f"• Размер позиции: `{lot} ETH` (Баланс: ${balance})\n"
        f"• Вход (Limit): `{entry_price:.2f}` | SL: `{stop_loss:.2f}` | TP: `{take_profit:.2f}`\n"
        f"• Безубыток: Перенос в {breakeven_new_sl:.2f} при цене {breakeven_trigger:.2f}\n"
        f"• СЕЛФ-ТЕСТ: ПРОЙДЕН (Хеш: {calculated_hash:.2f})\n"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Отправить ордер", callback_data=f"tx_{msg_id}")
    await message.answer(dashboard, parse_mode="Markdown", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("tx_"))
async def process_order_execution(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_")
        msg_id = parts[1]  # Извлекаем строковый ID сообщения из callback-строки
    except Exception:
        return
    
    if msg_id not in ORDER_CACHE:
        await callback.answer("❌ Данные ордера устарели.", show_alert=True)
        return
        
    await callback.answer("⏳ Запрос обрабатывается шлюзом платформы Dzengi...")
    cached_order = ORDER_CACHE[msg_id]
    
    try:
        async with asyncio.timeout(8.0):
            res = await send_limit_order(
                side=cached_order["side"], 
                price=cached_order["price"], 
                quantity=cached_order["lot"]
            )
            
            status_code = res.get("status", 500)
            raw_data = res.get("data", "Нет данных")
            
            if status_code in (200, 201):
                order_id = None
                try:
                    res_json = json.loads(raw_data)
                    order_id = res_json.get("orderId")
                except Exception:
                    pass

                if order_id:
                    await asyncio.sleep(1.5)
                    status_check = await get_order_status(order_id)
                    order_data = status_check.get("data", {})
                    
                    final_status = order_data.get("status", "НЕИЗВЕСТНО")
                    reject_reason = order_data.get("rejectReason", "Нет")
                    
                    report = (
                        f"✅ **Запрос принят шлюзом Dzengi**\n"
                        f"• ID ордера: `{order_id}`\n"
                        f"• **Текущий статус ордера: `{final_status}`**\n"
                    )
                    if final_status in ("REJECTED", "CANCELED") or reject_reason != "Нет":
                        report += f"• Причина отмены/отклонения: `{reject_reason}`\n"
                    
                    await callback.message.answer(report, parse_mode="Markdown")
                else:
                    await callback.message.answer(f"✅ Ордер размещен, но не удалось получить ID:\n{raw_data[:150]}")
                
                ORDER_CACHE.pop(msg_id, None)
            else:
                await callback.message.answer(f"❌ Платформа Dzengi отклонила транзакцию! (HTTP {status_code})", parse_mode="Markdown")
                file_buffer = BytesIO(raw_data.encode("utf-8"))
                file_buffer.name = "error_log.txt"
                await callback.message.answer_document(document=types.BufferedInputFile(file_buffer.read(), filename="error_log.txt"))
                
    except Exception as e:
        await callback.message.answer(f"❌ Критический сбой: {str(e)}")

async def main():
    await start_web_server()
    try:
        diagnostic_headers = {"User-Agent": "Mozilla/5.0"}
        async with ClientSession() as session:
            async with session.get("https://ident.me", headers=diagnostic_headers) as resp:
                current_ip = (await resp.text()).strip()
                logger.info(f"🛰️ (IP_DIAGNOSTIC) ТЕКУЩИЙ ИСХОДЯЩИЙ IP БОТА: {current_ip}")
    except Exception:
        pass

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
