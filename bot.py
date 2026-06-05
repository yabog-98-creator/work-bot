import asyncio
import os
import json
import calendar
from datetime import datetime, timedelta
 
import gspread
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
 
load_dotenv()
 
BOT_TOKEN = os.getenv("BOT_TOKEN")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME")
ADMIN_ID = 5689888528
 
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
 
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
 
google_creds = json.loads(os.getenv("GOOGLE_CREDENTIALS"))
creds = ServiceAccountCredentials.from_json_keyfile_dict(google_creds, scope)
 
client = gspread.authorize(creds)
spreadsheet = client.open(SPREADSHEET_NAME)
 
sheet = spreadsheet.worksheet("schedule")
problems_sheet = spreadsheet.worksheet("problems")
fines_sheet = spreadsheet.worksheet("fines")
rates_sheet = spreadsheet.worksheet("rates")
 
pending_problems = {}
pending_fines = {}
pending_shift_inputs = {}
 
 
# =========================
# HELPERS
# =========================
 
def is_admin(user_id):
    return int(user_id) == ADMIN_ID
 
 
def main_keyboard(user_id=None):
    keyboard = [
        [
            KeyboardButton(
                text="🚀 Открыть приложение",
                web_app=WebAppInfo(
    url=f"https://work-bot-app.vercel.app/?tg_id={user_id}"
)
        ],
        [KeyboardButton(text="🏠 Главное меню")],
        [KeyboardButton(text="📅 Мои смены"), KeyboardButton(text="💰 Моя зарплата")],
        [KeyboardButton(text="📊 Мои часы"), KeyboardButton(text="💸 Мои штрафы")]
    ]
 
    if user_id and is_admin(user_id):
        keyboard.append([KeyboardButton(text="👑 Панель управления")])
 
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
 
 
def admin_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Сотрудники")],
            [KeyboardButton(text="📋 Подтверждённые смены"), KeyboardButton(text="⚠️ Проблемные смены")],
            [KeyboardButton(text="📊 Часы сотрудников"), KeyboardButton(text="💰 Зарплаты")],
            [KeyboardButton(text="📈 Отчёт за месяц"), KeyboardButton(text="📄 Все штрафы")],
            [KeyboardButton(text="⬅️ Назад")]
        ],
        resize_keyboard=True
    )
 
 
def get_headers():
    headers = sheet.row_values(1)
    return {name: index + 1 for index, name in enumerate(headers)}
 
 
def parse_hours(shift):
    shift = str(shift).replace(" ", "")
    start, end = shift.split("-")
    start = int(start.split(":")[0])
    end = int(end.split(":")[0])
 
    if end < start:
        end += 24
 
    return end - start
 
 
def parse_date(date_text):
    return datetime.strptime(str(date_text).strip(), "%d.%m.%Y")
 
 
def get_row_value(row, headers, column_name):
    index = headers.get(column_name)
    if not index:
        return ""
    if len(row) < index:
        return ""
    return row[index - 1]
 
 
def get_confirmed_hours(row):
    hours = row.get("confirmed_hours") or row.get("hours")
 
    try:
        if hours not in [None, "", "None"]:
            return float(hours)
    except Exception:
        pass
 
    try:
        if str(row.get("confirmed", "")).strip().upper() == "YES":
            return float(parse_hours(row.get("shift")))
    except Exception:
        pass
 
    return 0
 
 
 
def get_employee_rate(telegram_id):
    records = rates_sheet.get_all_records()
 
    for row in records:
        if str(row.get("telegram_id", "")).strip() == str(telegram_id).strip():
            try:
                return float(row.get("rate", 0))
            except Exception:
                return 0
 
    return 0
 
 
def calculate_salary(telegram_id):
    records = sheet.get_all_records()
    total_hours = 0
    confirmed_count = 0
 
    for row in records:
        if str(row.get("telegram_id", "")).strip() == str(telegram_id).strip():
            if str(row.get("confirmed", "")).strip().upper() == "YES":
                total_hours += get_confirmed_hours(row)
                confirmed_count += 1
 
    rate = get_employee_rate(telegram_id)
    salary = total_hours * rate
 
    return total_hours, confirmed_count, rate, salary
 
 
def get_employee_fines_total(telegram_id):
    records = fines_sheet.get_all_records()
    total = 0
    count = 0
 
    for row in records:
        if str(row.get("telegram_id", "")).strip() == str(telegram_id).strip():
            try:
                total += float(row.get("amount", 0))
                count += 1
            except Exception:
                pass
 
    return count, total
 
 
 
 
def build_user_dashboard(user_id, first_name=""):
    telegram_id = str(user_id)
    employee = find_employee_by_telegram_id(telegram_id) or first_name or "Сотрудник"
 
    hours, shifts_count, rate, salary = calculate_salary(telegram_id)
    fines_count, fines_total = get_employee_fines_total(telegram_id)
    salary_after_fines = salary - fines_total
 
    future_rows = find_schedule_rows_by_id(telegram_id, only_future=True)
    upcoming_count = len(future_rows)
 
    next_shift_block = "📌 Следующая смена\nСмен пока нет"
 
    if future_rows:
        try:
            sorted_rows = sorted(
                future_rows,
                key=lambda item: parse_date(item[1].get("date")).date()
            )
            next_row = sorted_rows[0][1]
            next_date = str(next_row.get("date", "")).strip()
            next_shift = str(next_row.get("shift", "")).strip()
            next_hours = parse_hours(next_shift)
            confirmed = str(next_row.get("confirmed", "")).strip().upper()
            status = "✅ Подтверждена" if confirmed == "YES" else "⏳ Ожидает подтверждения"
 
            next_shift_block = (
                f"📌 Следующая смена\n"
                f"📅 {next_date}\n"
                f"🕒 {next_shift}\n"
                f"⏱ {next_hours} ч.\n"
                f"{status}"
            )
        except Exception:
            next_shift_block = "📌 Следующая смена\nЕсть ближайшие смены"
 
    rate_text = f"{rate:g} ₽/час" if rate else "ставка не указана"
 
    return (
        f"🏠 Главное меню\n\n"
        f"👋 Привет, {employee}!\n\n"
        f"{next_shift_block}\n\n"
        f"📊 Мой баланс\n"
        f"📅 Ближайших смен: {upcoming_count}\n"
        f"✅ Подтверждено смен: {shifts_count}\n"
        f"⏱ Отработано часов: {hours:g}\n\n"
        f"💰 Финансы\n"
        f"💵 Ставка: {rate_text}\n"
        f"💸 Штрафы: {fines_total:g} ₽\n"
        f"✅ К выплате: {salary_after_fines:g} ₽\n\n"
        f"Выбери действие ниже 👇"
    )
 
 
 
# =========================
# MINI APP API
# =========================
 
RAILWAY_PUBLIC_URL = "https://work-bot-production-4b59.up.railway.app"
 
 
def get_next_shift_info(telegram_id):
    future_rows = find_schedule_rows_by_id(telegram_id, only_future=True)
 
    if not future_rows:
        return None
 
    try:
        sorted_rows = sorted(
            future_rows,
            key=lambda item: parse_date(item[1].get("date")).date()
        )
    except Exception:
        sorted_rows = future_rows
 
    row_number, row = sorted_rows[0]
    shift_date = str(row.get("date", "")).strip()
    shift = str(row.get("shift", "")).strip()
 
    try:
        hours = parse_hours(shift)
    except Exception:
        hours = 0
 
    confirmed = str(row.get("confirmed", "")).strip().upper()
    status = "Подтверждена" if confirmed == "YES" else "Ожидает подтверждения"
 
    return {
        "row_number": row_number,
        "date": shift_date,
        "shift": shift,
        "hours": hours,
        "status": status,
        "confirmed": confirmed == "YES"
    }
 
 
def get_upcoming_shifts_for_api(telegram_id, limit=10):
    rows = find_schedule_rows_by_id(telegram_id, only_future=True)
 
    try:
        rows = sorted(rows, key=lambda item: parse_date(item[1].get("date")).date())
    except Exception:
        pass
 
    result = []
 
    for row_number, row in rows[:limit]:
        shift = str(row.get("shift", "")).strip()
        try:
            hours = parse_hours(shift)
        except Exception:
            hours = 0
 
        confirmed = str(row.get("confirmed", "")).strip().upper()
 
        result.append({
            "row_number": row_number,
            "date": str(row.get("date", "")).strip(),
            "shift": shift,
            "hours": hours,
            "confirmed": confirmed == "YES",
            "status": "Подтверждена" if confirmed == "YES" else "Ожидает"
        })
 
    return result
 
 
def build_miniapp_user_data(telegram_id):
    employee = find_employee_by_telegram_id(telegram_id) or "Сотрудник"
 
    hours, shifts_count, rate, salary = calculate_salary(telegram_id)
    fines_count, fines_total = get_employee_fines_total(telegram_id)
    salary_after_fines = salary - fines_total
    upcoming_shifts = get_upcoming_shifts_for_api(telegram_id)
    next_shift = get_next_shift_info(telegram_id)
 
    return {
        "ok": True,
        "telegram_id": str(telegram_id),
        "employee": employee,
        "role": "admin" if is_admin(telegram_id) else "employee",
        "hours": hours,
        "confirmed_shifts": shifts_count,
        "upcoming_shifts_count": len(upcoming_shifts),
        "rate": rate,
        "salary": salary,
        "fines_count": fines_count,
        "fines_total": fines_total,
        "salary_after_fines": salary_after_fines,
        "next_shift": next_shift,
        "upcoming_shifts": upcoming_shifts
    }
 
 
async def api_user_handler(request):
    telegram_id = request.match_info.get("telegram_id")
 
    try:
        data = build_miniapp_user_data(telegram_id)
        return web.json_response(data, headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type"
        })
    except Exception as e:
        return web.json_response(
            {"ok": False, "error": str(e)},
            status=500,
            headers={"Access-Control-Allow-Origin": "*"}
        )
 
 
async def api_health_handler(request):
    return web.json_response({"ok": True, "service": "work-bot-api"}, headers={
        "Access-Control-Allow-Origin": "*"
    })
 
 
async def api_options_handler(request):
    return web.Response(headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"
    })
 
 
async def start_api_server():
    api_app = web.Application()
    api_app.router.add_get("/", api_health_handler)
    api_app.router.add_get("/api/user/{telegram_id}", api_user_handler)
    api_app.router.add_options("/api/user/{telegram_id}", api_options_handler)
 
    runner = web.AppRunner(api_app)
    await runner.setup()
 
    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
 
    print(f"Mini App API запущен на порту {port}")
 
 
def split_long_text(text, limit=3500):
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].strip()
    if text:
        parts.append(text)
    return parts
 
 
def get_employees():
    records = sheet.get_all_records()
    employees = {}
 
    for row in records:
        employee = str(row.get("employee", "")).strip()
        telegram_id = str(row.get("telegram_id", "")).strip()
 
        if employee and telegram_id and telegram_id.lower() not in ["none", "nan"]:
            employees[telegram_id] = employee
 
    return sorted(employees.items(), key=lambda item: item[1].lower())
 
 
def find_employee_by_telegram_id(telegram_id):
    for tid, employee in get_employees():
        if str(tid) == str(telegram_id):
            return employee
    return None
 
 
def find_schedule_rows_by_id(telegram_id, only_future=False):
    records = sheet.get_all_records()
    result = []
    today = datetime.now().date()
 
    for index, row in enumerate(records, start=2):
        if str(row.get("telegram_id", "")).strip() != str(telegram_id).strip():
            continue
 
        if only_future:
            try:
                shift_date = parse_date(row.get("date")).date()
                if shift_date < today:
                    continue
            except Exception:
                continue
 
        result.append((index, row))
 
    return result
 
 
def find_schedule_rows_by_id_and_date(telegram_id, date_text):
    rows = []
    for index, row in find_schedule_rows_by_id(telegram_id):
        if str(row.get("date", "")).strip() == str(date_text).strip():
            rows.append((index, row))
    return rows
 
 
async def send_shift_message(telegram_id, employee, shift_date, shift, row_number, title="📅 Напоминание о смене"):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить смену", callback_data=f"confirm:{row_number}")],
            [InlineKeyboardButton(text="⚠️ Не могу выйти", callback_data=f"problem:{row_number}")]
        ]
    )
 
    hours = parse_hours(shift)
 
    text = (
        f"{title}\n\n"
        f"👤 {employee}\n"
        f"📅 Дата: {shift_date}\n"
        f"🕒 Смена: {shift}\n"
        f"⏱ Часы: {hours}"
    )
 
    await bot.send_message(chat_id=int(telegram_id), text=text, reply_markup=keyboard)
 
 
def employees_keyboard():
    employees = get_employees()
    buttons = []
 
    for telegram_id, employee in employees:
        buttons.append([
            InlineKeyboardButton(
                text=f"👤 {employee}",
                callback_data=f"emp:{telegram_id}"
            )
        ])
 
    return InlineKeyboardMarkup(inline_keyboard=buttons)
 
 
def employee_card_keyboard(telegram_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Смена", callback_data=f"empact:add:{telegram_id}"),
                InlineKeyboardButton(text="📣 Напомнить", callback_data=f"empact:remind:{telegram_id}")
            ],
            [
                InlineKeyboardButton(text="✏️ Изменить", callback_data=f"empact:edit:{telegram_id}"),
                InlineKeyboardButton(text="❌ Удалить", callback_data=f"empact:delete:{telegram_id}")
            ],
            [
                InlineKeyboardButton(text="📅 График", callback_data=f"empact:shifts:{telegram_id}"),
                InlineKeyboardButton(text="📊 Часы", callback_data=f"empact:hours:{telegram_id}")
            ],
            [
                InlineKeyboardButton(text="💰 Зарплата", callback_data=f"empact:salary:{telegram_id}"),
                InlineKeyboardButton(text="💸 Штраф", callback_data=f"empact:fine:{telegram_id}")
            ],
            [InlineKeyboardButton(text="⬅️ К списку сотрудников", callback_data="employees:list")]
        ]
    )
 
 
def calendar_keyboard(action, telegram_id, year=None, month=None):
    now = datetime.now()
    year = year or now.year
    month = month or now.month
 
    month_name = [
        "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
    ][month]
 
    prev_month = month - 1
    prev_year = year
    if prev_month == 0:
        prev_month = 12
        prev_year -= 1
 
    next_month = month + 1
    next_year = year
    if next_month == 13:
        next_month = 1
        next_year += 1
 
    buttons = [
        [
            InlineKeyboardButton(text="◀️", callback_data=f"cal:{action}:{telegram_id}:{prev_year}:{prev_month}"),
            InlineKeyboardButton(text=f"{month_name} {year}", callback_data="noop"),
            InlineKeyboardButton(text="▶️", callback_data=f"cal:{action}:{telegram_id}:{next_year}:{next_month}")
        ],
        [
            InlineKeyboardButton(text="Пн", callback_data="noop"),
            InlineKeyboardButton(text="Вт", callback_data="noop"),
            InlineKeyboardButton(text="Ср", callback_data="noop"),
            InlineKeyboardButton(text="Чт", callback_data="noop"),
            InlineKeyboardButton(text="Пт", callback_data="noop"),
            InlineKeyboardButton(text="Сб", callback_data="noop"),
            InlineKeyboardButton(text="Вс", callback_data="noop")
        ]
    ]
 
    cal = calendar.Calendar(firstweekday=0)
    for week in cal.monthdayscalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
            else:
                date_text = f"{day:02d}.{month:02d}.{year}"
                row.append(InlineKeyboardButton(text=str(day), callback_data=f"date:{action}:{telegram_id}:{date_text}"))
        buttons.append(row)
 
    buttons.append([InlineKeyboardButton(text="⬅️ К сотруднику", callback_data=f"emp:{telegram_id}")])
 
    return InlineKeyboardMarkup(inline_keyboard=buttons)
 
 
def shift_rows_keyboard(action, telegram_id, rows):
    buttons = []
 
    for row_number, row in rows:
        date_text = row.get("date")
        shift = row.get("shift")
        buttons.append([
            InlineKeyboardButton(
                text=f"📅 {date_text} | {shift}",
                callback_data=f"shiftrow:{action}:{row_number}:{telegram_id}"
            )
        ])
 
    buttons.append([InlineKeyboardButton(text="⬅️ К сотруднику", callback_data=f"emp:{telegram_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
 
 
# =========================
# BASIC COMMANDS
# =========================
 
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    user_id = message.from_user.id
 
    text = build_user_dashboard(user_id, message.from_user.first_name)
    await message.answer(text, reply_markup=main_keyboard(user_id))
 
 
 
 
@dp.message(Command("menu"))
@dp.message(F.text == "🏠 Главное меню")
async def menu_handler(message: types.Message):
    user_id = message.from_user.id
    await message.answer(
        build_user_dashboard(user_id, message.from_user.first_name),
        reply_markup=main_keyboard(user_id)
    )
 
 
@dp.message(Command("test"))
async def test_command(message: types.Message):
    await send_shift_notifications()
    await message.answer("Тест уведомлений запущен")
 
 
@dp.message(F.text == "⬅️ Назад")
async def back_button(message: types.Message):
    pending_fines.pop(message.from_user.id, None)
    pending_shift_inputs.pop(message.from_user.id, None)
    await message.answer(build_user_dashboard(message.from_user.id, message.from_user.first_name), reply_markup=main_keyboard(message.from_user.id))
 
 
@dp.message(F.text.in_(["👑 Админ-панель", "👑 Панель управления"]))
async def admin_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет доступа к админ-панели.")
        return
 
    await message.answer("👑 Панель управления\n\n👥 Сотрудники\n📊 Отчёты\n💰 Финансы\n⚠️ Контроль смен", reply_markup=admin_keyboard())
 
 
@dp.message(F.text == "👥 Сотрудники")
async def employees_list(message: types.Message):
    if not is_admin(message.from_user.id):
        return
 
    employees = get_employees()
 
    if not employees:
        await message.answer("Пока нет сотрудников с Telegram ID в таблице schedule.")
        return
 
    await message.answer(
        f"👥 Сотрудники\n\nВсего подключено: {len(employees)}\nВыбери сотрудника:",
        reply_markup=employees_keyboard()
    )
 
 
@dp.callback_query(F.data.startswith("emp:"))
async def employee_card(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
 
    telegram_id = callback.data.split(":")[1]
    employee = find_employee_by_telegram_id(telegram_id) or "Неизвестный сотрудник"
 
    hours, shifts_count, rate, salary = calculate_salary(telegram_id)
    fines_count, fines_total = get_employee_fines_total(telegram_id)
 
    salary_after_fines = salary - fines_total
    future_rows = find_schedule_rows_by_id(telegram_id, only_future=True)
 
    await callback.message.answer(
        f"👤 Карточка сотрудника\n\n"
        f"👤 {employee}\n"
        f"📱 ID: {telegram_id}\n\n"
        f"📅 Ближайших смен: {len(future_rows)}\n"
        f"✅ Подтверждено смен: {shifts_count}\n"
        f"⏱ Часы: {hours:g}\n\n"
        f"💵 Ставка: {rate:g} ₽/час\n"
        f"💰 Начислено: {salary:g} ₽\n"
        f"💸 Штрафы: {fines_total:g} ₽\n"
        f"✅ К выплате: {salary_after_fines:g} ₽\n\n"
        f"Выбери действие 👇",
        reply_markup=employee_card_keyboard(telegram_id)
    )
    await callback.answer()
 
 
 
 
@dp.callback_query(F.data == "employees:list")
async def employees_list_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
 
    employees = get_employees()
    if not employees:
        await callback.message.answer("Пока нет сотрудников с Telegram ID в таблице schedule.")
    else:
        await callback.message.answer(
            f"👥 Сотрудники\n\nВсего подключено: {len(employees)}\nВыбери сотрудника:",
            reply_markup=employees_keyboard()
        )
 
    await callback.answer()
 
 
@dp.callback_query(F.data.startswith("empact:"))
async def employee_action(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
 
    _, action, telegram_id = callback.data.split(":")
    employee = find_employee_by_telegram_id(telegram_id) or "Неизвестный сотрудник"
 
    if action == "add":
        await callback.message.answer(
            f"➕ Добавить смену для {employee}\n\nВыбери дату:",
            reply_markup=calendar_keyboard("add", telegram_id)
        )
 
    elif action == "remind":
        rows = find_schedule_rows_by_id(telegram_id, only_future=True)
        if not rows:
            await callback.message.answer("У сотрудника нет будущих смен.")
        else:
            await callback.message.answer(
                f"📣 Выбери смену для напоминания: {employee}",
                reply_markup=shift_rows_keyboard("remind", telegram_id, rows[:20])
            )
 
    elif action == "edit":
        rows = find_schedule_rows_by_id(telegram_id, only_future=True)
        if not rows:
            await callback.message.answer("У сотрудника нет будущих смен для изменения.")
        else:
            await callback.message.answer(
                f"✏️ Выбери смену для изменения: {employee}",
                reply_markup=shift_rows_keyboard("edit", telegram_id, rows[:20])
            )
 
    elif action == "delete":
        rows = find_schedule_rows_by_id(telegram_id, only_future=True)
        if not rows:
            await callback.message.answer("У сотрудника нет будущих смен для удаления.")
        else:
            await callback.message.answer(
                f"❌ Выбери смену для удаления: {employee}",
                reply_markup=shift_rows_keyboard("delete", telegram_id, rows[:20])
            )
 
    elif action == "shifts":
        rows = find_schedule_rows_by_id(telegram_id, only_future=True)
        if not rows:
            await callback.message.answer("У сотрудника нет ближайших смен.")
        else:
            lines = []
            for _, row in rows[:15]:
                shift = row.get("shift")
                try:
                    hours = parse_hours(shift)
                except Exception:
                    hours = 0
                confirmed = "✅" if str(row.get("confirmed", "")).strip().upper() == "YES" else "⏳"
                lines.append(f"{confirmed} {row.get('date')} | {shift} | {hours} ч.")
            await callback.message.answer(f"📅 Смены сотрудника {employee}:\n\n" + "\n".join(lines))
 
    elif action == "fine":
        pending_fines[callback.from_user.id] = {
            "step": "amount",
            "telegram_id": telegram_id,
            "employee": employee
        }
        await callback.message.answer(
            f"💸 Штраф для {employee}\n\nОтправь сумму штрафа числом."
        )
 
    elif action == "hours":
        records = sheet.get_all_records()
        total = 0
        count = 0
        for row in records:
            if str(row.get("telegram_id", "")).strip() == telegram_id and str(row.get("confirmed", "")).strip().upper() == "YES":
                total += get_confirmed_hours(row)
                count += 1
        await callback.message.answer(f"📊 {employee}\n\nПодтверждено смен: {count}\nВсего часов: {total:g}")
 
    elif action == "salary":
        hours, shifts_count, rate, salary = calculate_salary(telegram_id)
        fines_count, fines_total = get_employee_fines_total(telegram_id)
        salary_after_fines = salary - fines_total
 
        await callback.message.answer(
            f"💰 Зарплата сотрудника\n\n"
            f"👤 {employee}\n"
            f"📊 Смен: {shifts_count}\n"
            f"⏱ Часы: {hours:g}\n"
            f"💵 Ставка: {rate:g} ₽/час\n"
            f"💰 Начислено: {salary:g} ₽\n"
            f"💸 Штрафы: {fines_total:g} ₽\n"
            f"✅ Итого к выплате: {salary_after_fines:g} ₽"
        )
 
    await callback.answer()
 
 
@dp.callback_query(F.data.startswith("cal:"))
async def calendar_change(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
 
    _, action, telegram_id, year, month = callback.data.split(":")
    await callback.message.edit_reply_markup(reply_markup=calendar_keyboard(action, telegram_id, int(year), int(month)))
    await callback.answer()
 
 
@dp.callback_query(F.data.startswith("date:"))
async def date_selected(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
 
    _, action, telegram_id, date_text = callback.data.split(":")
    employee = find_employee_by_telegram_id(telegram_id) or "Неизвестный сотрудник"
 
    if action == "add":
        pending_shift_inputs[callback.from_user.id] = {
            "action": "add",
            "telegram_id": telegram_id,
            "employee": employee,
            "date": date_text
        }
        await callback.message.answer(
            f"➕ Добавить смену\n\n"
            f"👤 {employee}\n"
            f"📅 {date_text}\n\n"
            f"Теперь отправь время смены. Например: 8-22"
        )
 
    await callback.answer()
 
 
@dp.callback_query(F.data.startswith("shiftrow:"))
async def shift_row_action(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
 
    _, action, row_number, telegram_id = callback.data.split(":")
    row_number = int(row_number)
    headers = get_headers()
    row_values = sheet.row_values(row_number)
 
    employee = get_row_value(row_values, headers, "employee")
    shift_date = get_row_value(row_values, headers, "date")
    shift = get_row_value(row_values, headers, "shift")
 
    if action == "remind":
        await send_shift_message(telegram_id, employee, shift_date, shift, row_number, title="📣 Напоминание от администратора")
        await callback.message.answer("📣 Напоминание отправлено сотруднику.")
 
    elif action == "edit":
        pending_shift_inputs[callback.from_user.id] = {
            "action": "edit",
            "row_number": row_number,
            "telegram_id": telegram_id,
            "employee": employee,
            "date": shift_date,
            "old_shift": shift
        }
        await callback.message.answer(
            f"✏️ Изменить смену\n\n"
            f"👤 {employee}\n"
            f"📅 {shift_date}\n"
            f"Сейчас: {shift}\n\n"
            f"Отправь новое время смены. Например: 10-22"
        )
 
    elif action == "delete":
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"delok:{row_number}:{telegram_id}")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data=f"emp:{telegram_id}")]
            ]
        )
        await callback.message.answer(
            f"❌ Удалить смену?\n\n"
            f"👤 {employee}\n"
            f"📅 {shift_date}\n"
            f"🕒 {shift}",
            reply_markup=keyboard
        )
 
    await callback.answer()
 
 
@dp.callback_query(F.data.startswith("delok:"))
async def delete_confirm(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
 
    _, row_number, telegram_id = callback.data.split(":")
    row_number = int(row_number)
 
    headers = get_headers()
    row_values = sheet.row_values(row_number)
    employee = get_row_value(row_values, headers, "employee")
    shift_date = get_row_value(row_values, headers, "date")
    shift = get_row_value(row_values, headers, "shift")
 
    sheet.delete_rows(row_number)
 
    await callback.message.answer(
        f"❌ Смена удалена\n\n"
        f"👤 {employee}\n"
        f"📅 {shift_date}\n"
        f"🕒 {shift}"
    )
 
    try:
        await bot.send_message(
            int(telegram_id),
            f"❌ Твоя смена удалена\n\n📅 {shift_date}\n🕒 {shift}"
        )
    except Exception as e:
        await callback.message.answer(f"⚠️ Не удалось уведомить сотрудника: {e}")
 
    await callback.answer("Удалено")
 
 
@dp.callback_query(F.data.startswith("notify:"))
async def notify_after_add(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
 
    _, answer, row_number, telegram_id = callback.data.split(":")
    row_number = int(row_number)
 
    headers = get_headers()
    row_values = sheet.row_values(row_number)
    employee = get_row_value(row_values, headers, "employee")
    shift_date = get_row_value(row_values, headers, "date")
    shift = get_row_value(row_values, headers, "shift")
 
    if answer == "yes":
        try:
            await send_shift_message(telegram_id, employee, shift_date, shift, row_number, title="📅 Тебе добавлена новая смена")
            await callback.message.answer("📣 Уведомление отправлено сотруднику.")
        except Exception as e:
            await callback.message.answer(f"⚠️ Не удалось отправить уведомление: {e}")
    else:
        await callback.message.answer("Ок, уведомление не отправлялось.")
 
    await callback.answer()
 
 
@dp.callback_query(F.data == "noop")
async def noop(callback: types.CallbackQuery):
    await callback.answer()
 
 
# =========================
# REPORTS AND EMPLOYEE BUTTONS
# =========================
 
@dp.message(F.text.in_(["📅 Мои ближайшие смены", "📅 Мои смены"]))
async def my_upcoming_shifts(message: types.Message):
    telegram_id = str(message.from_user.id)
    records = sheet.get_all_records()
    today = datetime.now().date()
    shifts = []
 
    for row in records:
        if str(row.get("telegram_id", "")).strip() != telegram_id:
            continue
        try:
            shift_date = parse_date(row.get("date")).date()
        except Exception:
            continue
        if shift_date >= today:
            shift = str(row.get("shift")).strip()
            hours = parse_hours(shift)
            confirmed = str(row.get("confirmed", "")).strip().upper()
            status = "✅ подтверждена" if confirmed == "YES" else "⏳ не подтверждена"
            shifts.append((shift_date, f"📅 {row.get('date')} | 🕒 {shift} | ⏱ {hours} ч. | {status}"))
 
    if not shifts:
        await message.answer("📅 У тебя нет ближайших смен.")
        return
 
    shifts.sort(key=lambda item: item[0])
    await message.answer("📅 Мои смены\n\n" + "\n".join([item[1] for item in shifts[:10]]))
 
 
@dp.message(F.text.in_(["📊 Сколько у меня часов", "📊 Мои часы"]))
async def hours_button(message: types.Message):
    telegram_id = str(message.from_user.id)
    records = sheet.get_all_records()
    total_hours = 0
    confirmed_count = 0
 
    for row in records:
        if str(row.get("telegram_id", "")).strip() == telegram_id:
            if str(row.get("confirmed", "")).strip().upper() == "YES":
                total_hours += get_confirmed_hours(row)
                confirmed_count += 1
 
    await message.answer(
        f"📊 Твои подтверждённые часы\n\n"
        f"Подтверждено смен: {confirmed_count}\n"
        f"Всего часов: {total_hours:g}"
    )
 
 
 
@dp.message(F.text == "💰 Моя зарплата")
async def my_salary(message: types.Message):
    telegram_id = str(message.from_user.id)
    hours, shifts_count, rate, salary = calculate_salary(telegram_id)
    fines_count, fines_total = get_employee_fines_total(telegram_id)
    salary_after_fines = salary - fines_total
 
    if rate == 0:
        await message.answer(
            "💰 Моя зарплата\n\n"
            "Для тебя ещё не указана ставка в таблице rates.\n"
            "Обратись к администратору."
        )
        return
 
    await message.answer(
        f"💰 Моя зарплата\n\n"
        f"📊 Подтверждено смен: {shifts_count}\n"
        f"⏱ Часы: {hours:g}\n"
        f"💵 Ставка: {rate:g} ₽/час\n"
        f"💰 Начислено: {salary:g} ₽\n"
        f"💸 Штрафы: {fines_total:g} ₽\n"
        f"✅ Итого к выплате: {salary_after_fines:g} ₽"
    )
 
 
@dp.message(F.text == "💰 Зарплаты")
async def admin_all_salaries(message: types.Message):
    if not is_admin(message.from_user.id):
        return
 
    employees = get_employees()
 
    if not employees:
        await message.answer("Нет сотрудников с Telegram ID.")
        return
 
    lines = []
    total_salary = 0
    total_after_fines = 0
 
    for telegram_id, employee in employees:
        hours, shifts_count, rate, salary = calculate_salary(telegram_id)
        _, fines_total = get_employee_fines_total(telegram_id)
        after_fines = salary - fines_total
        total_salary += salary
        total_after_fines += after_fines
 
        lines.append(
            f"👤 {employee}\n"
            f"⏱ {hours:g} ч. × {rate:g} ₽ = {salary:g} ₽\n"
            f"💸 Штрафы: {fines_total:g} ₽\n"
            f"✅ К выплате: {after_fines:g} ₽"
        )
 
    text = (
        "💰 Зарплаты сотрудников\n\n"
        + "\n\n".join(lines)
        + f"\n\nИтого начислено: {total_salary:g} ₽"
        + f"\nИтого к выплате: {total_after_fines:g} ₽"
    )
 
    for part in split_long_text(text):
        await message.answer(part)
 
 
@dp.message(F.text == "📋 Подтверждённые смены")
async def admin_confirmed_shifts(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    records = sheet.get_all_records()
    confirmed = []
    for row in records:
        if str(row.get("confirmed", "")).strip().upper() == "YES":
            hours = get_confirmed_hours(row)
            confirmed.append(f"✅ {row.get('employee')} | {row.get('date')} | {row.get('shift')} | {hours:g} ч.")
    if not confirmed:
        await message.answer("Пока нет подтверждённых смен.")
        return
    await message.answer("📋 Подтверждённые смены:\n\n" + "\n".join(confirmed[-30:]))
 
 
@dp.message(F.text == "⚠️ Проблемные смены")
async def admin_problem_shifts(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    records = problems_sheet.get_all_records()
    if not records:
        await message.answer("Проблемных смен пока нет.")
        return
    lines = []
    for row in records[-30:]:
        lines.append(f"⚠️ {row.get('employee')} | {row.get('shift_date')} | {row.get('shift')}\nПричина: {row.get('problem')}")
    for part in split_long_text("⚠️ Проблемные смены:\n\n" + "\n\n".join(lines)):
        await message.answer(part)
 
 
@dp.message(F.text == "📊 Часы сотрудников")
async def admin_employee_hours(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    records = sheet.get_all_records()
    totals = {}
    for row in records:
        if str(row.get("confirmed", "")).strip().upper() == "YES":
            employee = row.get("employee")
            totals[employee] = totals.get(employee, 0) + get_confirmed_hours(row)
    if not totals:
        await message.answer("Пока нет подтверждённых часов.")
        return
    lines = [f"👤 {employee}: {hours:g} ч." for employee, hours in totals.items()]
    await message.answer("📊 Часы сотрудников:\n\n" + "\n".join(lines))
 
 
@dp.message(F.text == "📈 Отчёт за месяц")
async def admin_month_report(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    current_month = datetime.now().strftime("%m.%Y")
    records = sheet.get_all_records()
    totals = {}
    shifts_count = {}
    for row in records:
        if str(row.get("confirmed", "")).strip().upper() != "YES":
            continue
        if current_month not in str(row.get("date", "")).strip():
            continue
        employee = row.get("employee")
        totals[employee] = totals.get(employee, 0) + get_confirmed_hours(row)
        shifts_count[employee] = shifts_count.get(employee, 0) + 1
    if not totals:
        await message.answer(f"📈 За месяц {current_month} пока нет подтверждённых смен.")
        return
    total_all = sum(totals.values())
    lines = [f"👤 {employee}: {totals[employee]:g} ч. | смен: {shifts_count[employee]}" for employee in totals]
    await message.answer(f"📈 Отчёт за месяц {current_month}\n\n" + "\n".join(lines) + f"\n\nИтого часов: {total_all:g}")
 
 
# =========================
# FINES
# =========================
 
@dp.message(F.text == "💸 Мои штрафы")
async def my_fines(message: types.Message):
    telegram_id = str(message.from_user.id)
    records = fines_sheet.get_all_records()
    my_records = [row for row in records if str(row.get("telegram_id", "")).strip() == telegram_id]
    if not my_records:
        await message.answer("💸 У тебя нет штрафов.")
        return
    total = 0
    lines = []
    for row in my_records[-20:]:
        amount = row.get("amount", 0)
        try:
            total += float(amount)
        except Exception:
            pass
        lines.append(f"💸 {row.get('created_at')} | {amount} ₽\nПричина: {row.get('reason')}")
    for part in split_long_text("💸 Твои штрафы\n\n" + "\n\n".join(lines) + f"\n\nИтого штрафов: {total:g} ₽"):
        await message.answer(part)
 
 
@dp.message(F.text == "📄 Все штрафы")
async def all_fines(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    records = fines_sheet.get_all_records()
    if not records:
        await message.answer("💸 Штрафов пока нет.")
        return
    total = 0
    lines = []
    for row in records[-40:]:
        amount = row.get("amount", 0)
        try:
            total += float(amount)
        except Exception:
            pass
        lines.append(f"💸 {row.get('employee')} | {row.get('created_at')} | {amount} ₽\nID: {row.get('telegram_id')}\nПричина: {row.get('reason')}")
    for part in split_long_text("📄 Все штрафы:\n\n" + "\n\n".join(lines) + f"\n\nИтого по показанным: {total:g} ₽"):
        await message.answer(part)
 
 
# =========================
# NOTIFICATIONS AND CALLBACKS
# =========================
 
async def send_shift_notifications():
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
    records = sheet.get_all_records()
    print(f"Проверяем смены на {tomorrow}")
    for index, row in enumerate(records, start=2):
        try:
            employee = row["employee"]
            telegram_id = str(row["telegram_id"]).strip()
            shift_date = str(row["date"]).strip()
            shift = str(row["shift"]).strip()
            if shift_date == tomorrow:
                await send_shift_message(telegram_id, employee, shift_date, shift, index)
                print(f"Отправлено: {employee}")
        except Exception as e:
            print(f"Ошибка: {e}")
 
 
@dp.callback_query(F.data.startswith("confirm:"))
async def confirm_shift(callback: types.CallbackQuery):
    row_number = int(callback.data.split(":")[1])
    headers = get_headers()
    row = sheet.row_values(row_number)
    confirmed_current = get_row_value(row, headers, "confirmed").strip().upper()
    if confirmed_current == "YES":
        await callback.answer("Эта смена уже подтверждена", show_alert=True)
        return
    employee = get_row_value(row, headers, "employee")
    shift_date = get_row_value(row, headers, "date")
    shift = get_row_value(row, headers, "shift")
    hours = parse_hours(shift)
    sheet.update_cell(row_number, headers["confirmed"], "YES")
    hours_col = headers.get("confirmed_hours") or headers.get("hours")
    sheet.update_cell(row_number, hours_col, hours)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"✅ Смена подтверждена\n\nДата: {shift_date}\nСмена: {shift}\nЧасы: {hours}")
    await bot.send_message(ADMIN_ID, f"✅ Смена подтверждена\n\n👤 Сотрудник: {employee}\n📅 Дата: {shift_date}\n🕒 Смена: {shift}\n⏱ Часы: {hours}")
    await callback.answer("Смена подтверждена")
 
 
@dp.callback_query(F.data.startswith("problem:"))
async def problem_shift(callback: types.CallbackQuery):
    row_number = int(callback.data.split(":")[1])
    pending_problems[callback.from_user.id] = row_number
    await callback.message.answer("⚠️ Опиши проблему со сменой одним сообщением.")
    await callback.answer()
 
 
# =========================
# TEXT ROUTER FOR INPUTS
# =========================
 
@dp.message()
async def text_router(message: types.Message):
    user_id = message.from_user.id
    if user_id in pending_shift_inputs:
        await handle_shift_input(message)
        return
    if user_id in pending_fines:
        await handle_fine_creation(message)
        return
    if user_id in pending_problems:
        await handle_problem_text(message)
        return
 
 
async def handle_shift_input(message: types.Message):
    admin_id = message.from_user.id
    data = pending_shift_inputs.get(admin_id)
    if not data:
        return
    text = message.text.strip()
    action = data.get("action")
 
    try:
        hours = parse_hours(text)
    except Exception:
        await message.answer("Смена должна быть в формате 8-22 или 08:00-22:00.")
        return
 
    if action == "add":
        employee = data["employee"]
        telegram_id = data["telegram_id"]
        shift_date = data["date"]
        sheet.append_row([employee, telegram_id, shift_date, text, "", ""])
        row_number = len(sheet.get_all_values())
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да, отправить", callback_data=f"notify:yes:{row_number}:{telegram_id}")],
                [InlineKeyboardButton(text="❌ Нет", callback_data=f"notify:no:{row_number}:{telegram_id}")]
            ]
        )
        await message.answer(
            f"✅ Смена добавлена\n\n👤 {employee}\n📅 {shift_date}\n🕒 {text}\n⏱ {hours} ч.\n\n📣 Отправить уведомление сотруднику?",
            reply_markup=keyboard
        )
        pending_shift_inputs.pop(admin_id, None)
        return
 
    if action == "edit":
        row_number = data["row_number"]
        headers = get_headers()
        sheet.update_cell(row_number, headers["shift"], text)
        sheet.update_cell(row_number, headers["confirmed"], "")
        hours_col = headers.get("confirmed_hours") or headers.get("hours")
        sheet.update_cell(row_number, hours_col, "")
        await message.answer(
            f"✏️ Смена изменена\n\n👤 {data['employee']}\n📅 {data['date']}\nБыло: {data['old_shift']}\nСтало: {text}\n⏱ {hours} ч.\n\nПодтверждение сброшено."
        )
        try:
            await send_shift_message(data["telegram_id"], data["employee"], data["date"], text, row_number, title="✏️ Твоя смена изменена")
        except Exception as e:
            await message.answer(f"⚠️ Смена изменена, но уведомление не отправлено: {e}")
        pending_shift_inputs.pop(admin_id, None)
        return
 
 
async def handle_fine_creation(message: types.Message):
    admin_id = message.from_user.id
    data = pending_fines.get(admin_id)
    if not data:
        return
    text = message.text.strip()
 
    if data["step"] == "amount":
        try:
            amount = float(text.replace(",", "."))
        except Exception:
            await message.answer("Сумма должна быть числом. Например: 500")
            return
        data["amount"] = amount
        data["step"] = "reason"
        pending_fines[admin_id] = data
        await message.answer("Теперь напиши причину штрафа.")
        return
 
    if data["step"] == "reason":
        reason = text
        created_at = datetime.now().strftime("%d.%m.%Y %H:%M")
        fines_sheet.append_row([created_at, data["employee"], data["telegram_id"], data["amount"], reason, admin_id])
        await message.answer(
            f"✅ Штраф выписан\n\n👤 Сотрудник: {data['employee']}\nID: {data['telegram_id']}\n💸 Сумма: {data['amount']:g} ₽\nПричина: {reason}",
            reply_markup=admin_keyboard()
        )
        try:
            await bot.send_message(int(data["telegram_id"]), f"💸 Тебе выписан штраф\n\nСумма: {data['amount']:g} ₽\nПричина: {reason}\nДата: {created_at}")
        except Exception as e:
            await message.answer(f"⚠️ Не удалось отправить уведомление сотруднику: {e}")
        pending_fines.pop(admin_id, None)
        return
 
 
async def handle_problem_text(message: types.Message):
    user_id = message.from_user.id
    row_number = pending_problems.pop(user_id)
    headers = get_headers()
    row = sheet.row_values(row_number)
    employee = get_row_value(row, headers, "employee")
    telegram_id = get_row_value(row, headers, "telegram_id")
    shift_date = get_row_value(row, headers, "date")
    shift = get_row_value(row, headers, "shift")
    problem = message.text
    created_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    problems_sheet.append_row([created_at, employee, telegram_id, shift_date, shift, problem])
    await bot.send_message(ADMIN_ID, f"⚠️ Проблема со сменой\n\n👤 Сотрудник: {employee}\n📅 Дата: {shift_date}\n🕒 Смена: {shift}\n\nПричина:\n{problem}")
    await message.answer("⚠️ Сообщение отправлено администратору.")
 
 
scheduler = AsyncIOScheduler()
scheduler.add_job(send_shift_notifications, trigger="cron", hour=20, minute=0)
 
 
async def main():
    await start_api_server()
    scheduler.start()
    print("Бот запущен V17 mini app real data")
    await dp.start_polling(bot)
 
 
if __name__ == "__main__":
    asyncio.run(main())
