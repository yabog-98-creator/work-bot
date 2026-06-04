import asyncio
import os
import json
from datetime import datetime, timedelta
 
import gspread
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
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
 
creds = ServiceAccountCredentials.from_json_keyfile_dict(
    google_creds,
    scope
)
 
client = gspread.authorize(creds)
spreadsheet = client.open(SPREADSHEET_NAME)
 
sheet = spreadsheet.worksheet("schedule")
problems_sheet = spreadsheet.worksheet("problems")
 
pending_problems = {}
 
 
def is_admin(user_id):
    return int(user_id) == ADMIN_ID
 
 
def main_keyboard(user_id=None):
    keyboard = [
        [KeyboardButton(text="📊 Сколько у меня часов")]
    ]
 
    if user_id and is_admin(user_id):
        keyboard.append([KeyboardButton(text="👑 Админ-панель")])
 
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True
    )
 
 
def admin_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Подтверждённые смены")],
            [KeyboardButton(text="⚠️ Проблемные смены")],
            [KeyboardButton(text="📊 Часы сотрудников")],
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
    await message.answer(
        "Главное меню",
        reply_markup=main_keyboard(message.from_user.id)
    )
 
 
@dp.message(F.text == "👑 Админ-панель")
async def admin_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет доступа к админ-панели.")
        return
 
    await message.answer(
        "👑 Админ-панель",
        reply_markup=admin_keyboard()
    )
 
 
@dp.message(F.text == "📋 Подтверждённые смены")
async def admin_confirmed_shifts(message: types.Message):
    if not is_admin(message.from_user.id):
        return
 
    records = sheet.get_all_records()
    confirmed = []
 
    for row in records:
        if str(row.get("confirmed", "")).strip().upper() == "YES":
            confirmed.append(
                f"✅ {row.get('employee')} | {row.get('date')} | "
                f"{row.get('shift')} | {row.get('confirmed_hours') or row.get('hours')} ч."
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
    await message.answer(text)
 
 
@dp.message(F.text == "📊 Часы сотрудников")
async def admin_employee_hours(message: types.Message):
    if not is_admin(message.from_user.id):
        return
 
    records = sheet.get_all_records()
    totals = {}
 
    for row in records:
        if str(row.get("confirmed", "")).strip().upper() == "YES":
            employee = row.get("employee")
            hours = row.get("confirmed_hours") or row.get("hours") or 0
 
            try:
                totals[employee] = totals.get(employee, 0) + float(hours)
            except Exception:
                pass
 
    if not totals:
        await message.answer("Пока нет подтверждённых часов.")
        return
 
    lines = [
        f"👤 {employee}: {hours:g} ч."
        for employee, hours in totals.items()
    ]
 
    await message.answer("📊 Часы сотрудников:\n\n" + "\n".join(lines))
 
 
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
                hours = row.get("confirmed_hours") or row.get("hours") or 0
 
                try:
                    total_hours += float(hours)
                    confirmed_count += 1
                except Exception:
                    pass
 
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
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="✅ Подтвердить смену",
                                callback_data=f"confirm:{index}"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text="⚠️ Не могу выйти",
                                callback_data=f"problem:{index}"
                            )
                        ]
                    ]
                )
 
                text = (
                    f"📅 Напоминание о смене\n\n"
                    f"👤 {employee}\n"
                    f"🕒 Завтра у тебя смена:\n"
                    f"{shift}"
                )
 
                await bot.send_message(
                    chat_id=int(telegram_id),
                    text=text,
                    reply_markup=keyboard
                )
 
                print(f"Отправлено: {employee}")
 
        except Exception as e:
            print(f"Ошибка: {e}")
 
 
@dp.callback_query(F.data.startswith("confirm:"))
async def confirm_shift(callback: types.CallbackQuery):
    row_number = int(callback.data.split(":")[1])
    headers = get_headers()
    row = sheet.row_values(row_number)
 
    employee = row[headers["employee"] - 1]
    shift_date = row[headers["date"] - 1]
    shift = row[headers["shift"] - 1]
 
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
 
    await callback.message.answer(
        "⚠️ Опиши проблему со сменой одним сообщением."
    )
 
    await callback.answer()
 
 
@dp.message()
async def problem_text_handler(message: types.Message):
    user_id = message.from_user.id
 
    if user_id not in pending_problems:
        return
 
    row_number = pending_problems.pop(user_id)
    headers = get_headers()
    row = sheet.row_values(row_number)
 
    employee = row[headers["employee"] - 1]
    telegram_id = row[headers["telegram_id"] - 1]
    shift_date = row[headers["date"] - 1]
    shift = row[headers["shift"] - 1]
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
    print("Бот запущен V4")
    await dp.start_polling(bot)
 
 
if __name__ == "__main__":
    asyncio.run(main())
