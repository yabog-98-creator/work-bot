import asyncio
import os
import json
from datetime import datetime, timedelta
 
import gspread
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
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
 
pending_problems = {}
pending_fines = {}
pending_shift_actions = {}
 
 
def is_admin(user_id):
    return int(user_id) == ADMIN_ID
 
 
def main_keyboard(user_id=None):
    keyboard = [
        [KeyboardButton(text="📅 Мои ближайшие смены")],
        [KeyboardButton(text="📊 Сколько у меня часов")],
        [KeyboardButton(text="💸 Мои штрафы")]
    ]
 
    if user_id and is_admin(user_id):
        keyboard.append([KeyboardButton(text="👑 Админ-панель")])
 
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
 
 
def admin_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить смену")],
            [KeyboardButton(text="📣 Отправить напоминание")],
            [KeyboardButton(text="✏️ Изменить смену")],
            [KeyboardButton(text="❌ Удалить смену")],
            [KeyboardButton(text="📋 Подтверждённые смены")],
            [KeyboardButton(text="⚠️ Проблемные смены")],
            [KeyboardButton(text="📊 Часы сотрудников")],
            [KeyboardButton(text="📈 Отчёт за месяц")],
            [KeyboardButton(text="💸 Выписать штраф")],
            [KeyboardButton(text="📄 Все штрафы")],
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
 
 
def find_employee_by_telegram_id(telegram_id):
    records = sheet.get_all_records()
 
    for row in records:
        if str(row.get("telegram_id")).strip() == str(telegram_id).strip():
            return row.get("employee")
 
    return None
 
 
def find_schedule_rows_by_id_and_date(telegram_id, date_text):
    records = sheet.get_all_records()
    result = []
 
    for index, row in enumerate(records, start=2):
        if str(row.get("telegram_id")).strip() == str(telegram_id).strip() and str(row.get("date")).strip() == str(date_text).strip():
            result.append((index, row))
 
    return result
 
 
async def send_shift_message(telegram_id, employee, shift_date, shift, row_number, title="📅 Напоминание о смене"):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить смену",
                    callback_data=f"confirm:{row_number}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚠️ Не могу выйти",
                    callback_data=f"problem:{row_number}"
                )
            ]
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
 
    await bot.send_message(
        chat_id=int(telegram_id),
        text=text,
        reply_markup=keyboard
    )
 
 
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    user_id = message.from_user.id
 
    text = (
        f"Привет, {message.from_user.first_name}!\n\n"
        f"Твой Telegram ID:\n"
        f"{user_id}\n\n"
        f"Передай этот ID администратору."
    )
 
    await message.answer(text, reply_markup=main_keyboard(user_id))
 
 
@dp.message(Command("test"))
async def test_command(message: types.Message):
    await send_shift_notifications()
    await message.answer("Тест уведомлений запущен")
 
 
@dp.message(F.text == "⬅️ Назад")
async def back_button(message: types.Message):
    pending_fines.pop(message.from_user.id, None)
    pending_shift_actions.pop(message.from_user.id, None)
 
    await message.answer(
        "Главное меню",
        reply_markup=main_keyboard(message.from_user.id)
    )
 
 
@dp.message(F.text == "👑 Админ-панель")
async def admin_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет доступа к админ-панели.")
        return
 
    await message.answer("👑 Админ-панель", reply_markup=admin_keyboard())
 
 
@dp.message(F.text == "➕ Добавить смену")
async def start_add_shift(message: types.Message):
    if not is_admin(message.from_user.id):
        return
 
    pending_shift_actions[message.from_user.id] = {
        "action": "add",
        "step": "telegram_id"
    }
 
    await message.answer("➕ Добавить смену\n\nОтправь Telegram ID сотрудника.")
 
 
@dp.message(F.text == "📣 Отправить напоминание")
async def start_manual_reminder(message: types.Message):
    if not is_admin(message.from_user.id):
        return
 
    pending_shift_actions[message.from_user.id] = {
        "action": "remind",
        "step": "telegram_id"
    }
 
    await message.answer(
        "📣 Отправить напоминание\n\n"
        "Отправь Telegram ID сотрудника."
    )
 
 
@dp.message(F.text == "✏️ Изменить смену")
async def start_edit_shift(message: types.Message):
    if not is_admin(message.from_user.id):
        return
 
    pending_shift_actions[message.from_user.id] = {
        "action": "edit",
        "step": "telegram_id"
    }
 
    await message.answer(
        "✏️ Изменить смену\n\n"
        "Отправь Telegram ID сотрудника."
    )
 
 
@dp.message(F.text == "❌ Удалить смену")
async def start_delete_shift(message: types.Message):
    if not is_admin(message.from_user.id):
        return
 
    pending_shift_actions[message.from_user.id] = {
        "action": "delete",
        "step": "telegram_id"
    }
 
    await message.answer(
        "❌ Удалить смену\n\n"
        "Отправь Telegram ID сотрудника."
    )
 
 
@dp.message(F.text == "📅 Мои ближайшие смены")
async def my_upcoming_shifts(message: types.Message):
    telegram_id = str(message.from_user.id)
    records = sheet.get_all_records()
    today = datetime.now().date()
 
    shifts = []
 
    for row in records:
        if str(row.get("telegram_id")).strip() != telegram_id:
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
 
            shifts.append((
                shift_date,
                f"📅 {row.get('date')} | 🕒 {shift} | ⏱ {hours} ч. | {status}"
            ))
 
    if not shifts:
        await message.answer("📅 У тебя нет ближайших смен.")
        return
 
    shifts.sort(key=lambda item: item[0])
    lines = [item[1] for item in shifts[:10]]
 
    await message.answer("📅 Твои ближайшие смены:\n\n" + "\n".join(lines))
 
 
@dp.message(F.text == "📋 Подтверждённые смены")
async def admin_confirmed_shifts(message: types.Message):
    if not is_admin(message.from_user.id):
        return
 
    records = sheet.get_all_records()
    confirmed = []
 
    for row in records:
        if str(row.get("confirmed", "")).strip().upper() == "YES":
            hours = get_confirmed_hours(row)
            confirmed.append(
                f"✅ {row.get('employee')} | {row.get('date')} | "
                f"{row.get('shift')} | {hours:g} ч."
            )
 
    if not confirmed:
        await message.answer("Пока нет подтверждённых смен.")
        return
 
    text = "📋 Подтверждённые смены:\n\n" + "\n".join(confirmed[-30:])
    await message.answer(text)
 
 
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
        lines.append(
            f"⚠️ {row.get('employee')} | {row.get('shift_date')} | {row.get('shift')}\n"
            f"Причина: {row.get('problem')}"
        )
 
    text = "⚠️ Проблемные смены:\n\n" + "\n\n".join(lines)
 
    for part in split_long_text(text):
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
            hours = get_confirmed_hours(row)
            totals[employee] = totals.get(employee, 0) + hours
 
    if not totals:
        await message.answer("Пока нет подтверждённых часов.")
        return
 
    lines = [
        f"👤 {employee}: {hours:g} ч."
        for employee, hours in totals.items()
    ]
 
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
 
        date_value = str(row.get("date", "")).strip()
 
        if current_month not in date_value:
            continue
 
        employee = row.get("employee")
        hours = get_confirmed_hours(row)
 
        totals[employee] = totals.get(employee, 0) + hours
        shifts_count[employee] = shifts_count.get(employee, 0) + 1
 
    if not totals:
        await message.answer(f"📈 За месяц {current_month} пока нет подтверждённых смен.")
        return
 
    total_all = sum(totals.values())
 
    lines = [
        f"👤 {employee}: {totals[employee]:g} ч. | смен: {shifts_count[employee]}"
        for employee in totals
    ]
 
    text = (
        f"📈 Отчёт за месяц {current_month}\n\n"
        + "\n".join(lines)
        + f"\n\nИтого часов: {total_all:g}"
    )
 
    await message.answer(text)
 
 
@dp.message(F.text == "💸 Мои штрафы")
async def my_fines(message: types.Message):
    telegram_id = str(message.from_user.id)
    records = fines_sheet.get_all_records()
 
    my_records = [
        row for row in records
        if str(row.get("telegram_id")).strip() == telegram_id
    ]
 
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
 
        lines.append(
            f"💸 {row.get('created_at')} | {amount} ₽\n"
            f"Причина: {row.get('reason')}"
        )
 
    text = (
        "💸 Твои штрафы\n\n"
        + "\n\n".join(lines)
        + f"\n\nИтого штрафов: {total:g} ₽"
    )
 
    for part in split_long_text(text):
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
 
        lines.append(
            f"💸 {row.get('employee')} | {row.get('created_at')} | {amount} ₽\n"
            f"ID: {row.get('telegram_id')}\n"
            f"Причина: {row.get('reason')}"
        )
 
    text = (
        "📄 Все штрафы:\n\n"
        + "\n\n".join(lines)
        + f"\n\nИтого по показанным: {total:g} ₽"
    )
 
    for part in split_long_text(text):
        await message.answer(part)
 
 
@dp.message(F.text == "💸 Выписать штраф")
async def start_fine_create(message: types.Message):
    if not is_admin(message.from_user.id):
        return
 
    pending_fines[message.from_user.id] = {
        "step": "telegram_id"
    }
 
    await message.answer(
        "💸 Выписать штраф\n\n"
        "Отправь Telegram ID сотрудника."
    )
 
 
@dp.message(F.text == "📊 Сколько у меня часов")
async def hours_button(message: types.Message):
    telegram_id = str(message.from_user.id)
    records = sheet.get_all_records()
 
    total_hours = 0
    confirmed_count = 0
 
    for row in records:
        if str(row.get("telegram_id")).strip() == telegram_id:
            confirmed = str(row.get("confirmed", "")).strip().upper()
 
            if confirmed == "YES":
                hours = get_confirmed_hours(row)
                total_hours += hours
                confirmed_count += 1
 
    await message.answer(
        f"📊 Твои подтверждённые часы\n\n"
        f"Подтверждено смен: {confirmed_count}\n"
        f"Всего часов: {total_hours:g}"
    )
 
 
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
                await send_shift_message(
                    telegram_id=telegram_id,
                    employee=employee,
                    shift_date=shift_date,
                    shift=shift,
                    row_number=index,
                    title="📅 Напоминание о смене"
                )
 
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
 
    confirmed_col = headers["confirmed"]
    hours_col = headers.get("confirmed_hours") or headers.get("hours")
 
    sheet.update_cell(row_number, confirmed_col, "YES")
    sheet.update_cell(row_number, hours_col, hours)
 
    await callback.message.edit_reply_markup(reply_markup=None)
 
    await callback.message.answer(
        f"✅ Смена подтверждена\n\n"
        f"Дата: {shift_date}\n"
        f"Смена: {shift}\n"
        f"Часы: {hours}"
    )
 
    await bot.send_message(
        ADMIN_ID,
        f"✅ Смена подтверждена\n\n"
        f"👤 Сотрудник: {employee}\n"
        f"📅 Дата: {shift_date}\n"
        f"🕒 Смена: {shift}\n"
        f"⏱ Часы: {hours}"
    )
 
    await callback.answer("Смена подтверждена")
 
 
@dp.callback_query(F.data.startswith("problem:"))
async def problem_shift(callback: types.CallbackQuery):
    row_number = int(callback.data.split(":")[1])
    pending_problems[callback.from_user.id] = row_number
 
    await callback.message.answer("⚠️ Опиши проблему со сменой одним сообщением.")
    await callback.answer()
 
 
@dp.message()
async def text_router(message: types.Message):
    user_id = message.from_user.id
 
    if user_id in pending_shift_actions:
        await handle_shift_action(message)
        return
 
    if user_id in pending_fines:
        await handle_fine_creation(message)
        return
 
    if user_id in pending_problems:
        await handle_problem_text(message)
        return
 
 
async def handle_shift_action(message: types.Message):
    admin_id = message.from_user.id
    data = pending_shift_actions.get(admin_id)
 
    if not data:
        return
 
    text = message.text.strip()
    action = data["action"]
 
    if data["step"] == "telegram_id":
        data["telegram_id"] = text
        employee = find_employee_by_telegram_id(text)
        data["employee"] = employee or "Неизвестный сотрудник"
 
        data["step"] = "date"
        pending_shift_actions[admin_id] = data
 
        await message.answer(
            f"Сотрудник: {data['employee']}\n\n"
            "Теперь отправь дату смены в формате ДД.ММ.ГГГГ."
        )
        return
 
    if data["step"] == "date":
        try:
            parse_date(text)
        except Exception:
            await message.answer("Дата должна быть в формате ДД.ММ.ГГГГ. Например: 05.06.2026")
            return
 
        data["date"] = text
 
        if action == "remind":
            rows = find_schedule_rows_by_id_and_date(data["telegram_id"], data["date"])
 
            if not rows:
                await message.answer("Смена не найдена.", reply_markup=admin_keyboard())
                pending_shift_actions.pop(admin_id, None)
                return
 
            sent = 0
 
            for row_number, row in rows:
                await send_shift_message(
                    telegram_id=data["telegram_id"],
                    employee=row.get("employee"),
                    shift_date=row.get("date"),
                    shift=row.get("shift"),
                    row_number=row_number,
                    title="📣 Напоминание от администратора"
                )
                sent += 1
 
            await message.answer(
                f"📣 Напоминание отправлено. Смен найдено: {sent}",
                reply_markup=admin_keyboard()
            )
            pending_shift_actions.pop(admin_id, None)
            return
 
        if action == "delete":
            rows = find_schedule_rows_by_id_and_date(data["telegram_id"], data["date"])
 
            if not rows:
                await message.answer("Смена не найдена.", reply_markup=admin_keyboard())
                pending_shift_actions.pop(admin_id, None)
                return
 
            row_number, row = rows[0]
            employee = row.get("employee")
            shift = row.get("shift")
            shift_date = row.get("date")
 
            sheet.delete_rows(row_number)
 
            await message.answer(
                f"❌ Смена удалена\n\n"
                f"👤 {employee}\n"
                f"📅 {shift_date}\n"
                f"🕒 {shift}",
                reply_markup=admin_keyboard()
            )
 
            try:
                await bot.send_message(
                    int(data["telegram_id"]),
                    f"❌ Твоя смена удалена\n\n"
                    f"📅 Дата: {shift_date}\n"
                    f"🕒 Смена: {shift}"
                )
            except Exception as e:
                await message.answer(f"⚠️ Не удалось уведомить сотрудника: {e}")
 
            pending_shift_actions.pop(admin_id, None)
            return
 
        data["step"] = "shift"
        pending_shift_actions[admin_id] = data
 
        if action == "add":
            await message.answer("Теперь отправь время смены. Например: 8-22")
        elif action == "edit":
            await message.answer("Теперь отправь новое время смены. Например: 10-22")
 
        return
 
    if data["step"] == "shift":
        try:
            hours = parse_hours(text)
        except Exception:
            await message.answer("Смена должна быть в формате 8-22 или 08:00-22:00.")
            return
 
        if action == "add":
            employee = data["employee"]
            telegram_id = data["telegram_id"]
            shift_date = data["date"]
            shift = text
 
            sheet.append_row([
                employee,
                telegram_id,
                shift_date,
                shift,
                "",
                ""
            ])
 
            row_number = len(sheet.get_all_values())
 
            await message.answer(
                f"✅ Смена добавлена\n\n"
                f"👤 {employee}\n"
                f"📅 {shift_date}\n"
                f"🕒 {shift}\n"
                f"⏱ {hours} ч.",
                reply_markup=admin_keyboard()
            )
 
            try:
                await send_shift_message(
                    telegram_id=telegram_id,
                    employee=employee,
                    shift_date=shift_date,
                    shift=shift,
                    row_number=row_number,
                    title="📅 Тебе добавлена новая смена"
                )
            except Exception as e:
                await message.answer(f"⚠️ Смена добавлена, но уведомление не отправлено: {e}")
 
            pending_shift_actions.pop(admin_id, None)
            return
 
        if action == "edit":
            rows = find_schedule_rows_by_id_and_date(data["telegram_id"], data["date"])
 
            if not rows:
                await message.answer("Смена не найдена.", reply_markup=admin_keyboard())
                pending_shift_actions.pop(admin_id, None)
                return
 
            row_number, row = rows[0]
            headers = get_headers()
 
            old_shift = row.get("shift")
            employee = row.get("employee")
            shift_date = row.get("date")
 
            shift_col = headers["shift"]
            confirmed_col = headers["confirmed"]
            hours_col = headers.get("confirmed_hours") or headers.get("hours")
 
            sheet.update_cell(row_number, shift_col, text)
            sheet.update_cell(row_number, confirmed_col, "")
            sheet.update_cell(row_number, hours_col, "")
 
            await message.answer(
                f"✏️ Смена изменена\n\n"
                f"👤 {employee}\n"
                f"📅 {shift_date}\n"
                f"Было: {old_shift}\n"
                f"Стало: {text}\n"
                f"⏱ {hours} ч.\n\n"
                f"Подтверждение сброшено.",
                reply_markup=admin_keyboard()
            )
 
            try:
                await send_shift_message(
                    telegram_id=data["telegram_id"],
                    employee=employee,
                    shift_date=shift_date,
                    shift=text,
                    row_number=row_number,
                    title="✏️ Твоя смена изменена"
                )
            except Exception as e:
                await message.answer(f"⚠️ Смена изменена, но уведомление не отправлено: {e}")
 
            pending_shift_actions.pop(admin_id, None)
            return
 
 
async def handle_fine_creation(message: types.Message):
    admin_id = message.from_user.id
    data = pending_fines.get(admin_id)
 
    if not data:
        return
 
    text = message.text.strip()
 
    if data["step"] == "telegram_id":
        data["telegram_id"] = text
        employee = find_employee_by_telegram_id(text)
        data["employee"] = employee or "Неизвестный сотрудник"
        data["step"] = "amount"
        pending_fines[admin_id] = data
 
        await message.answer(
            f"Сотрудник: {data['employee']}\n\n"
            "Теперь отправь сумму штрафа числом."
        )
        return
 
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
 
        fines_sheet.append_row([
            created_at,
            data["employee"],
            data["telegram_id"],
            data["amount"],
            reason,
            admin_id
        ])
 
        await message.answer(
            f"✅ Штраф выписан\n\n"
            f"👤 Сотрудник: {data['employee']}\n"
            f"ID: {data['telegram_id']}\n"
            f"💸 Сумма: {data['amount']:g} ₽\n"
            f"Причина: {reason}",
            reply_markup=admin_keyboard()
        )
 
        try:
            await bot.send_message(
                int(data["telegram_id"]),
                f"💸 Тебе выписан штраф\n\n"
                f"Сумма: {data['amount']:g} ₽\n"
                f"Причина: {reason}\n"
                f"Дата: {created_at}"
            )
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
 
    problems_sheet.append_row([
        created_at,
        employee,
        telegram_id,
        shift_date,
        shift,
        problem
    ])
 
    await bot.send_message(
        ADMIN_ID,
        f"⚠️ Проблема со сменой\n\n"
        f"👤 Сотрудник: {employee}\n"
        f"📅 Дата: {shift_date}\n"
        f"🕒 Смена: {shift}\n\n"
        f"Причина:\n{problem}"
    )
 
    await message.answer("⚠️ Сообщение отправлено администратору.")
 
 
scheduler = AsyncIOScheduler()
 
scheduler.add_job(
    send_shift_notifications,
    trigger="cron",
    hour=20,
    minute=0
)
 
 
async def main():
    scheduler.start()
    print("Бот запущен V9 schedule management")
    await dp.start_polling(bot)
 
 
if __name__ == "__main__":
    asyncio.run(main())
