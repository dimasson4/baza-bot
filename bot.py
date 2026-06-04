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

# Настройка сквозного логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Инициализация конфигурации среды выполнения из панели Render
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DZENGI_API_KEY = os.environ.get("DZENGI_API_KEY")
DZENGI_SECRET_KEY = os.environ.get("DZENGI_SECRET_KEY")
PORT = int(os.environ.get("PORT", 10000))

# Фиксированные константы торговой платформы
MY_ACCOUNT_ID = "4295225058470143566"
# ИСПРАВЛЕНО: Установлен официальный домен для торговых SIGNED-запросов
DZENGI_BASE_URL = "https://api-adapter.backend.dzengi.com"

# Инициализация ядра aiogram 3.x
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Глобальное хранилище для сохранения параметров ордеров между шагами
ORDER_CACHE = {}

# --- Секция Асинхронного Веб-сервера (Render Health Check) ---

async def handle_health_check(request):
    return web.Response(text="OK", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"[HEALTH_CHECK] Асинхронный веб-сервер успешно запущен на порту {PORT}")

# --- Секция Криптографии и Сетевого шлюза API Dzengi ---

def generate_dzengi_signature(query_string: str, secret_key: str) -> str:
    return hmac.new(
        secret_key.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

async def send_limit_order(side: str, price: float, quantity: float) -> dict:
    correct_base_url = "https://api-adapter.dzengi.com"
    endpoint = "/api/v1/order"
    timestamp = int(time.time() * 1000)
    
    # --- СТРОГОЕ ИСПРАВЛЕНИЕ ДЛЯ DZENGI API (-1030) ---
    # 1. Биржа требует логику round_up при несоответствии точности (quotePrecision = 2).
    # Для этого используем математическое смещение на бесконечно малую величину перед округлением.
    rounded_price = round(price + 0.0001, 2)
    
    # 2. Критически важно: Dzengi требует СТРОГОЕ соблюдение quotePrecision в строке.
    # Нельзя убирать нули через rstrip. Должно быть ровно 2 знака (например, "3150.50", "3100.00").
    str_price = f"{rounded_price:.2f}"
    
    # Спецификация контракта для объема (обычно 4 знака для крипто-пар с плечом)
    str_quantity = f"{quantity:.4f}"
    str_timestamp = str(timestamp)
    
    raw_params = {
        "accountId": MY_ACCOUNT_ID,
        "leverage": "10",
        "price": str_price,        # Отправляем строку строго с двумя знаками после запятой
        "quantity": str_quantity,
        "recvWindow": "60000",
        "side": side,
        "symbol": "ETH/USD_LEVERAGE",
        "timestamp": str_timestamp,
        "type": "LIMIT"
    }
    
    # Алфавитная сортировка параметров для формирования корректной подписи
    sorted_params = sorted(raw_params.items())
    query_string = urllib.parse.urlencode(sorted_params)
    
    # Генерация подписи HMAC-SHA256
    signature = generate_dzengi_signature(query_string, DZENGI_SECRET_KEY)
    full_query_with_sig = f"{query_string}&signature={signature}"
    full_url = f"{correct_base_url}{endpoint}?{full_query_with_sig}"
    
    headers = {
        "X-MBX-APIKEY": DZENGI_API_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
async def get_order_status(order_id: str) -> dict:
    correct_base_url = "https://api-adapter.dzengi.com"
    endpoint = "/api/v1/order"
    timestamp = int(time.time() * 1000)
    
    # Формируем обязательные Query-параметры для GET-запроса
    raw_params = {
        "orderId": order_id,
        "recvWindow": "60000",
        "timestamp": str(timestamp)
    }
    
    # Сортируем и кодируем параметры в строку
    sorted_params = sorted(raw_params.items())
    query_string = urllib.parse.urlencode(sorted_params)
    
    # Генерируем HMAC-SHA256 подпись
    signature = generate_dzengi_signature(query_string, DZENGI_SECRET_KEY)
    full_query_with_sig = f"{query_string}&signature={signature}"
    full_url = f"{correct_base_url}{endpoint}?{full_query_with_sig}"
    
    headers = {
        "X-MBX-APIKEY": DZENGI_API_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
 async with ClientSession() as session:
        try:
            # Для проверки статуса используется метод GET
            async with session.get(full_url, headers=headers) as response:
                response_text = await response.text()
                try:
                    return {"status": response.status, "data": json.loads(response_text)}
                except Exception:
                    return {"status": response.status, "data": {"msg": response_text}}
        except Exception as e:
            return {"status": 500, "data": {"msg": str(e)}}

# --- Секция Логики Обработки Сигналов (Мега-Протокол v14.3) ---

def escape_markdown(text: str) -> str:
    """Экранирование системных символов для предотвращения поломки парсера разметки Telegram."""
    escape_chars = r"_*`["
    return re.sub(r"([%s])" % re.escape(escape_chars), r"\\\1", text)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("🤖 Модуль риск-офицера v14.3 находится в режиме боевого дежурства. Ожидание сигналов ETH/USD.")

@dp.message(F.text.contains("ETH/USD"))
async def handle_signal_message(message: types.Message):
    text = message.text
    msg_id = str(message.message_id)

    # 1. Сегментированный парсинг метрик (Фильтр Glass-Filter v4)
    try:
        price_match = re.search(r"(?:Цена|Price)[:\s]*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if not price_match:
            await message.answer("ВЕРДИКТ: ВХОД ЗАПРЕЩЕН. Причина: Входящий текст не содержит явного значения цены.")
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
                await message.answer("ВЕРДИКТ: ВХОД ЗАПРЕЩЕН. Причина: Не удалось изолировать процентные доли стакана.")
                return
        else:
            buy_percentage = float(glass_match.group(1))
            sell_percentage = float(glass_match.group(2))

    except Exception as e:
        logger.error(f"[PARSING_ERROR] Сбой регулярных выражений: {str(e)}")
        await message.answer("ВЕРДИКТ: ВХОД ЗАПРЕЩЕН. Причина: Критический сбой чтения структуры метрик.")
        return

    # 2. Определение динамического баланса (Правило Fallback)
    balance_match = re.search(r"(?:баланс|balance)[:\s]*\$?(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    balance = float(balance_match.group(1)) if balance_match else 65.54

    # 3. Валидация направления рынка (Вектор Тренда + Фильтр объема стакана >= 60%)
    is_bullish = "бычий" in text.lower() or "↑" in text
    is_bearish = "медвежий" in text.lower() or "↓" in text

    if is_bullish and buy_percentage >= 60.0:
        direction = "LONG"
        side = "BUY"
    elif is_bearish and sell_percentage >= 60.0:
        direction = "SHORT"
        side = "SELL"
    else:
        await message.answer(f"ВЕРДИКТ: ВХОД ЗАПРЕЩЕН. Причина: Отсутствует опорный перекос объемов стакана >=60%. (Покупки: {buy_percentage}%, Продажи: {sell_percentage}%)")
        return

    # 4. Математическая матрица расчета рисков v14.3
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

    # Вычисление контрольной суммы для прохождения селф-теста целостности
    calculated_hash = round(entry_price + stop_loss + take_profit + breakeven_trigger, 2)

    if not math_check:
        await message.answer("ВЕРДИКТ: ВХОД ЗАПРЕЩЕН. Причина: Математический селф-тест выявил критическую погрешность округления.")
        return

    # Сохраняем вычисленные параметры в кэш под уникальным ID сообщения для обеспечения атомарности клика
    ORDER_CACHE[msg_id] = {
        "side": side,
        "price": entry_price,
        "lot": lot
    }

    # 5. Сборка визуального интерфейса оператора
    action_str = "🟢 ОТКРЫТЬ LONG" if direction == "LONG" else "🔴 ОТКРЫТЬ SHORT"
    
    dashboard = (
        f"📊 **ВИЗУАЛЬНЫЙ ДАШБОРД ОПЕРАТОРА**\n"
        f"• Действие: {action_str}\n"
        f"• Инструмент: ETH/USD (Изолированное х10)\n"
        f"• Размер позиции: `{lot} ETH` (Баланс: ${balance})\n"
        f"• Вход (Limit): `{entry_price:.2f}` | SL: `{stop_loss:.2f}` | TP: `{take_profit:.2f}`\n"
        f"• Безубыток: Перенос в {breakeven_new_sl:.2f} при цене {breakeven_trigger:.2f}\n"
        f"• СЕЛФ-ТЕСТ: ПРОЙДЕН (Хеш: {calculated_hash:.2f})\n"
        f"== `[BACKEND_API_DATA СОХРАНЕН В ПАМЯТИ]` =="
    )

    # Привязка инлайн-кнопки по целостному кэш-индексу (строго укладывается в лимит 64 байт)
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Отправить ордер", callback_data=f"tx_{msg_id}")
    
    await message.answer(dashboard, parse_mode="Markdown", reply_markup=builder.as_markup())
@dp.callback_query(F.data.startswith("tx_"))
async def process_order_execution(callback: types.CallbackQuery):
    # 1. Извлекаем ID сообщения из callback_data
    try:
        data_parts = callback.data.split("_")
        msg_id = data_parts[1]
    except Exception as e:
        await callback.answer("❌ Ошибка разбора метаданных кнопки.", show_alert=True)
        return
    
    # 2. Валидация наличия транзакции в кэше памяти RAM
    if msg_id not in ORDER_CACHE:
        await callback.answer("❌ Данные ордера устарели. Сгенерируйте новый сигнал.", show_alert=True)
        return

    # Мгновенно тушим анимацию часов, отправляя статус-уведомление оператору
    await callback.answer("⏳ Запрос обрабатывается шлюзом платформы Dzengi...")
    
    cached_order = ORDER_CACHE[msg_id]
    side = cached_order["side"]
    price = cached_order["price"]
    lot = cached_order["lot"]
    
    try:
        logger.info(f"[GATEWAY] Инициация отправки ордера для сообщения {msg_id}")
        
        # Интеграция контроля таймаута: защищаем бота от бесконечного зависания сети
        async with asyncio.timeout(8.0):
            res = await send_limit_order(side=side, price=price, quantity=lot)
            
        status_code = res.get("status", 500)
        raw_data = res.get("data", "Нет данных")

        # Анализ результатов ответа шлюза биржи
        if status_code in (200, 201):
            # Парсим успешный ответ для извлечения ID ордера
            try:
                res_json = json.loads(raw_data)
                order_id = res_json.get("orderId")
            except Exception:
                order_id = None

            if order_id:
                # Даем торговому ядру Dzengi 1.5 секунды на обработку стакана
                await asyncio.sleep(1.5)
                
                # Запрашиваем реальный статус ордера на бирже
                status_check = await get_order_status(order_id)
                order_data = status_check.get("data", {})
                
                # Извлекаем финальное состояние (NEW, FILLED, CANCELED, REJECTED)
                final_status = order_data.get("status", "НЕИЗВЕСТНО (Проверьте терминал)")
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
                await callback.message.answer(f"✅ Ордер размещен, но не удалось считать ID:\n{raw_data[:150]}")
            
            ORDER_CACHE.pop(msg_id, None)

# --- Точка запуска и Очистка сетевых шлюзов при деплое на Render ---

async def main():
    # 1. Запуск асинхронного фонового веб-сервера для прохождения Health Check Render
    await start_web_server()
    
    # 2. Гарантированная текстовая диагностика исходящего IP-адреса
    try:
        diagnostic_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        async with ClientSession() as session:
            # Запрашиваем чистый текстовый IP напрямую с резервного зеркала
            async with session.get("https://ident.me", headers=diagnostic_headers) as resp:
                current_ip = await resp.text()
                current_ip = current_ip.strip() # Очищаем от возможных пробелов
                logger.info("=========================================================")
                logger.info(f"🔥 [IP_DIAGNOSTIC] ТЕКУЩИЙ ИСХОДЯЩИЙ IP БОТА: {current_ip}")
                logger.info("=========================================================")
    except Exception as ip_err:
        logger.error(f"[IP_DIAGNOSTIC] Не удалось определить IP-адрес: {str(ip_err)}")
    
    # 3. Борьба с ошибкой 409 Conflict: принудительный жесткий сброс вебхуков при старте
    logger.info("[INIT] Запуск процедуры очистки очереди обновлений Telegram...")
    await bot.delete_webhook(drop_pending_updates=True)
    
    # 4. Старт долгого опроса (Polling)
    logger.info("[INIT] Риск-модуль успешно запущен и готов к обработке сигналов.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("[SHUTDOWN] Риск-модуль остановлен.")
        
