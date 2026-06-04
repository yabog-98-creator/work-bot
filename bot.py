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
    shift_date = row[headers["date"] - 1]
    shift = row[headers["shift"] - 1]

    await bot.send_message(
        ADMIN_ID,
        f"⚠️ Проблема со сменой\n\n"
        f"👤 Сотрудник: {employee}\n"
        f"📅 Дата: {shift_date}\n"
        f"🕒 Смена: {shift}\n\n"
        f"Причина:\n{message.text}"
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
    print("Бот запущен V3")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())