import json
import urllib.request
import ssl
from datetime import datetime
from typing import List, Dict, Any, Optional

def fetch_schedule_from_api(api_url: str) -> List[Any]:
    """
    Выполняет GET-запрос к API и возвращает распарсенный массив items.
    """
    try:
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(api_url, timeout=10, context=context) as response:
            data_str = response.read().decode('utf-8')
            data = json.loads(data_str)
            items = json.loads(data['result'])
            return items
    except Exception as e:
        raise RuntimeError(f"Ошибка загрузки данных с {api_url}: {e}")

def parse_week_schedule(items: List[Any]) -> tuple[Dict[str, Any], Optional[str], Optional[str]]:
    """
    Преобразует массив items в формат недели.
    Возвращает: (week_data, start_date, end_date)
    """
    values = {i: items[i] for i in range(len(items))}

    day_indexes = [
        i for i, v in enumerate(items)
        if isinstance(v, dict) and 'lessons' in v and 'date' in v
    ]
    day_indexes.sort()

    MONTHS = {
        1: 'янв.', 2: 'фев.', 3: 'мар.', 4: 'апр.', 5: 'мая', 6: 'июня',
        7: 'июля', 8: 'авг.', 9: 'сен.', 10: 'окт.', 11: 'ноя.', 12: 'дек.'
    }
    DAY_NAMES = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']

    def format_date(date_str: str) -> str:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        return f"{dt.day} {MONTHS[dt.month]}"

    def get_day_name(date_str: str) -> str:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        return DAY_NAMES[dt.weekday()]

    def get_week_dates() -> tuple[Optional[str], Optional[str]]:
        """Возвращает первую и последнюю дату недели"""
        if not day_indexes:
            return None, None
        first_day_idx = day_indexes[0]
        last_day_idx = day_indexes[-1]
        
        first_date = values[values[first_day_idx]['date']]
        last_date = values[values[last_day_idx]['date']]
        
        return first_date, last_date

    days_list = []
    total_lessons = 0

    for day_idx in day_indexes:
        day_obj = values[day_idx]
        lessons_idx = day_obj['lessons']
        date_idx = day_obj['date']

        date_str = values[date_idx]
        day_name = get_day_name(date_str)
        formatted_date = format_date(date_str)

        lesson_indexes = values[lessons_idx]
        day_lessons = []

        for les_idx in lesson_indexes:
            les_obj = values[les_idx]
            if not isinstance(les_obj, dict):
                continue

            muted_idx = les_obj.get('isMuted')
            if muted_idx is not None:
                muted = values[muted_idx]
                if muted is True:
                    continue

            try:
                subject = values[les_obj['title']]
                teacher = values[les_obj['teacher']]
                room = values[les_obj['room']]
                type_ = values[les_obj['type']]
                time_range = f"{values[les_obj['start_time']]}-{values[les_obj['end_time']]}"
            except KeyError as e:
                print(f"Пропущено занятие (индекс {les_idx}), отсутствует ключ {e}")
                continue

            day_lessons.append({
                "subject": subject,
                "teacher": teacher,
                "room": room,
                "type": type_,
                "time_range": time_range
            })

        total_lessons += len(day_lessons)
        days_list.append({
            "day_name": day_name,
            "date": formatted_date,
            "lessons": day_lessons
        })

    now = datetime.now().isoformat()
    start_date, end_date = get_week_dates()
    
    week_data = {
        "days": days_list,
        "total_lessons": total_lessons,
        "parsed_at": now,
        "merged_at": now
    }
    
    return week_data, start_date, end_date

def format_week_key(start_date: str, end_date: str) -> str:
    MONTHS_SHORT = {
        1: 'jan', 2: 'feb', 3: 'mar', 4: 'apr', 5: 'may', 6: 'jun',
        7: 'jul', 8: 'aug', 9: 'sep', 10: 'oct', 11: 'nov', 12: 'dec'
    }
    
    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    
    start_str = f"{start_dt.day}_{MONTHS_SHORT[start_dt.month]}"
    end_str = f"{end_dt.day}_{MONTHS_SHORT[end_dt.month]}"
    
    return f"week_{start_str}_to_{end_str}"

def build_full_schedule(
    current_week_url: str,
    next_week_url: str,
    other_weeks_urls: List[str]
) -> Dict[str, Any]:
    result = {}
    
    # 1. Загружаем текущую неделю
    current_items = fetch_schedule_from_api(current_week_url)
    current_data, _, _ = parse_week_schedule(current_items)
    result["current_week"] = current_data
    
    # 2. Загружаем следующую неделю
    next_items = fetch_schedule_from_api(next_week_url)
    next_data, _, _ = parse_week_schedule(next_items)
    result["next_week"] = next_data
    
    # 3. Загружаем остальные недели
    for i, url in enumerate(other_weeks_urls, 1):
        try:
            items = fetch_schedule_from_api(url)
            week_data, start_date, end_date = parse_week_schedule(items)
            
            if start_date and end_date:
                key = format_week_key(start_date, end_date)
                result[key] = week_data
            else:
                print(f" Не удалось определить даты для недели #{i}")
                
        except Exception as e:
            print(f"Ошибка загрузки недели #{i}: {e}")
    
    result['combined_at'] = datetime.now().isoformat()
    
    return result

def save_schedule_to_file(schedule: Dict[str, Any], filename: str = "schedule.json") -> None:
    """
    Сохраняет расписание в JSON-файл с отступами для читаемости.
    """
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(schedule, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    # Cсылки для текущей и следующей недели
    CURRENT_WEEK_API = "https://timetable.of.by/_app/remote/154fomr/getLessons?payload=W3siaWQiOjEsInR5cGUiOjIsIndlZWtPZmZzZXQiOjN9LCIyMjQwMDM2MDIiLCJncm91cCIsMF0"
    NEXT_WEEK_API    = "https://timetable.of.by/_app/remote/154fomr/getLessons?payload=W3siaWQiOjEsInR5cGUiOjIsIndlZWtPZmZzZXQiOjN9LCIyMjQwMDM2MDIiLCJncm91cCIsMV0"
    
    # Ссылки на остальные недели
    OTHER_WEEKS_API = [
        'https://timetable.of.by/_app/remote/154fomr/getLessons?payload=W3siaWQiOjEsInR5cGUiOjIsIndlZWtPZmZzZXQiOjN9LCIyMjQwMDM2MDIiLCJncm91cCIsLTZd',
        'https://timetable.of.by/_app/remote/154fomr/getLessons?payload=W3siaWQiOjEsInR5cGUiOjIsIndlZWtPZmZzZXQiOjN9LCIyMjQwMDM2MDIiLCJncm91cCIsLTVd',
        'https://timetable.of.by/_app/remote/154fomr/getLessons?payload=W3siaWQiOjEsInR5cGUiOjIsIndlZWtPZmZzZXQiOjN9LCIyMjQwMDM2MDIiLCJncm91cCIsLTRd',
        'https://timetable.of.by/_app/remote/154fomr/getLessons?payload=W3siaWQiOjEsInR5cGUiOjIsIndlZWtPZmZzZXQiOjN9LCIyMjQwMDM2MDIiLCJncm91cCIsLTNd',
        'https://timetable.of.by/_app/remote/154fomr/getLessons?payload=W3siaWQiOjEsInR5cGUiOjIsIndlZWtPZmZzZXQiOjN9LCIyMjQwMDM2MDIiLCJncm91cCIsLTJd',
        'https://timetable.of.by/_app/remote/154fomr/getLessons?payload=W3siaWQiOjEsInR5cGUiOjIsIndlZWtPZmZzZXQiOjN9LCIyMjQwMDM2MDIiLCJncm91cCIsLTFd',
        'https://timetable.of.by/_app/remote/154fomr/getLessons?payload=W3siaWQiOjEsInR5cGUiOjIsIndlZWtPZmZzZXQiOjN9LCIyMjQwMDM2MDIiLCJncm91cCIsMl0',
        'https://timetable.of.by/_app/remote/154fomr/getLessons?payload=W3siaWQiOjEsInR5cGUiOjIsIndlZWtPZmZzZXQiOjN9LCIyMjQwMDM2MDIiLCJncm91cCIsM10',
        'https://timetable.of.by/_app/remote/154fomr/getLessons?payload=W3siaWQiOjEsInR5cGUiOjIsIndlZWtPZmZzZXQiOjN9LCIyMjQwMDM2MDIiLCJncm91cCIsNF0',
        'https://timetable.of.by/_app/remote/154fomr/getLessons?payload=W3siaWQiOjEsInR5cGUiOjIsIndlZWtPZmZzZXQiOjN9LCIyMjQwMDM2MDIiLCJncm91cCIsNV0',
        'https://timetable.of.by/_app/remote/154fomr/getLessons?payload=W3siaWQiOjEsInR5cGUiOjIsIndlZWtPZmZzZXQiOjN9LCIyMjQwMDM2MDIiLCJncm91cCIsNl0'       
    ]
    
    OUTPUT_FILE = "schedule_201_2.json"
    
    try:
        full_schedule = build_full_schedule(
            current_week_url=CURRENT_WEEK_API,
            next_week_url=NEXT_WEEK_API,
            other_weeks_urls=OTHER_WEEKS_API
        )
        save_schedule_to_file(full_schedule, OUTPUT_FILE)
        
    except Exception as e:
        print(f"Ошибка: {e}")
        input("Нажмите Enter для выхода...")