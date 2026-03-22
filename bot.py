import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import json
import time
from threading import Thread
from datetime import datetime
import asyncio
import locale
import subprocess
import sys
import os

TOKEN = ""

# Попробуем установить русскую локаль для корректного отображения месяцев
try:
    locale.setlocale(locale.LC_TIME, 'ru_RU.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_TIME, 'Russian_Russia.1251')
    except:
        print("⚠️ Не удалось установить русскую локаль, будут использоваться английские названия месяцев")

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
#  СОСТОЯНИЯ ДЛЯ CONVERSATIONHANDLER
# ============================================================
SELECTING_ACTION, VIEWING_SCHEDULE, SELECTING_DAY, SELECTING_WEEK, SELECTING_ANY_WEEK = range(5)

# ============================================================
#  ЗАГРУЗКА РАСПИСАНИЯ
# ============================================================
def load_schedule(filename="schedule_201_2.json"):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None

# ============================================================
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def get_russian_month(month_num):
    """Возвращает русское название месяца"""
    months = {
        1: 'янв.', 2: 'фев.', 3: 'мар.', 4: 'апр.',
        5: 'мая', 6: 'июн.', 7: 'июл.', 8: 'авг.',
        9: 'сен.', 10: 'окт.', 11: 'нояб.', 12: 'дек.'
    }
    return months.get(month_num, '')

def get_current_schedule_date():
    """Возвращает текущую дату в формате расписания (16 мар.)"""
    now = datetime.now()
    day = now.day
    month_rus = get_russian_month(now.month)
    return f"{day} {month_rus}"

def get_russian_weekday(weekday_num):
    """Возвращает название дня недели на русском"""
    weekdays = {
        0: 'Понедельник', 1: 'Вторник', 2: 'Среда',
        3: 'Четверг', 4: 'Пятница', 5: 'Суббота', 6: 'Воскресенье'
    }
    return weekdays.get(weekday_num, '')

def find_today_schedule(schedule_data, week_type='current_week'):
    """Поиск расписания на сегодня"""
    today_date = get_current_schedule_date()
    today_weekday = get_russian_weekday(datetime.now().weekday())
    
    logger.info(f"Ищем расписание: {today_weekday} ({today_date}), неделя: {week_type}")
    
    if week_type not in schedule_data:
        return None
    
    week_data = schedule_data[week_type]
    
    # Ищем по точной дате
    for day in week_data['days']:
        if day['date'] == today_date:
            logger.info(f"✓ Найдено по дате: {day['day_name']} ({day['date']})")
            return day
    
    # Ищем по дню недели
    for day in week_data['days']:
        if day['day_name'] == today_weekday:
            logger.info(f"✓ Найдено по дню недели: {day['day_name']} ({day['date']})")
            return day
    
    # Воскресенье → показываем понедельник следующей недели
    if today_weekday == 'Воскресенье' and week_type == 'current_week':
        next_week_data = schedule_data.get('next_week')
        if next_week_data:
            for day in next_week_data['days']:
                if day['day_name'] == 'Понедельник':
                    logger.info(f"✓ Воскресенье → понедельник след. недели: {day['date']}")
                    return day
    
    logger.info("✗ Расписание на сегодня не найдено")
    return None

def get_all_weeks_list(schedule_data: dict) -> list:
    """
    Возвращает список кортежей (ключ_недели, отображаемое_название)
    Сортировка: ХРОНОЛОГИЧЕСКАЯ (по дате начала недели)
    """
    weeks = []
    exclude_keys = ['combined_at', 'parsed_at', 'merged_at']
    
    months_reverse = {
        'янв.': 1, 'фев.': 2, 'мар.': 3, 'апр.': 4,
        'мая': 5, 'июн.': 6, 'июл.': 7, 'авг.': 8,
        'сен.': 9, 'окт.': 10, 'нояб.': 11, 'дек.': 12
    }
    
    months_eng = {
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
        'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
        'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
    }
    
    current_year = datetime.now().year
    
    for key, value in schedule_data.items():
        if key in exclude_keys or not isinstance(value, dict):
            continue
        
        start_date_str = None
        
        # Определяем дату начала недели для сортировки
        if key in ['current_week', 'next_week']:
            # Берём дату из данных недели
            if 'days' in value and len(value['days']) > 0:
                first_day = value['days'][0]
                date_str = first_day.get('date', '')  # "16 мар."
                try:
                    parts = date_str.split()
                    day = int(parts[0])
                    month_rus = parts[1].rstrip('.')
                    month_num = months_reverse.get(month_rus, 1)
                    # ✅ Используем текущий год для всех
                    start_date_str = f"{current_year}-{month_num:02d}-{day:02d}"
                except:
                    start_date_str = "9999-99-99"
            else:
                start_date_str = "9999-99-99"
        
        elif key.startswith('week_'):
            # Парсим ключ вида week_16_mar_to_22_mar
            try:
                parts = key.replace('week_', '').split('_to_')
                if len(parts) == 2:
                    start = parts[0]  # "16_mar"
                    day_str, month_eng = start.split('_')
                    day = int(day_str)
                    month_num = months_eng.get(month_eng, 1)
                    # ✅ Используем текущий год для всех
                    start_date_str = f"{current_year}-{month_num:02d}-{day:02d}"
                else:
                    start_date_str = "9999-99-99"
            except:
                start_date_str = "9999-99-99"
        else:
            start_date_str = "9999-99-99"
        
        # Формируем отображаемое название
        if key == 'current_week':
            display_name = "📅 Текущая неделя"
        elif key == 'next_week':
            display_name = "📆 Следующая неделя"
        elif key.startswith('week_'):
            try:
                parts = key.replace('week_', '').split('_to_')
                if len(parts) == 2:
                    start, end = parts
                    
                    months_rus_display = {
                        'jan': 'янв.', 'feb': 'фев.', 'mar': 'мар.', 'apr': 'апр.',
                        'may': 'мая', 'jun': 'июн.', 'jul': 'июл.', 'aug': 'авг.',
                        'sep': 'сен.', 'oct': 'окт.', 'nov': 'ноя.', 'dec': 'дек.'
                    }
                    
                    def format_date_part(date_part):
                        d, m = date_part.split('_')
                        return f"{d} {months_rus_display.get(m, m)}"
                    
                    display_name = f"📆 {format_date_part(start)} – {format_date_part(end)}"
                else:
                    display_name = key
            except:
                display_name = key
        else:
            display_name = key
        
        weeks.append((key, display_name, start_date_str))
    
    # ✅ СОРТИРОВКА ПО ДАТЕ (теперь правильно!)
    weeks.sort(key=lambda x: x[2])
    
    return [(key, name) for key, name, _ in weeks]

# ============================================================
#  КЛАВИАТУРЫ
# ============================================================

def get_main_keyboard():
    """Главная клавиатура бота"""
    keyboard = [
        ['📅 Расписание на сегодня', '📋 Текущая неделя'],
        ['📆 Следующая неделя', '🗓️ Все недели'], 
        ['🔄 Обновить расписание', '/start'],
        ['❓ Помощь']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_week_keyboard():
    """Клавиатура выбора недели (для старого меню)"""
    keyboard = [
        ['📅 Текущая неделя', '📆 Следующая неделя'],
        ['🔙 Назад']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_all_weeks_keyboard(schedule_data: dict) -> ReplyKeyboardMarkup:
    """Клавиатура со списком ВСЕХ доступных недель"""
    weeks = get_all_weeks_list(schedule_data)
    keyboard = [[display_name] for _, display_name in weeks]
    keyboard.append(['🔙 Назад'])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_days_keyboard(schedule_data: dict, week_key: str) -> ReplyKeyboardMarkup:
    """Клавиатура с днями для указанной недели (поддерживает любые ключи)"""
    keyboard = []
    if week_key in schedule_data and isinstance(schedule_data[week_key], dict):
        week_data = schedule_data[week_key]
        if 'days' in week_data:
            for day in week_data['days']:
                keyboard.append([f"{day['day_name']} ({day['date']})"])
    keyboard.append(['🔙 Назад'])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

# ============================================================
#  ЗАПУСК ПАРСЕРА
# ============================================================

def run_schedule_parser_sync():
    """Синхронная версия запуска парсера"""
    try:
        possible_parser_files = ["api_parser.py"]
        parser_script = next((s for s in possible_parser_files if os.path.exists(s)), None)
        
        if not parser_script:
            return False, "Файл парсера не найден. Проверьте наличие schedule_parser.py, schedule.py или parser.py"
        
        print(f"🚀 Запускаем парсер: {parser_script}")
        
        result = subprocess.run(
            [sys.executable, parser_script],
            capture_output=True, text=True, timeout=120,
            encoding='utf-8', errors='ignore'
        )
        
        print(f"Парсер завершился с кодом: {result.returncode}")
        
        if result.returncode == 0:
            success_message = "Расписание успешно обновлено! 🎉"
            if result.stdout:
                lines = result.stdout.split('\n')
                important = [l for l in lines if any(x in l for x in ['✅', '❌', '📊'])]
                if important:
                    success_message += f"\n\nДетали:\n" + "\n".join(important[-5:])
            return True, success_message
        else:
            error = result.stderr or result.stdout or "Неизвестная ошибка"
            if "Chrome" in error or "driver" in error:
                error = "Ошибка браузера. Проверьте установку Chrome и ChromeDriver."
            elif "timeout" in error.lower():
                error = "Таймаут операции. Сайт может быть перегружен."
            else:
                error = error[:300] + "..." if len(error) > 300 else error
            return False, f"Ошибка при обновлении:\n{error}"
            
    except subprocess.TimeoutExpired:
        return False, "Таймаут при обновлении (процесс занял слишком много времени)"
    except Exception as e:
        return False, f"Ошибка при запуске парсера: {str(e)}"

# ============================================================
#  ОБРАБОТЧИКИ КОМАНД
# ============================================================

async def update_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обновление расписания"""
    user = update.message.from_user
    logger.info(f"Пользователь {user.first_name} запустил обновление")
    
    await update.message.reply_text(
        "🔄 Запускаю обновление расписания...\n⏳ Пожалуйста, подождите...",
        reply_markup=get_main_keyboard()
    )
    
    try:
        success, result_message = run_schedule_parser_sync()
        if success:
            await update.message.reply_text(
                f"✅ {result_message}\nТеперь вы можете просмотреть актуальное расписание.",
                reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text(
                f"❌ {result_message}\nПопробуйте позже.",
                reply_markup=get_main_keyboard()
            )
    except Exception as e:
        logger.error(f"Ошибка в update_schedule: {e}")
        await update.message.reply_text(
            f"❌ Произошла ошибка:\n{str(e)[:500]}",
            reply_markup=get_main_keyboard()
        )
    
    return SELECTING_ACTION

async def show_today_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать расписание на сегодня"""
    schedule_data = load_schedule()
    if not schedule_data:
        await update.message.reply_text(
            "❌ Расписание не найдено. Нажмите '🔄 Обновить расписание'",
            reply_markup=get_main_keyboard()
        )
        return SELECTING_ACTION
    
    today_weekday = datetime.now().weekday()
    week_type = 'next_week' if today_weekday == 6 else 'current_week'
    
    today_schedule = find_today_schedule(schedule_data, week_type)
    today_date = get_current_schedule_date()
    today_weekday_name = get_russian_weekday(today_weekday)
    week_label = "текущей" if week_type == 'current_week' else "следующей"
    
    if not today_schedule or not today_schedule['lessons']:
        await update.message.reply_text(
            f"📅 На сегодня ({today_weekday_name}, {today_date}) занятий нет 🎉\n(данные из {week_label} недели)",
            reply_markup=get_main_keyboard()
        )
    else:
        message = f"📅 Расписание на сегодня ({today_weekday_name}, {today_date}):\n\n"
        for i, lesson in enumerate(today_schedule['lessons'], 1):
            message += f"{i}. ⏰ {lesson['time_range']}\n   📚 {lesson['subject']}\n"
            message += f"   👨‍🏫 {lesson['teacher']}\n   🏫 {lesson['room']} | {lesson['type']}\n\n"
        await update.message.reply_text(message, reply_markup=get_main_keyboard())
    
    return SELECTING_ACTION

async def show_week_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE, week_key: str, title: str) -> int:
    """Универсальная функция показа расписания недели"""
    schedule_data = load_schedule()
    if not schedule_data or week_key not in schedule_data:
        await update.message.reply_text(
            f"❌ Расписание ({title}) не найдено. Нажмите '🔄 Обновить расписание'",
            reply_markup=get_main_keyboard()
        )
        return SELECTING_ACTION
    
    week_data = schedule_data[week_key]
    message = f"{title}:\n\n"
    
    for day in week_data['days']:
        message += f"📅 {day['day_name']} ({day['date']}):\n"
        if not day['lessons']:
            message += "   🎉 Нет занятий\n\n"
        else:
            for i, lesson in enumerate(day['lessons'], 1):
                message += f"   {i}. ⏰ {lesson['time_range']}\n      📚 {lesson['subject']}\n"
                message += f"      👨‍🏫 {lesson['teacher']}\n      🏫 {lesson['room']} | {lesson['type']}\n\n"
    
    # Разбивка длинных сообщений
    if len(message) > 4096:
        parts = [message[i:i+4096] for i in range(0, len(message), 4096)]
        for i, part in enumerate(parts):
            markup = get_main_keyboard() if i == len(parts) - 1 else None
            await update.message.reply_text(part, reply_markup=markup)
    else:
        await update.message.reply_text(message, reply_markup=get_main_keyboard())
    
    return SELECTING_ACTION

async def show_current_week_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await show_week_schedule(update, context, 'current_week', "📋 Расписание на текущую неделю")

async def show_next_week_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await show_week_schedule(update, context, 'next_week', "📆 Расписание на следующую неделю")

# ============================================================
#  НОВЫЕ ФУНКЦИИ ДЛЯ "ВСЕ НЕДЕЛИ"
# ============================================================

async def select_any_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать список всех доступных недель"""
    schedule_data = load_schedule()
    if not schedule_data:
        await update.message.reply_text(
            "❌ Расписание не найдено. Нажмите '🔄 Обновить расписание'",
            reply_markup=get_main_keyboard()
        )
        return SELECTING_ACTION
    
    weeks = get_all_weeks_list(schedule_data)
    if not weeks:
        await update.message.reply_text("❌ Недели не найдены в расписании", reply_markup=get_main_keyboard())
        return SELECTING_ACTION
    
    await update.message.reply_text("📆 Выберите неделю для просмотра:", reply_markup=get_all_weeks_keyboard(schedule_data))
    return SELECTING_ANY_WEEK

async def handle_selected_any_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора недели из списка всех недель — ПОКАЗЫВАЕМ ВСЮ НЕДЕЛЮ"""
    schedule_data = load_schedule()
    if not schedule_data:
        await update.message.reply_text("❌ Расписание не найдено", reply_markup=get_main_keyboard())
        return SELECTING_ACTION
    
    selected_text = update.message.text
    weeks = get_all_weeks_list(schedule_data)
    selected_key = next((key for key, name in weeks if name == selected_text), None)
    
    if not selected_key or selected_key not in schedule_data:
        await update.message.reply_text("❌ Неделя не найдена", reply_markup=get_main_keyboard())
        return SELECTING_ACTION
    
    # ✅ ПОКАЗЫВАЕМ ПОЛНОЕ РАСПИСАНИЕ НЕДЕЛИ (вместо выбора дня)
    if selected_key == 'current_week':
        return await show_current_week_schedule(update, context)
    elif selected_key == 'next_week':
        return await show_next_week_schedule(update, context)
    else:
        # Для недель вида week_16_mar_to_22_mar
        return await show_any_week_schedule(update, context, selected_key)
    
async def show_any_week_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE, week_key: str) -> int:
    """Показать полное расписание для любой недели по ключу"""
    schedule_data = load_schedule()
    if not schedule_data or week_key not in schedule_data:
        await update.message.reply_text(
            "❌ Расписание не найдено. Нажмите '🔄 Обновить расписание'",
            reply_markup=get_main_keyboard()
        )
        return SELECTING_ACTION
    
    week_data = schedule_data[week_key]
    
    # Формируем заголовок
    if week_key.startswith('week_'):
        try:
            parts = week_key.replace('week_', '').split('_to_')
            if len(parts) == 2:
                start, end = parts
                def format_date_part(date_part):
                    day, month = date_part.split('_')
                    months = {
                        'jan': 'янв.', 'feb': 'фев.', 'mar': 'мар.', 'apr': 'апр.',
                        'may': 'мая', 'jun': 'июн.', 'jul': 'июл.', 'aug': 'авг.',
                        'sep': 'сен.', 'oct': 'окт.', 'nov': 'ноя.', 'dec': 'дек.'
                    }
                    return f"{day} {months.get(month, month)}"
                start_fmt = format_date_part(start)
                end_fmt = format_date_part(end)
                title = f"📆 Расписание на неделю: {start_fmt} – {end_fmt}"
            else:
                title = f"📆 Расписание: {week_key}"
        except:
            title = f"📆 Расписание: {week_key}"
    else:
        title = f"📆 Расписание: {week_key}"
    
    # Формируем сообщение с расписанием
    message = f"{title}:\n\n"
    
    for day in week_data['days']:
        message += f"📅 {day['day_name']} ({day['date']}):\n"
        if not day['lessons']:
            message += "   🎉 Нет занятий\n\n"
        else:
            for i, lesson in enumerate(day['lessons'], 1):
                message += f"   {i}. ⏰ {lesson['time_range']}\n"
                message += f"      📚 {lesson['subject']}\n"
                message += f"      👨‍🏫 {lesson['teacher']}\n"
                message += f"      🏫 {lesson['room']} | {lesson['type']}\n\n"
    
    # Разбивка длинных сообщений
    if len(message) > 4096:
        parts = [message[i:i+4096] for i in range(0, len(message), 4096)]
        for i, part in enumerate(parts):
            markup = get_main_keyboard() if i == len(parts) - 1 else None
            await update.message.reply_text(part, reply_markup=markup)
    else:
        await update.message.reply_text(message, reply_markup=get_main_keyboard())
    
    return SELECTING_ACTION

async def handle_message_selecting_any_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора недели — ПОКАЗЫВАЕМ ВСЮ НЕДЕЛЮ"""
    text = update.message.text
    
    if text == '🔙 Назад':
        return await start(update, context)
    
    schedule_data = load_schedule()
    if schedule_data:
        weeks = get_all_weeks_list(schedule_data)
        # Если пользователь выбрал неделю из списка
        for key, name in weeks:
            if name == text:
                if key == 'current_week':
                    return await show_current_week_schedule(update, context)
                elif key == 'next_week':
                    return await show_next_week_schedule(update, context)
                else:
                    return await show_any_week_schedule(update, context, key)
    
    await update.message.reply_text(
        "Пожалуйста, выберите неделю из предложенных вариантов:",
        reply_markup=get_all_weeks_keyboard(schedule_data)
    )
    return SELECTING_ANY_WEEK

# ============================================================
#  ВЫБОР ДНЯ И ПОКАЗ РАСПИСАНИЯ
# ============================================================

async def select_week_for_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Старый метод выбора недели (для обратной совместимости)"""
    schedule_data = load_schedule()
    if not schedule_data:
        await update.message.reply_text(
            "❌ Расписание не найдено. Нажмите '🔄 Обновить расписание'",
            reply_markup=get_main_keyboard()
        )
        return SELECTING_ACTION
    
    await update.message.reply_text("Выберите неделю для просмотра:", reply_markup=get_week_keyboard())
    return SELECTING_WEEK

async def select_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать дни выбранной недели"""
    schedule_data = load_schedule()
    if not schedule_data:
        await update.message.reply_text(
            "❌ Расписание не найдено. Нажмите '🔄 Обновить расписание'",
            reply_markup=get_main_keyboard()
        )
        return SELECTING_ACTION
    
    week_type = context.user_data.get('selected_week', 'current_week')
    week_label = 'текущая' if week_type == 'current_week' else 'следующая'
    
    await update.message.reply_text(
        f"Выберите день для просмотра расписания ({week_label} неделя):",
        reply_markup=get_days_keyboard(schedule_data, week_type)
    )
    return SELECTING_DAY

async def show_day_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать расписание выбранного дня"""
    schedule_data = load_schedule()
    if not schedule_data:
        await update.message.reply_text("❌ Расписание не найдено", reply_markup=get_main_keyboard())
        return SELECTING_ACTION
    
    selected_day = update.message.text
    week_type = context.user_data.get('selected_week', 'current_week')
    
    if week_type not in schedule_data:
        await update.message.reply_text("❌ Данные недели не найдены", reply_markup=get_main_keyboard())
        return SELECTING_ACTION
    
    week_data = schedule_data[week_type]
    target_day = next((d for d in week_data['days'] if f"{d['day_name']} ({d['date']})" == selected_day), None)
    
    if not target_day:
        await update.message.reply_text("❌ День не найден", reply_markup=get_main_keyboard())
        return SELECTING_ACTION
    
    week_label = "текущей" if week_type == 'current_week' else "следующей"
    message = f"📅 {target_day['day_name']} ({target_day['date']})\n({week_label} неделя):\n\n"
    
    if not target_day['lessons']:
        message += "🎉 Нет занятий"
    else:
        for i, lesson in enumerate(target_day['lessons'], 1):
            message += f"{i}. ⏰ {lesson['time_range']}\n   📚 {lesson['subject']}\n"
            message += f"   👨‍🏫 {lesson['teacher']}\n   🏫 {lesson['room']} | {lesson['type']}\n\n"
    
    await update.message.reply_text(message, reply_markup=get_main_keyboard())
    return SELECTING_ACTION

# ============================================================
#  ПОМОЩЬ И СТАРТ
# ============================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Справка по командам"""
    help_text = """
🤖 **Команды бота:**

📅 **Расписание на сегодня** - занятия на сегодня
📋 **Текущая неделя** - всё расписание текущей недели  
📆 **Следующая неделя** - расписание следующей недели
🗓️ **Все недели** - выбрать любую загруженную неделю 🆕
🔄 **Обновить расписание** - получить актуальные данные
❓ **Помощь** - эта справка

⚡ **Быстрые команды:**
/start — запустить бота
/today — расписание на сегодня
/current_week — текущая неделя
/next_week — следующая неделя
/all_weeks — все недели 🆕
/update_schedule — обновить расписание
/help — показать справку
    """
    await update.message.reply_text(help_text, reply_markup=get_main_keyboard())
    return SELECTING_ACTION

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Команда /start"""
    user = update.message.from_user
    logger.info(f"Пользователь {user.first_name} запустил бота")
    
    context.user_data.clear()
    today_date = get_current_schedule_date()
    today_weekday = get_russian_weekday(datetime.now().weekday())
    
    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋\n"
        f"Сегодня: {today_weekday}, {today_date}\n"
        "Я бот для просмотра расписания группы 201/2.\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )
    return SELECTING_ACTION

# ============================================================
#  КОМАНДЫ-ЯРЛЫКИ
# ============================================================

async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await show_today_schedule(update, context)

async def current_week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await show_current_week_schedule(update, context)

async def next_week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await show_next_week_schedule(update, context)

async def all_weeks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await select_any_week(update, context)

async def update_schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await update_schedule(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена действия"""
    user = update.message.from_user
    logger.info(f"Пользователь {user.first_name} отменил действие")
    await update.message.reply_text('Действие отменено', reply_markup=get_main_keyboard())
    return ConversationHandler.END

# ============================================================
#  ОБРАБОТЧИКИ СООБЩЕНИЙ ПО СОСТОЯНИЯМ
# ============================================================

async def handle_message_selecting_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка в главном меню"""
    text = update.message.text
    
    handlers = {
        '📅 Расписание на сегодня': show_today_schedule,
        '📋 Текущая неделя': show_current_week_schedule,
        '📆 Следующая неделя': show_next_week_schedule,
        '🗓️ Все недели': select_any_week, 
        '🔄 Обновить расписание': update_schedule,
        '❓ Помощь': help_command,
    }
    
    if text in handlers:
        return await handlers[text](update, context)
    elif text == '🔙 Назад':
        return await start(update, context)
    else:
        await update.message.reply_text(
            "Не понимаю команду \nИспользуйте кнопки меню или /help",
            reply_markup=get_main_keyboard()
        )
        return SELECTING_ACTION

async def handle_message_selecting_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора недели (старое меню)"""
    text = update.message.text
    
    if text == '📅 Текущая неделя':
        context.user_data['selected_week'] = 'current_week'
        return await select_day(update, context)
    elif text == '📆 Следующая неделя':
        context.user_data['selected_week'] = 'next_week'
        return await select_day(update, context)
    elif text == '🔙 Назад':
        return await start(update, context)
    else:
        await update.message.reply_text(
            "Пожалуйста, выберите неделю из предложенных вариантов:",
            reply_markup=get_week_keyboard()
        )
        return SELECTING_WEEK

async def handle_message_selecting_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора дня"""
    text = update.message.text
    
    if text == '🔙 Назад':
        return await select_week_for_days(update, context)
    
    schedule_data = load_schedule()
    week_type = context.user_data.get('selected_week', 'current_week')
    
    if schedule_data and week_type in schedule_data:
        for day in schedule_data[week_type]['days']:
            if f"{day['day_name']} ({day['date']})" == text:
                return await show_day_schedule(update, context)
    
    await update.message.reply_text(
        "Пожалуйста, выберите день из предложенных вариантов:",
        reply_markup=get_days_keyboard(schedule_data, week_type)
    )
    return SELECTING_DAY

# ============================================================
#  ЗАПУСК БОТА
# ============================================================

def main():
    application = Application.builder().token(token=TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SELECTING_ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message_selecting_action)],
            SELECTING_ANY_WEEK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message_selecting_any_week)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("current_week", current_week_command))
    application.add_handler(CommandHandler("next_week", next_week_command))
    application.add_handler(CommandHandler("all_weeks", all_weeks_command))
    application.add_handler(CommandHandler("update_schedule", update_schedule_command))
    application.add_handler(CommandHandler("help", help_command))
    
    print("✅ Бот запущен...")
    print(f"📅 Текущая дата: {get_current_schedule_date()}")
    application.run_polling()

if __name__ == '__main__':
    main()
