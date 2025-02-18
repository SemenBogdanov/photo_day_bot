import configparser

import telebot
from telebot import types
from datetime import datetime, timedelta
import pytz
import psycopg2
import asyncio
import time

config = configparser.ConfigParser()
config.read('/home/semen106/abc/py_conf/global_config.cfg')

# For test
# config.read(r'C:\PYTHON_CONFIG\global_config.cfg')

# Настройки
TOKEN = config['PHOTO_DAY_BOT']['photo_day_bot_token']
DB_CONNECTION = psycopg2.connect(
    dbname=config['HOSTER_KC_DB']['database'],
    user=config['HOSTER_KC_DB']['user'],
    password=config['HOSTER_KC_DB']['password'],
    host=config['HOSTER_KC_DB']['host'],
    port=config['HOSTER_KC_DB']['port']
)
cursor = DB_CONNECTION.cursor()
bot = telebot.TeleBot(TOKEN)
moscow_tz = pytz.timezone('Europe/Moscow')


# Помощь для работы с задачами в БД
def start_task(user_id, title):
    start_time = datetime.now(moscow_tz)
    cursor.execute(
        "INSERT INTO dal_data.tasks (user_id, title, start_time, status) VALUES (%s, %s, %s, %s) RETURNING id",
        (user_id, title, start_time, 'active',)
    )
    task_id = cursor.fetchone()[0]
    DB_CONNECTION.commit()
    return task_id, start_time


def end_task(user_id, task_id):
    end_time = datetime.now(moscow_tz)
    cursor.execute(
        "UPDATE dal_data.tasks SET end_time = %s, status = %s WHERE id = %s AND user_id = %s",
        (end_time, 'inactive', task_id, user_id,)
    )
    DB_CONNECTION.commit()


def get_active_task(user_id):
    cursor.execute(
        "SELECT id, title FROM dal_data.tasks WHERE user_id = %s AND status = %s ORDER BY start_time DESC LIMIT 1",
        (user_id, 'active',)
    )
    return cursor.fetchone()


def create_activity(user_id, activity_name):
    start_time = datetime.now(moscow_tz)
    cursor.execute(
        "INSERT INTO dal_data.user_activities (user_id, activity_name, start_time, is_active) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (user_id, activity_name, start_time, True,)
    )
    activity_id = cursor.fetchone()[0]
    DB_CONNECTION.commit()
    return activity_id


# Основные обработчики
@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.from_user.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    tasks_button = types.KeyboardButton("Мои задачи")
    lunch_button = types.KeyboardButton("Обед")
    complete_button = types.KeyboardButton("Завершить задачу")
    markup.add(tasks_button, lunch_button, complete_button)
    bot.send_message(message.chat.id, "Добро пожаловать! Выберите действие:", reply_markup=markup)


@bot.message_handler(func=lambda message: message.text == "Мои задачи")
def show_tasks(message):
    user_id = message.from_user.id
    active_task = get_active_task(user_id)
    if active_task:
        task_id, title = active_task
        bot.send_message(
            message.chat.id, f"Вы работаете над: {title}. Нажмите 'Завершить задачу', чтобы завершить.")
    else:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        create_task_button = types.KeyboardButton("Создать задачу")
        markup.add(create_task_button)
        bot.send_message(message.chat.id, "Нет активных задач. Выберите 'Создать задачу' для начала.",
                         reply_markup=markup)


@bot.message_handler(func=lambda message: message.text == "Обед")
def lunch(message):
    user_id = message.from_user.id
    task_id, _ = start_task(user_id, "Обед")
    bot.send_message(message.chat.id, "Обед начался!")


@bot.message_handler(func=lambda message: message.text == "Завершить задачу")
def finish_task(message, reply=True):
    user_id = message.from_user.id
    active_task = get_active_task(user_id)
    if active_task:
        task_id, title = active_task
        end_task(user_id, task_id)
        bot.send_message(message.chat.id, f"Задача '{title}' завершена!")
    else:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        create_task_button = types.KeyboardButton("Создать задачу")
        markup.add(create_task_button)
        if reply:
            bot.send_message(message.chat.id, "Нет активных задач для завершения.", reply_markup=markup)


@bot.message_handler(func=lambda message: message.text == "Создать задачу")
def create_new_task(message):
    finish_task(message, reply=False)
    bot.send_message(message.chat.id, "Введите название задачи:")
    bot.register_next_step_handler(message, create_task_handler)


def create_task_handler(message):
    user_id = message.from_user.id
    task_name = message.text
    task_id, start_time = start_task(user_id, task_name)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    tasks_button = types.KeyboardButton("Мои задачи")
    lunch_button = types.KeyboardButton("Обед")
    complete_button = types.KeyboardButton("Завершить задачу")
    markup.add(tasks_button, lunch_button, complete_button)
    bot.send_message(message.chat.id, f"Задача '{task_name}' начата в {start_time.strftime('%H:%M:%S')}."
                     , reply_markup=markup)


# Уведомления
async def send_reminders():
    while True:
        time.sleep(240)
        cursor.execute(
            "SELECT id, user_id, title, start_time FROM dal_data.tasks WHERE status = 'active' AND end_time IS NULL"
        )
        active_tasks = cursor.fetchall()
        for task in active_tasks:
            task_id, user_id, title, start_time = task
            if datetime.now(moscow_tz) - start_time > timedelta(hours=2):
                bot.send_message(user_id,
                                 f"Напоминание: задача '{title}' активна уже более 2 часов. Завершите ее, если нужно.")


# Функция для получения задач пользователя за день
def get_user_tasks_for_day(user_id):
    # Текущая дата и начало дня
    today = datetime.now(moscow_tz).date()
    start_of_day = datetime.combine(today, datetime.min.time(), moscow_tz)
    end_of_day = datetime.combine(today, datetime.max.time(), moscow_tz)

    # Запрос всех задач за сегодня
    cursor.execute(
        """
        SELECT title, start_time, end_time
        FROM dal_data.tasks
        WHERE user_id = %s AND start_time BETWEEN %s AND %s
        ORDER BY start_time ASC
        """, (user_id, start_of_day, end_of_day)
    )
    return cursor.fetchall()


# Функция для вычисления общего времени по задачам
def get_total_time(tasks):
    total_time = timedelta()
    task_details = []
    for task in tasks:
        title, start_time, end_time = task
        # Если задача не завершена, то считаем время до текущего момента
        if end_time is None:
            end_time = datetime.now(moscow_tz)

        # Вычисляем время, затраченное на задачу
        task_duration = end_time - start_time
        total_time += task_duration

        task_details.append(f"{title}: {str(task_duration)}")

    return total_time, task_details


# Основная функция для закрытия дня
@bot.message_handler(func=lambda message: message.text.lower() == "фото дня")
def end_of_day_report(message):
    user_id = message.from_user.id

    # Получаем задачи пользователя за сегодняшний день
    tasks = get_user_tasks_for_day(user_id)

    print(tasks)

    if tasks:
        # Получаем общее время и детали по задачам
        total_time, task_details = get_total_time(tasks)

        # Формируем сообщение для пользователя
        report_message = f"Ваш отчет за сегодня:\n\nОбщее время: {str(total_time)}\n\nЗадачи:\n"
        for detail in task_details:
            report_message += f"- {detail}\n"

        bot.send_message(message.chat.id, report_message)
    else:
        bot.send_message(message.chat.id, "Сегодня у вас нет завершенных задач.")


# Запуск бота и уведомлений
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(send_reminders())
    bot.polling(none_stop=True)
