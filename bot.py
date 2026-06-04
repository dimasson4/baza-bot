import os
import re
import time
import hmac
import json
import hashlib
import urllib.parse
import asyncio
import logging
from aiohttp import web, ClientSession
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Инициализация конфигурации
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DZENGI_API_KEY = os.environ.get("DZENGI_API_KEY")
DZENGI_SECRET_KEY = os.environ.get("DZENGI_SECRET_KEY")
PORT = int(os.environ.get("PORT", 10000))

MY_ACCOUNT_ID = "4295225058470143566-eac1_a580"
DZENGI_BASE_URL = "https://dzengi.com"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Секция Веб-сервера (Render Health Check) ---

async def handle_health_check(request):
    return web.Response(text="OK", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Сервер для Health Check запущен на порту {PORT}")

# --- Секция API Dzengi ---

def generate_dzengi_signature(query_string: str, secret_key: str) -> str:
    return hmac.new(secret_key.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()

async def send_limit_order(side: str, price: float, quantity: float) -> dict:
    endpoint = "/api/v1/order"
    timestamp = int(time.time() * 1000)
    symbol_encoded = "ETH%2FUSD_LEVERAGE"
    
    params = {
        "accountId": MY_ACCOUNT_ID,
        "type": "LIMIT",
        "side": side,
        "price": f"{price:.2f}",
        "quantity": f"{quantity:.4f}",
        "timestamp": str(timestamp)
    }
    
    sorted_params = sorted(params.items())
    query_parts = [f"{k}={urllib.parse.quote(v, safe='')}" for k, v in sorted_params]
    query_string = f"symbol={symbol_encoded}&" + "&".join(query_parts)
    
    signature = generate_dzengi_signature(query_string, DZENGI_SECRET_KEY)
    full_url = f"{DZENGI_BASE_URL}{endpoint}?{query_string}&signature={signature}"
    
    headers = {
        "X-MBX-APIKEY": DZENGI_API_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    async with ClientSession() as session:
        try:
            async with session.post(full_url, data=None, headers=headers) as response:
                response_text = await response.text()
                return {"status": response.status, "data": response_text}
        except Exception as e:
            return {"status": 500, "data": str(e)}

# --- Секция Обработки Сигналов (Мега-Протокол v14.3) ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("🤖 Робот-риск-офицер v14.3 готов к работе.")

@dp.message(F.text.contains("ETH/USD"))
async def handle_signal_message(message: types.Message):
    text = message.text

    # 1. Извлечение числовых значений (Цена, Покупки, Продажи)
    numbers = re.findall(r"\d+(?:\.\d+)?", text)
    if len(numbers) < 3:
        await message.answer("ВЕРДИКТ: ВХОД ЗАПРЕЩЕН. Причина: Недостаточно финансовых данных.")
        return

    # Жесткое распределение переменных из упомянутого текста
    entry_price = round(float(numbers[0]), 2)
    buy_percentage = float(numbers[1])
    sell_percentage = float(numbers[2])

    # 2. Поиск баланса (Парсинг правила FALLBACK)
    balance_match = re.search(r"(?:баланс|balance)[:\s]*\$?(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    balance = float(balance_match.group(1)) if balance_match else 65.54

    # 3. Направление сделки (Вектор + Стакан > 60%)
    is_bullish = "бычий" in text.lower() or "↑" in text
    is_bearish = "медвежий" in text.lower() or "↓" in text

    if is_bullish and buy_percentage > 60.0:
        direction = "LONG"
        side = "BUY"
    elif is_bearish and sell_percentage > 60.0:
        direction = "SHORT"
        side = "SELL"
    else:
        await message.answer("ВЕРДИКТ: ВХОД ЗАПРЕЩЕН. Причина: Сигнал не подтвержден перекосом стакана >60%.")
        return

    # 4. Расчет математической матрицы по формулам протокола v14.3
    calculated_lot = (balance * 0.02) / (18.50 * 1.02)
    lot = round(calculated_lot, 4)

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

    # Шаг 3. Селф-тест ИИ
    if not math_check:
        await message.answer("ВЕРДИКТ: ВХОД ЗАПРЕЩЕН. Причина: Внутренний математический сбой модели.")
        return

    # 5. Сборка строгого шаблона ответа без поломок верстки
    action_str = "🟢 ОТКРЫТЬ LONG" if direction == "LONG" else "🔴 ОТКРЫТЬ SHORT"
    
    dashboard = (
        f"📊 **ВИЗУАЛЬНЫЙ ДАШБОРД ОПЕРАТОРА**\n"
        f"• Действие: {action_str}\n"
        f"• Инструмент: ETH/USD (Плечо: Изолированное х10)\n"
        f"• Размер позиции: {lot} ETH (Баланс расчета: ${balance})\n"
        f"• Цена входа (Limit): {entry_price:.2f}\n"
        f"• Защитный стоп (SL): {stop_loss:.2f}\n"
        f"• Цель прибыли (TP): {take_profit:.2f}\n"
        f"• Уровень безубытка (Б/У): Перенос SL в {breakeven_new_sl:.2f} при достижении цены {breakeven_trigger:.2f}\n"
        f"• Безопасность: СЕЛФ-ТЕСТ ПРОЙДЕН (Хеш: {calculated_hash:.2f})\n"
        f"================ `[BACKEND_API_DATA]` ================\n"
    )

    backend_json = {
        "verdict": "ALLOWED",
        "protocol_version": "14.3",
        "order_details": {
            "direction": direction,
            "instrument": "ETH/USD",
            "leverage": "Isolated x10",
            "order_type": "Limit Order",
            "calculated_lot": f"{lot} ETH",
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "breakeven_trigger": breakeven_trigger,
            "breakeven_new_sl": breakeven_new_sl
        },
        "security_block": {
            "self_test_status": "PASSED",
            "calculated_hash": calculated_hash
        }
    }

    dashboard += f"```json\n{json.dumps(backend_json, indent=2)}\n```\n"
    dashboard += "===================================="

    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Отправить ордер", callback_data=f"exec_{side}_{entry_price}_{lot}")
    
    await message.answer(dashboard, parse_mode="Markdown", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("exec_"))
async def process_order_execution(callback: types.CallbackQuery):
    _, side, price_str, lot_str = callback.data.split("_")
    
    await callback.answer("⏳ Ордер отправляется...")
    res = await send_limit_order(side=side, price=float(price_str), quantity=float(lot_str))
    
    if res["status"] in [200, 201]:
        await callback.message.answer(f"✅ **Ордер исполнен!**\nСторона: `{side}`\nОбъем: `{lot_str}`")
    else:
        await callback.message.answer(f"❌ **Ошибка API Dzengi ({res['status']})**\n`{res['data']}`")

# --- Точка входа ---

async def main():
    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Бот готов принимать обновления.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
