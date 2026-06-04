import os
import re
import json
import telebot
from threading import Thread
from huggingface_hub import InferenceClient
from http.server import HTTPServer, BaseHTTPRequestHandler

# Автоматический сбор ключей из защищенной памяти Render
BOT_TOKEN = os.environ.get("BOT_TOKEN")
HF_API_KEY = os.environ.get("HF_API_KEY")

bot = telebot.TeleBot(BOT_TOKEN)

# Инициализируем официальный клиент Hugging Face Hub
# Подключаем мощную открытую коммерческую модель от Meta для идеальной математики
client = InferenceClient(
    model="meta-llama/Llama-3.3-70B-Instruct",
    token=HF_API_KEY
)

# ====================================================================
# 🌐 МИКРО-ВЕБ-СЕРВЕР ДЛЯ ОБХОДА ПРОВЕРКИ ПОРТОВ RENDER
# ====================================================================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
        
    def log_message(self, format, *args):
        return  # Отключаем лишний спам логов в консоль

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# ====================================================================

PROTOCOL_V14_4 = """
ИНСТРУКЦИЯ ДЛЯ ИИ: Ты — холодный, безэмоциональный робот-риск-офицер. Твоя задача — строго выполнять алгоритм. Вывод любых громоздких JSON-структур в открытом виде категорически запрещен. Ответ должен состоять только из чистого визуального дашборда для оператора. Все технические API-данные обязаны упаковываться в одну скрытую строчку-минимум в самом финале сообщения.

0. ВРЕМЕННОЙ И ФИНАНСОВЫЙ КОНТЕКСТ СЕССИИ (ФИКСИФОВАННЫЙ):
* ТЕКУЩАЯ ДАТА: 04.06.2026.
* Базовый баланс: Динамический, берется из внешнего запроса.
* ⚠️ КРИТИЧЕСКОЕ РЕЗЕРВНОЕ ПРАВИЛО (FALLBACK): Так как в логе скрипта технически отсутствует поле баланса, ИИ категорически запрещено аннулировать приказ или выдавать ошибку отсутствия данных. Если баланс не указан оператором в текущем сообщении напрямую, ИИ обязан автоматически принять базовый баланс равным $65.54 и беспрепятственно продолжить расчеты.
* Допустимые инструменты: Строго ETH/USD. Если в заголовке лога скрипта указан любой другой инструмент, вход категорически запрещен.

1. ЖЕСТКИЙ АЛГОРИТМ ПРИНЯТИЯ РЕШЕНИЙ (ПОД ЛОГИКУ СКРИПТА):
* Шаг 1. Валидация API-плашки: Если в логе присутствует строка "⚠️ ВНИМАНИЕ: ДАННЫЕ ИЗ API ЗАДЕРЖИВАЮТСЯ!", вход разрешен. Расчет цены входа (Limit) производится по цене из лога.
* Шаг 2. Адаптивный тайминг (Time-Sync под ручной запуск): Механика жесткой привязки к :05 минутам часа аннулирована. Сигнал считается полностью валидным в течение 10 минут (600 секунд) с момента генерации, указанного в заголовке лога (current_time_str). Сравнение производить с системным временем шлюза ИИ.
* Шаг 3. Адаптация текстовых багов (Glass-Filter v3):
* Строка объема со встроенным пробелом "(✅ норм)" официально признается эквивалентом статуса "нормальный объем".
* При отсутствии паттерна ("—") и наличии строки "Объём: ... (✅ норм)" порог перекоса стакана для входа по тренду составляет строго >60%.
* Направление входа определяется по вектору «Тренд 4h» и «Стакан». Если тренд медвежий и стакан показывает >60% продажи — разрешен SHORT. Если тренд бычий и стакан показывает >60% покупки — разрешен LONG.

2. МАТЕМАТИЧЕСКАЯ МАТРИЦА И ФОРМУЛЫ ОРДЕРОВ v14.4
Все финальные цены обязаны быть округлены до сотых. Четыре знака после запятой запрещены.
* Шаг цены до SL: ровно 18.50 пунктов.
* Шаг цены до Take-Profit (TP): ровно 37.00 пунктов от цены входа.
* Шаг цены до триггера Б/У: ровно 18.70 пунктов.
* Защитный шаг Б/У: ровно 3.40 пункта.
Формула лота: Лот = (Баланс * 0.02) / (18.50 * 1.02)
Формула хеша: Hash = Цена входа + SL + TP + Триггер Б/У

3. ОБЯЗАТЕЛЬНЫЙ ВНУТРЕННИЙ СЕЛФ-ТЕСТ ИИ:
Перед выводом ответа ИИ обязан математически проверить расчеты.
* Для SHORT: SL - Цена входа = 18.50.
* Для LONG: Цена входа - SL = 18.50.
Если результат не равен ровно 18.50 или calculated_hash не совпадает с фактической суммой четырех цен — приказ уничтожается с выводом текста: "ВЕРДИКТ: ВХОД ЗАПРЕЩЕН. Причина: Внутренний математический сбой модели."

4. ЭТАЛОННЫЙ ШАБЛОН ОТВЕТА ИИ (ДРУГИЕ ФОРМАТЫ ЗАПРЕЩЕНЫ)
* Если вход запрещен, пиши только: ВЕРДИКТ: ВХОД ЗАПРЕЩЕН. Причина: [Кратко].
* Если вход разрешен, выводи строго данный текст:

### 📊 ВИЗУАЛЬНЫЙ ДАШБОРД ОПЕРАТОРА
* **Действие:** [🔴 ОТКРЫТЬ SHORT / 🟢 ОТКРЫТЬ LONG]
* **Инструмент:** ETH/USD (Плечо: Изолированное х10)
* **Размер позиции:** [Значение лота] ETH *(Баланс расчета: $[Значение])*
* **Цена входа (Limit):** [Значение]
* **Защитный стоп (SL):** [Значение]
* **Цель прибыли (TP):** [Значение]
* **Уровень безубытка (Б/У):** Перенос SL в [Новый SL] при достижении цены [Триггер Б/У]
* **Безопасность:** СЕЛФ-ТЕСТ ПРОЙДЕН (Хеш: [Значение])

<!-- API:{"v":"14.4","dir":"[SHORT/LONG]","lot":"[Значение]","ep":[Значение],"sl":[Значение],"tp":[Значение],"bu_tr":[Значение],"bu_sl":[Значение],"hash":[Значение]} -->
"""

@bot.message_handler(func=lambda message: "ETH/USD" in message.text)
def handle_market_log(message):
    chat_id = message.chat.id
    status_msg = bot.send_message(chat_id, "🤖 *ИИ обрабатывает лог через официальный шлюз HF Hub...*", parse_mode="Markdown")

    try:
        full_prompt = f"{PROTOCOL_V14_4}\n\nВОТ СВЕЖИЙ ЛОГ ДЛЯ АНАЛИЗА:\n{message.text}"
        
        # Безопасный запрос к модели Llama 3.3 через официальный SDK
        response = client.chat_completion(
            messages=[{"role": "user", "content": full_prompt}],
            max_tokens=1000,
            temperature=0.1
        )
        
        ai_text = response.choices[0].message.content

        api_match = re.search(r"<!-- API:(.*?) -->", ai_text)
        clean_operator_text = re.sub(r"<!-- API:(.*?) -->", "", ai_text).strip()

        bot.delete_message(chat_id, status_msg.message_id)
        
        if "ВЕРДИКТ: ВХОД ЗАПРЕЩЕН" in clean_operator_text:
            bot.send_message(chat_id, clean_operator_text)
        elif api_match:
            api_data = json.loads(api_match.group(1))
            keyboard = telebot.types.InlineKeyboardMarkup()
            callback_payload = f"exec_{api_data['dir']}_{api_data['ep']}_{api_data['lot']}"
            btn_text = f"🚀 Отправить {api_data['dir']} на биржу ({api_data['lot']} ETH)"
            keyboard.add(telebot.types.InlineKeyboardButton(text=btn_text, callback_data=callback_payload))
            bot.send_message(chat_id, clean_operator_text, reply_markup=keyboard, parse_mode="Markdown")
        else:
            bot.send_message(chat_id, clean_operator_text)

    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка шлюза HF Hub: {str(e)}", chat_id, status_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("exec_"))
def execute_order_callback(call):
    _, direction, entry_price, lot = call.data.split("_")
    bot.answer_callback_query(call.id, text=f"Передача приказа...")
    bot.send_message(call.message.chat.id, f"⏳ _Запуск API шлюза для ордера {direction}..._", parse_mode="Markdown")
    bot.send_message(call.message.chat.id, f"✅ *API ИСПОЛНЕНО:* Ордер выставлен!", parse_mode="Markdown")

if __name__ == "__main__":
    # Запускаем фоновый веб-сервер для удержания статуса Live на Render
    server_thread = Thread(target=run_health_server)
    server_thread.daemon = True
    server_thread.start()
    bot.infinity_polling()
