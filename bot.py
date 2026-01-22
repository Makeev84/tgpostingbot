#!/usr/bin/env python3
"""
Telegram Bot для публикации фото с модерацией
"""

import logging
import sqlite3
import re
import os
from datetime import datetime
from typing import Dict, Optional, Tuple
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters
)

# ========== НАСТРОЙКА ==========
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
MODERATOR_GROUP_ID = int(os.getenv('MODERATOR_GROUP_ID', '-1001234567890'))
CHANNEL_ID = os.getenv('CHANNEL_ID', '@your_channel')

# Состояния для FSM
SELECTING_LANGUAGE, WAITING_PHOTO, WAITING_AGE, WAITING_COUNTRY, WAITING_ANON, WAITING_USERNAME = range(6)

# Поддерживаемые языки
SUPPORTED_LANGUAGES = {
    'en': 'English 🇺🇸',
    'ru': 'Русский 🇷🇺'
}

# Локализация
LOCALIZATION = {
    'en': {
        'welcome': "Hello {name}! 👋\nI'm a photo submission bot. Please select your language:",
        'select_language': "Please select your language:",
        'language_set': "Language set to English. You can change it with /language command.\n\nNow send me a photo to start.",
        'send_photo': "📸 Photo received! Now send your age (numbers only):",
        'invalid_age': "Please send age as numbers:",
        'age_limits': "Age must be between 18 and 100 years. Try again:",
        'enter_country': "Now enter your country:\nYou can send:\n• Flag emoji (🇺🇸, 🇷🇺)\n• Country name (USA, Russia)\n• 2-letter code (us, ru)",
        'country_clarification': "Please clarify the country:\n1. Send flag emoji (🇺🇸, 🇷🇺 etc.)\n2. Write full name (United States, Россия)\n3. Use 2-letter code (us, ru, gb)",
        'select_mode': "Select publication mode:\nSend: 'anon' or 'not anon'",
        'anonymous': "👤 Anon",
        'not_anonymous': "📝 Not anon",
        'submitted': "✅ Your post has been submitted for moderation! We will notify you of the result.",
        'error': "❌ An error occurred while creating the post. Please try later.",
        'cancel': "Action cancelled. Send a photo to start over.",
        'post_approved': "✅ Your post has been approved and published!",
        'post_rejected': "❌ Your post has been rejected by moderators.",
        'language_changed': "Language changed to English.",
        'no_username': "You don't have a username (@nickname) set in your Telegram profile.\n\nTo post non-anonymously, you need to set a username in Telegram settings.\n\nOptions:\n1. Set a username in Telegram and try again\n2. Post anonymously (send 'anon')",
        'username_required': "Please provide your Telegram username (with @) or choose to post anonymously.",
        'enter_username': "Please enter your Telegram username (with @, e.g., @username):",
        'invalid_username': "Username should start with @. Please enter a valid username or send 'anon' to post anonymously:"
    },
    'ru': {
        'welcome': "Привет, {name}! 👋\nЯ бот для отправки фото. Пожалуйста, выберите язык:",
        'select_language': "Пожалуйста, выберите язык:",
        'language_set': "Язык изменен на Русский. Вы можете изменить его командой /language.\n\nТеперь отправьте мне фото, чтобы начать.",
        'send_photo': "📸 Фото получено! Теперь отправьте ваш возраст (только цифры):",
        'invalid_age': "Пожалуйста, отправьте возраст цифрами:",
        'age_limits': "Возраст должен быть от 18 до 100 лет. Попробуйте еще раз:",
        'enter_country': "Теперь укажите вашу страну:\nМожно отправить:\n• Эмодзи флага (🇺🇸, 🇷🇺)\n• Название страны (USA, Russia)\n• 2-буквенный код (us, ru)",
        'country_clarification': "Пожалуйста, уточните страну:\n1. Отправьте эмодзи флага (🇺🇸, 🇷🇺 и т.д.)\n2. Напишите полное название (United States, Россия)\n3. Используйте 2-буквенный код (us, ru, gb)",
        'select_mode': "Выберите режим публикации:\nНапишите: 'анон' или 'не анон'",
        'anonymous': "👤 Анон",
        'not_anonymous': "📝 Не анон",
        'submitted': "✅ Ваш пост отправлен на модерацию! Мы уведомим вас о результате.",
        'error': "❌ Произошла ошибка при создании поста. Попробуйте позже.",
        'cancel': "Действие отменено. Отправьте фото чтобы начать заново.",
        'post_approved': "✅ Ваш пост одобрен и опубликован!",
        'post_rejected': "❌ Ваш пост отклонен модераторами.",
        'language_changed': "Язык изменен на Русский.",
        'no_username': "У вас не установлен username (@никнейм) в Telegram.\n\nДля публикации не анонимно нужно установить username в настройках Telegram.\n\nВарианты:\n1. Установите username в Telegram и попробуйте снова\n2. Опубликуйте анонимно (отправьте 'анон')",
        'username_required': "Пожалуйста, укажите ваш Telegram username (с @) или выберите анонимную публикацию.",
        'enter_username': "Пожалуйста, введите ваш Telegram username (с @, например, @username):",
        'invalid_username': "Username должен начинаться с @. Пожалуйста, введите правильный username или отправьте 'анон' для анонимной публикации:"
    }
}

# ========== БАЗА ДАННЫХ ==========
class Database:
    def __init__(self, db_name='bot_database.db'):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.create_tables()
        self.migrate_tables()

    def create_tables(self):
        cursor = self.conn.cursor()

        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                language TEXT DEFAULT 'en',
                topic_id INTEGER,
                reg_date TIMESTAMP
            )
        ''')

        # Таблица постов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS posts (
                post_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                photo_id TEXT,
                age INTEGER,
                country TEXT,
                country_emoji TEXT,
                is_anonymous BOOLEAN,
                display_username TEXT,
                mod_chat_id INTEGER,
                mod_message_id INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP,
                published_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        self.conn.commit()

    def migrate_tables(self):
        """Добавляем недостающие колонки если таблицы уже существуют"""
        cursor = self.conn.cursor()

        try:
            # Проверяем есть ли колонка topic_id в таблице users
            cursor.execute("PRAGMA table_info(users)")
            columns = [column[1] for column in cursor.fetchall()]

            if 'topic_id' not in columns:
                cursor.execute('ALTER TABLE users ADD COLUMN topic_id INTEGER')
                logging.info("Added topic_id column to users table")

            # Проверяем есть ли колонка mod_message_id в таблице posts
            cursor.execute("PRAGMA table_info(posts)")
            columns = [column[1] for column in cursor.fetchall()]

            if 'mod_message_id' not in columns:
                cursor.execute('ALTER TABLE posts ADD COLUMN mod_message_id INTEGER')
                logging.info("Added mod_message_id column to posts table")

            if 'display_username' not in columns:
                cursor.execute('ALTER TABLE posts ADD COLUMN display_username TEXT')
                logging.info("Added display_username column to posts table")

            self.conn.commit()

        except Exception as e:
            logging.error(f"Error during migration: {e}")
            self.conn.rollback()

    def add_user(self, user_id, username, full_name):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, full_name, reg_date)
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, full_name, datetime.now()))
        self.conn.commit()

    def set_user_language(self, user_id, language):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE users SET language = ? WHERE user_id = ?', (language, user_id))
        self.conn.commit()

    def set_user_topic(self, user_id, topic_id):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE users SET topic_id = ? WHERE user_id = ?', (topic_id, user_id))
        self.conn.commit()

    def get_user_language(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT language FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        return result[0] if result else 'en'

    def get_user_topic(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT topic_id FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        return result[0] if result else None

    def create_post(self, user_id, photo_id, age, country, country_emoji, is_anonymous, display_username, mod_chat_id, mod_message_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO posts 
            (user_id, photo_id, age, country, country_emoji, is_anonymous, display_username, mod_chat_id, mod_message_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, photo_id, age, country, country_emoji, is_anonymous, display_username, mod_chat_id, mod_message_id, datetime.now()))
        post_id = cursor.lastrowid
        self.conn.commit()
        return post_id

    def update_post_status(self, post_id, status, mod_message_id=None):
        cursor = self.conn.cursor()
        if mod_message_id:
            cursor.execute('''
                UPDATE posts
                SET status = ?, published_at = ?, mod_message_id = ?
                WHERE post_id = ?
            ''', (status, datetime.now() if status == 'published' else None, mod_message_id, post_id))
        else:
            cursor.execute('''
                UPDATE posts 
                SET status = ?, published_at = ? 
                WHERE post_id = ?
            ''', (status, datetime.now() if status == 'published' else None, post_id))
        self.conn.commit()

    def get_post(self, post_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM posts WHERE post_id = ?', (post_id,))
        columns = [column[0] for column in cursor.description]
        result = cursor.fetchone()
        return dict(zip(columns, result)) if result else None

    def get_user(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        columns = [column[0] for column in cursor.description]
        result = cursor.fetchone()
        return dict(zip(columns, result)) if result else None

# Глобальный экземпляр базы данных
db = Database()

# ========== УТИЛИТЫ ДЛЯ СТРАН ==========
class CountryUtils:
    def __init__(self):
        self.country_cache = self._initialize_country_cache()

    def _initialize_country_cache(self):
        cache = {}
        countries = {
            'us': {'name': 'United States', 'emoji': '🇺🇸'},
            'ru': {'name': 'Russia', 'emoji': '🇷🇺'},
            'gb': {'name': 'United Kingdom', 'emoji': '🇬🇧'},
            'de': {'name': 'Germany', 'emoji': '🇩🇪'},
            'fr': {'name': 'France', 'emoji': '🇫🇷'},
            'es': {'name': 'Spain', 'emoji': '🇪🇸'},
            'it': {'name': 'Italy', 'emoji': '🇮🇹'},
            'cn': {'name': 'China', 'emoji': '🇨🇳'},
            'jp': {'name': 'Japan', 'emoji': '🇯🇵'},
            'kr': {'name': 'South Korea', 'emoji': '🇰🇷'},
            'br': {'name': 'Brazil', 'emoji': '🇧🇷'},
            'ca': {'name': 'Canada', 'emoji': '🇨🇦'},
            'au': {'name': 'Australia', 'emoji': '🇦🇺'},
            'in': {'name': 'India', 'emoji': '🇮🇳'},
            'ua': {'name': 'Ukraine', 'emoji': '🇺🇦'},
            'pl': {'name': 'Poland', 'emoji': '🇵🇱'},
            'tr': {'name': 'Turkey', 'emoji': '🇹🇷'},
            'nl': {'name': 'Netherlands', 'emoji': '🇳🇱'},
            'se': {'name': 'Sweden', 'emoji': '🇸🇪'},
            'no': {'name': 'Norway', 'emoji': '🇳🇴'},
        }

        for code, data in countries.items():
            cache[code] = data
            cache[data['name'].lower()] = data

        russian_names = {
            'россия': countries['ru'],
            'рф': countries['ru'],
            'русский': countries['ru'],
            'сша': countries['us'],
            'америка': countries['us'],
            'американский': countries['us'],
            'великобритания': countries['gb'],
            'англия': countries['gb'],
            'английский': countries['gb'],
            'британский': countries['gb'],
            'германия': countries['de'],
            'немецкий': countries['de'],
            'франция': countries['fr'],
            'французский': countries['fr'],
            'испания': countries['es'],
            'испанский': countries['es'],
            'италия': countries['it'],
            'итальянский': countries['it'],
            'китай': countries['cn'],
            'китайский': countries['cn'],
            'япония': countries['jp'],
            'японский': countries['jp'],
            'корея': countries['kr'],
            'корейский': countries['kr'],
            'бразилия': countries['br'],
            'бразильский': countries['br'],
            'канада': countries['ca'],
            'канадский': countries['ca'],
            'австралия': countries['au'],
            'австралийский': countries['au'],
            'индия': countries['in'],
            'индийский': countries['in'],
            'украина': countries['ua'],
            'украинский': countries['ua'],
            'польша': countries['pl'],
            'польский': countries['pl'],
            'турция': countries['tr'],
            'турецкий': countries['tr'],
            'нидерланды': countries['nl'],
            'голландия': countries['nl'],
            'голландский': countries['nl'],
            'швеция': countries['se'],
            'шведский': countries['se'],
            'норвегия': countries['no'],
            'норвежский': countries['no'],
        }

        cache.update(russian_names)
        return cache

    def parse_country_input(self, text: str) -> Optional[Dict]:
        text = text.strip().lower()

        flag_emoji_pattern = re.compile(r'[\U0001F1E6-\U0001F1FF]{2}')
        if flag_emoji_pattern.match(text):
            return {
                'name': text.upper(),
                'emoji': text,
                'code': '??'
            }

        if text in self.country_cache:
            return self.country_cache[text]

        for key, data in self.country_cache.items():
            if isinstance(key, str) and text in key:
                return data

        return None

country_utils = CountryUtils()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_user_language(user_id: int) -> str:
    """Получить язык пользователя"""
    return db.get_user_language(user_id)

def get_text(key: str, user_id: int, **kwargs) -> str:
    """Получить локализованный текст"""
    lang = get_user_language(user_id)
    text = LOCALIZATION[lang].get(key, key)
    return text.format(**kwargs) if kwargs else text

def get_language_keyboard():
    """Клавиатура для выбора языка"""
    keyboard = [
        [InlineKeyboardButton("English 🇺🇸", callback_data="lang_en")],
        [InlineKeyboardButton("Русский 🇷🇺", callback_data="lang_ru")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_anon_keyboard(user_id: int):
    """Клавиатура для выбора анонимности"""
    lang = get_user_language(user_id)
    if lang == 'ru':
        keyboard = [['анон', 'не анон']]
    else:
        keyboard = [['anon', 'not anon']]
    return ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

def get_moderation_keyboard(post_id: int):
    """Инлайн-клавиатура для модерации"""
    keyboard = [
        [
            InlineKeyboardButton("✅ Запостить", callback_data=f"approve_{post_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{post_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def parse_anon_input(text: str, lang: str) -> Optional[bool]:
    """Парсит ввод анонимности"""
    text_lower = text.strip().lower()

    if lang == 'ru':
        anon_keywords = ['анон', 'анонимно', 'anon', 'anonymous']
        not_anon_keywords = ['не анон', 'не анонимно', 'не anon', 'not anon', 'not anonymous']
    else:
        anon_keywords = ['anon', 'anonymous', 'анон', 'анонимно']
        not_anon_keywords = ['not anon', 'not anonymous', 'не анон', 'не анонимно']

    for keyword in anon_keywords:
        if keyword in text_lower:
            return True

    for keyword in not_anon_keywords:
        if keyword in text_lower:
            return False

    return None

def format_post_text(country_emoji: str, user_display: str, age: int) -> str:
    """Форматирует текст поста с HTML разметкой"""
    # Username жирным
    user_text = f"<b>{user_display}</b>"

    # Возраст жирным
    age_text = f"<b>Age: {age}</b>"

    # POST YOUR BULGE жирным и как ссылка
    post_text = f'<b><a href="https://t.me/bulgebotbot">POST YOUR BULGE</a></b>'

    return f"{country_emoji} {user_text}\n\n{age_text}\n\n{post_text}"

def is_valid_username(username: str) -> bool:
    """Проверяет валидность username"""
    username = username.strip()
    return username.startswith('@') and len(username) > 1

# ========== ОБРАБОТЧИКИ КОМАНД ==========
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    db.add_user(user.id, user.username, user.full_name)

    await update.message.reply_text(
        get_text('welcome', user.id, name=user.first_name),
        reply_markup=get_language_keyboard()
    )
    return SELECTING_LANGUAGE

async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для смены языка"""
    await update.message.reply_text(
        get_text('select_language', update.effective_user.id),
        reply_markup=get_language_keyboard()
    )
    return SELECTING_LANGUAGE

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия"""
    user = update.effective_user
    await update.message.reply_text(
        get_text('cancel', user.id),
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора языка"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    language = query.data.replace('lang_', '')

    if language in SUPPORTED_LANGUAGES:
        db.set_user_language(user_id, language)
        await query.edit_message_text(
            text=get_text('language_set', user_id)
        )
        return WAITING_PHOTO

    return SELECTING_LANGUAGE

# ========== ОСНОВНОЙ FLOW ==========
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение фото"""
    user = update.effective_user
    photo = update.message.photo[-1]
    context.user_data['photo_id'] = photo.file_id

    await update.message.reply_text(
        get_text('send_photo', user.id)
    )
    return WAITING_AGE

async def handle_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение возраста"""
    user = update.effective_user
    age_text = update.message.text.strip()

    if not age_text.isdigit():
        await update.message.reply_text(get_text('invalid_age', user.id))
        return WAITING_AGE

    age = int(age_text)
    if age < 18 or age > 100:
        await update.message.reply_text(get_text('age_limits', user.id))
        return WAITING_AGE

    context.user_data['age'] = age

    await update.message.reply_text(
        get_text('enter_country', user.id),
        reply_markup=ReplyKeyboardRemove()
    )
    return WAITING_COUNTRY

async def handle_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение страны"""
    user = update.effective_user
    country_input = update.message.text.strip()
    country_data = country_utils.parse_country_input(country_input)

    if not country_data:
        await update.message.reply_text(get_text('country_clarification', user.id))
        return WAITING_COUNTRY

    context.user_data['country'] = country_data['name']
    context.user_data['country_emoji'] = country_data['emoji']

    await update.message.reply_text(
        get_text('select_mode', user.id),
        reply_markup=get_anon_keyboard(user.id)
    )
    return WAITING_ANON

async def handle_anon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение выбора анонимности"""
    user = update.effective_user
    choice = update.message.text

    lang = get_user_language(user.id)
    is_anonymous = parse_anon_input(choice, lang)

    if is_anonymous is None:
        await update.message.reply_text(
            get_text('select_mode', user.id),
            reply_markup=get_anon_keyboard(user.id)
        )
        return WAITING_ANON

    if is_anonymous:
        # Если выбрана анонимность - сразу создаем пост
        context.user_data['is_anonymous'] = True
        context.user_data['display_username'] = "Anon"
        return await create_post(update, context)
    else:
        # Если выбрано не анонимно - проверяем наличие username
        if not user.username:
            await update.message.reply_text(
                get_text('no_username', user.id),
                reply_markup=ReplyKeyboardRemove()
            )
            return WAITING_USERNAME
        else:
            context.user_data['is_anonymous'] = False
            context.user_data['display_username'] = f"@{user.username}"
            return await create_post(update, context)

async def handle_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода username"""
    user = update.effective_user
    user_input = update.message.text.strip()

    # Проверяем, не хочет ли пользователь переключиться на анонимность
    lang = get_user_language(user.id)
    is_anonymous = parse_anon_input(user_input, lang)

    if is_anonymous is not None:
        if is_anonymous:
            # Пользователь выбрал анонимность
            context.user_data['is_anonymous'] = True
            context.user_data['display_username'] = "Anon"
            return await create_post(update, context)
        else:
            # Пользователь снова выбрал не анонимно
            await update.message.reply_text(
                get_text('enter_username', user.id),
                reply_markup=ReplyKeyboardRemove()
            )
            return WAITING_USERNAME

    # Проверяем валидность username
    if is_valid_username(user_input):
        context.user_data['is_anonymous'] = False
        context.user_data['display_username'] = user_input
        return await create_post(update, context)
    else:
        await update.message.reply_text(
            get_text('invalid_username', user.id),
            reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_USERNAME

async def create_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание поста (общая функция)"""
    user = update.effective_user
    user_data = context.user_data

    try:
        # Проверяем, есть ли уже тема для пользователя
        existing_topic_id = db.get_user_topic(user.id)

        if existing_topic_id:
            # Используем существующую тему
            topic_id = existing_topic_id
            # Отправляем разделитель для нового поста
            await context.bot.send_message(
                chat_id=MODERATOR_GROUP_ID,
                message_thread_id=topic_id,
                text=f"🆕 New submission from {user.first_name} ({user.id})"
            )
        else:
            # Создаем новую тему
            topic_name = f"{user.first_name} ({user.id})"
            topic = await context.bot.create_forum_topic(
                chat_id=MODERATOR_GROUP_ID,
                name=topic_name
            )
            topic_id = topic.message_thread_id
            db.set_user_topic(user.id, topic_id)

        # Формируем текст поста
        post_text = format_post_text(
            user_data['country_emoji'],
            user_data['display_username'],
            user_data['age']
        )

        # Отправляем фото в тему с временными кнопками
        message = await context.bot.send_photo(
            chat_id=MODERATOR_GROUP_ID,
            message_thread_id=topic_id,
            photo=user_data['photo_id'],
            caption=post_text,
            parse_mode='HTML'
        )

        # Создаем пост в базе данных с ID сообщения
        post_id = db.create_post(
            user_id=user.id,
            photo_id=user_data['photo_id'],
            age=user_data['age'],
            country=user_data['country'],
            country_emoji=user_data['country_emoji'],
            is_anonymous=user_data.get('is_anonymous', True),
            display_username=user_data['display_username'],
            mod_chat_id=MODERATOR_GROUP_ID,
            mod_message_id=message.message_id
        )

        # Отправляем кнопки модерации как отдельное сообщение
        button_message = await context.bot.send_message(
            chat_id=MODERATOR_GROUP_ID,
            message_thread_id=topic_id,
            text=f"Post #{post_id} - Moderation",
            reply_markup=get_moderation_keyboard(post_id)
        )

        # Сохраняем ID сообщения с кнопками
        db.update_post_status(post_id, 'pending', button_message.message_id)

        await update.message.reply_text(
            get_text('submitted', user.id),
            reply_markup=ReplyKeyboardRemove()
        )

    except Exception as e:
        logging.error(f"Error creating post: {e}")
        await update.message.reply_text(
            get_text('error', user.id)
        )

    # Очищаем данные пользователя
    context.user_data.clear()
    return ConversationHandler.END

# ========== МОДЕРАЦИЯ ==========
async def handle_moderation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатия кнопок модерации"""
    query = update.callback_query
    await query.answer()

    action, post_id = query.data.split('_')
    post_id = int(post_id)

    # Получаем данные поста
    post = db.get_post(post_id)
    if not post:
        await query.message.reply_text("Post not found!")
        return

    if action == 'approve':
        # Публикация в канал
        try:
            # Формируем финальный пост
            post_text = format_post_text(
                post['country_emoji'],
                post['display_username'],
                post['age']
            )

            # Публикуем в канал
            channel_message = await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=post['photo_id'],
                caption=post_text,
                parse_mode='HTML'
            )

            # Обновляем статус поста
            db.update_post_status(post_id, 'published', channel_message.message_id)

            # Убираем кнопки из сообщения модерации
            await query.edit_message_reply_markup(reply_markup=None)

            # Обновляем текст сообщения с кнопками
            await query.edit_message_text(
                text=f"✅ Post #{post_id} published in channel",
                reply_markup=None
            )

            # Добавляем отметку о публикации
            await context.bot.send_message(
                chat_id=MODERATOR_GROUP_ID,
                message_thread_id=db.get_user_topic(post['user_id']),
                text=f"✅ Published in channel: {CHANNEL_ID}"
            )

            # Уведомляем пользователя
            try:
                user_lang = db.get_user_language(post['user_id'])
                approval_text = LOCALIZATION[user_lang]['post_approved']
                await context.bot.send_message(
                    chat_id=post['user_id'],
                    text=approval_text
                )
            except Exception as e:
                logging.error(f"Could not notify user: {e}")

        except Exception as e:
            logging.error(f"Error publishing post: {e}")
            await query.message.reply_text(f"❌ Error: {str(e)}")

    elif action == 'reject':
        # Отклонение поста
        db.update_post_status(post_id, 'rejected')

        # Убираем кнопки из сообщения модерации
        await query.edit_message_reply_markup(reply_markup=None)

        # Обновляем текст сообщения с кнопками
        await query.edit_message_text(
            text=f"❌ Post #{post_id} rejected",
            reply_markup=None
        )

        # Добавляем отметку об отклонении
        await context.bot.send_message(
            chat_id=MODERATOR_GROUP_ID,
            message_thread_id=db.get_user_topic(post['user_id']),
            text=f"❌ Post #{post_id} rejected by moderator"
        )

        # Уведомляем пользователя
        try:
            user_lang = db.get_user_language(post['user_id'])
            rejection_text = LOCALIZATION[user_lang]['post_rejected']
            await context.bot.send_message(
                chat_id=post['user_id'],
                text=rejection_text
            )
        except Exception as e:
            logging.error(f"Could not notify user: {e}")

# ========== ГЛАВНАЯ ФУНКЦИЯ ==========
def main():
    """Запуск бота"""
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )

    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()

    # Создаем ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start_command)],
        states={
            SELECTING_LANGUAGE: [
                CallbackQueryHandler(language_callback, pattern='^lang_'),
                CommandHandler('language', language_command)
            ],
            WAITING_PHOTO: [
                MessageHandler(filters.PHOTO, handle_photo),
                CommandHandler('language', language_command)
            ],
            WAITING_AGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_age),
                CommandHandler('cancel', cancel_command),
                CommandHandler('language', language_command)
            ],
            WAITING_COUNTRY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_country),
                CommandHandler('cancel', cancel_command),
                CommandHandler('language', language_command)
            ],
            WAITING_ANON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_anon),
                CommandHandler('cancel', cancel_command),
                CommandHandler('language', language_command)
            ],
            WAITING_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_username),
                CommandHandler('cancel', cancel_command),
                CommandHandler('language', language_command)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel_command)],
        per_message=False
    )

    # Добавляем обработчики
    application.add_handler(conv_handler)

    # Добавляем обработчик модерации отдельно (не внутри ConversationHandler)
    application.add_handler(CallbackQueryHandler(handle_moderation_callback, pattern='^(approve|reject)_'))
    application.add_handler(CommandHandler('language', language_command))

    # Запускаем бота
    print("Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()