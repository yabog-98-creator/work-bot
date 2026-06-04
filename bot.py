import asyncio
import os
import json
from datetime import datetime, timedelta

import gspread
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials

# =========================
# ENV
# =========================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME")

# =========================
# BOT
# =========================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# =========================
# GOOGLE SHEETS
# =========================

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

sheet = client.open(SPREADSHEET_NAME).worksheet("schedule")

# =========================
# START
# =========================

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    user_id = message.from_user.id

    text = (
        f"Привет, {message.from_user.first_name}!\n\n"
        f"Твой Telegram ID:\n"
        f"{user_id}\n\n"
        f"Передай этот ID администратору."
    )

    await message.answer(text)

# =========================
# TEST
# =========================

@dp.message(Command("test"))
async def test_command(message: types.Message):
    await send_shift_notifications()
    await message.answer("Тест уведомлений запущен")

# =========================
# NOTIFICATIONS
# =========================

async def send_shift_notifications():

    tomorrow = (
        datetime.now() + timedelta(days=1)
    ).strftime("%d.%m.%Y")

    records = sheet.get_all_records()

    print(f"Проверяем смены на {tomorrow}")

    for row in records:
        try:
            employee = row["employee"]
            telegram_id = str(row["telegram_id"]).strip()
            shift_date = row["date"]
            shift = row["shift"]

            if shift_date == tomorrow:

                text = (
                    f"📅 Напоминание о смене\n\n"
                    f"👤 {employee}\n"
                    f"🕒 Завтра у тебя смена:\n"
                    f"{shift}"
                )

                await bot.send_message(
                    chat_id=int(telegram_id),
                    text=text
                )

                print(f"Отправлено: {employee}")

        except Exception as e:
            print(f"Ошибка: {e}")

# =========================
# SCHEDULER
# =========================

scheduler = AsyncIOScheduler()

scheduler.add_job(
    send_shift_notifications,
    trigger="cron",
    hour=20,
    minute=0
)

# =========================
# MAIN
# =========================

async def main():

    scheduler.start()

    print("Бот запущен V2")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())