import os
import re
import time
import telebot
import telebot.apihelper as apihelper
from dotenv import load_dotenv
from telebot import types
import random
import datetime

from tarot_deck import TAROT_DECK
from trivia_questions import TRIVIA_QUESTIONS

load_dotenv()

# === 1. НАСТРОЙКИ ===
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
# Прокси только для локального запуска в РФ (на Railway не нужен)
TELEGRAM_PROXY = os.getenv('TELEGRAM_PROXY', '').strip()

if not BOT_TOKEN:
    raise RuntimeError('BOT_TOKEN не задан. Добавь в .env локально или в Variables на Railway.')

if TELEGRAM_PROXY:
    apihelper.proxy = {'https': TELEGRAM_PROXY, 'http': TELEGRAM_PROXY}

apihelper.CONNECT_TIMEOUT = 30
apihelper.READ_TIMEOUT = 30

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)
IMAGES_DIR = os.path.join(os.path.dirname(__file__), 'images')
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}

CARD_BUTTON = '🃏 Карта дня'
REDRAW_BUTTON = '🎲 Перевытянуть карту'

users_history = {}
users_extra_draw = {}
users_quiz = {}
users_spreads = {}
SPREAD_SIZE = 3

WARMUP_EXERCISES = [
    '25 приседаний',
    '30 наклонов корпусом вперёд',
    '20 прыжков на месте',
    '15 классических отжиманий (можно с колен)',
    '40 секунд планки',
    '30 махов руками в стороны',
    '20 выпадов на каждую ногу',
    '35 секунд бега на месте',
    '15 подъёмов на носки',
    '20 круговых вращений плечами',
    '30 секунд «велосипеда» лёжа',
    '10 раз: присед — планка — прыжок',
    '25 наклонов в стороны',
    '20 подъёмов коленей стоя на месте',
    '30 секунд стойки на одной ноге (по 15 на каждую)',
]

SPREAD_TOPICS = {
    'love': {
        'button': '💕 Любовь',
        'title': 'любовь',
        'positions': ['Твоё сердце', 'Энергия партнёра', 'Путь отношений'],
        'synthesis': (
            'Карты {cards} вместе рисуют целостную картину: {m1} '
            'Это перекликается с тем, что {m2} '
            'И завершает послание мысль о том, что {m3}'
        ),
    },
    'friendship': {
        'button': '🤝 Дружба',
        'title': 'дружбу',
        'positions': ['Ты в дружбе', 'Твой друг / окружение', 'Перспектива'],
        'synthesis': (
            'Расклад на дружбу ({cards}) складывается так: {m1} '
            'Рядом с этим {m2} '
            'В итоге карты советуют помнить, что {m3}'
        ),
    },
    'career': {
        'button': '💼 Карьера',
        'title': 'карьеру',
        'positions': ['Текущая ситуация', 'Препятствие', 'Результат'],
        'synthesis': (
            'Три карты карьеры — {cards} — говорят в одном ключе: {m1} '
            'При этом {m2} '
            'Общий вывод: {m3}'
        ),
    },
    'finances': {
        'button': '💰 Финансы',
        'title': 'финансы',
        'positions': ['Доходы', 'Риски и траты', 'Перспектива'],
        'synthesis': (
            'Финансовый расклад ({cards}) показывает: {m1} '
            'Одновременно {m2} '
            'Совокупно карты намекают: {m3}'
        ),
    },
}

BUTTON_TO_TOPIC = {info['button']: topic for topic, info in SPREAD_TOPICS.items()}
MENU_BUTTONS = {CARD_BUTTON, REDRAW_BUTTON, *BUTTON_TO_TOPIC.keys()}


def capitalize_sentence(text):
    text = text.strip()
    if not text:
        return text
    return text[0].upper() + text[1:]


def get_spread_meanings(card_name, topic_key):
    card = TAROT_DECK[card_name]
    if 'spreads' in card and topic_key in card['spreads']:
        return card['spreads'][topic_key]
    essence = card['essence'][topic_key]
    return [
        f'энергия карты говорит о том, что важна тема: {essence}',
        f'в этой позиции проявляется {essence}',
        f'итог склоняется к тому, что ключевое значение — {essence}',
    ]


def get_main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(types.KeyboardButton(CARD_BUTTON))
    markup.row(types.KeyboardButton(REDRAW_BUTTON))
    markup.row(
        types.KeyboardButton('💕 Любовь'),
        types.KeyboardButton('🤝 Дружба'),
    )
    markup.row(
        types.KeyboardButton('💼 Карьера'),
        types.KeyboardButton('💰 Финансы'),
    )
    return markup


def today_str():
    return str(datetime.date.today())


def can_draw_card(user_id):
    today = today_str()
    if users_history.get(user_id) != today:
        return True
    return users_extra_draw.get(user_id, False)


def normalize_answer(text):
    text = text.strip().lower().replace('ё', 'е')
    text = re.sub(r'[^\w\d]+', '', text, flags=re.UNICODE)
    return text


def pick_random_question():
    item = random.choice(TRIVIA_QUESTIONS)
    answers = {normalize_answer(a) for a in item['answers']}
    return item['question'], answers


def start_redraw_quiz(chat_id):
    if users_quiz.get(chat_id):
        bot.send_message(
            chat_id,
            '❓ Ты уже отвечаешь на вопрос выше. Напиши *одним словом*.',
            parse_mode='Markdown',
        )
        return

    today = today_str()
    if users_history.get(chat_id) != today:
        bot.send_message(chat_id, '🃏 Сначала вытяни карту дня — потом сможешь попытаться перевытянуть.')
        return

    if users_extra_draw.get(chat_id, False):
        bot.send_message(chat_id, '✨ У тебя уже есть дополнительная попытка! Жми «🃏 Карта дня».')
        return

    question, answers = pick_random_question()
    users_quiz[chat_id] = answers
    bot.send_message(
        chat_id,
        f'🧠 Чтобы перевытянуть карту, ответь *одним словом*:\n\n{question}',
        parse_mode='Markdown',
    )


def handle_quiz_answer(message):
    chat_id = message.chat.id
    expected = users_quiz.get(chat_id)
    if not expected:
        return False

    raw = message.text.strip()
    if not raw or ' ' in raw:
        bot.send_message(chat_id, '⚠️ Ответ должен быть *одним словом* без пробелов.', parse_mode='Markdown')
        return True

    if normalize_answer(raw) in expected:
        users_quiz.pop(chat_id, None)
        users_extra_draw[chat_id] = True
        bot.send_message(
            chat_id,
            '✅ Верно! Карты довольны твоей эрудицией.\n'
            'Теперь жми «🃏 Карта дня» — у тебя есть ещё одна попытка.',
        )
    else:
        bot.send_message(
            chat_id,
            '❌ Неверно. Попробуй ещё раз — ответ всё ещё *одним словом*.',
            parse_mode='Markdown',
        )
    return True


def draw_random_cards(count=SPREAD_SIZE):
    return random.sample(list(TAROT_DECK.keys()), min(count, len(TAROT_DECK)))


def list_images():
    if not os.path.isdir(IMAGES_DIR):
        return []
    return [
        os.path.join(IMAGES_DIR, name)
        for name in os.listdir(IMAGES_DIR)
        if os.path.splitext(name.lower())[1] in IMAGE_EXTENSIONS
    ]


def send_random_photo(chat_id, caption=None):
    images = list_images()
    if not images:
        bot.send_message(chat_id, caption or 'В папке images пока нет картинок.')
        return

    image_path = random.choice(images)
    try:
        with open(image_path, 'rb') as photo:
            bot.send_photo(chat_id, photo, caption=caption)
    except OSError as e:
        print(f'❌ Ошибка чтения изображения {image_path}: {e}')
        bot.send_message(chat_id, caption or '')


def generate_spread_reading(topic_key, cards):
    topic = SPREAD_TOPICS[topic_key]
    meanings = [random.choice(get_spread_meanings(card, topic_key)) for card in cards]

    lines = [
        f"🔮 Расклад на {topic['title']}",
        f"Карты: {' · '.join(cards)}",
        "",
    ]

    for position, card, meaning in zip(topic['positions'], cards, meanings):
        lines.append(f"▫️ {position} — {card}")
        lines.append(f"   {capitalize_sentence(meaning)}.")
        lines.append("")

    synthesis = topic['synthesis'].format(
        cards=', '.join(cards),
        m1=meanings[0],
        m2=meanings[1],
        m3=meanings[2],
    )
    lines.append(f"✨ Общий посыл:\n{capitalize_sentence(synthesis)}")
    return '\n'.join(lines)


def spread_done_today(user_id, topic_key):
    return users_spreads.get(user_id, {}).get(topic_key) == today_str()


def mark_spread_done(user_id, topic_key):
    users_spreads.setdefault(user_id, {})[topic_key] = today_str()


def send_spread_limit_message(chat_id, topic_key):
    topic = SPREAD_TOPICS[topic_key]
    exercise = random.choice(WARMUP_EXERCISES)
    bot.send_message(
        chat_id,
        f'✨ Прости, но расклад на {topic["title"]} сегодня уже был — '
        f'перевытянуть получится только завтра 🌙\n\n'
        f'💪 Зато вот лёгкая зарядка от карт: *{exercise}*.\n'
        f'Сделай — и энергия точно не пропадёт зря!',
        parse_mode='Markdown',
    )


def send_spread(chat_id, topic_key):
    if spread_done_today(chat_id, topic_key):
        send_spread_limit_message(chat_id, topic_key)
        return

    cards = draw_random_cards()
    reading_text = generate_spread_reading(topic_key, cards)
    send_random_photo(chat_id, reading_text)
    mark_spread_done(chat_id, topic_key)


def handle_card_of_day(message):
    user_id = message.chat.id
    today = today_str()

    if not can_draw_card(user_id):
        bot.send_message(
            message.chat.id,
            '✨ Звёзды уже сказали своё слово на сегодня.\n\n'
            'Хочешь ещё одну карту? Нажми «🎲 Перевытянуть карту» и ответь на вопрос!',
        )
        return

    chosen_card = random.choice(list(TAROT_DECK.keys()))
    prediction = random.choice(TAROT_DECK[chosen_card]['predictions'])
    caption_text = f"Твоя карта: {chosen_card}\n\n{prediction}"

    send_random_photo(message.chat.id, caption_text)
    users_history[user_id] = today
    users_extra_draw[user_id] = False
    users_quiz.pop(user_id, None)


@bot.message_handler(commands=['start'])
def start_bot(message):
    bot.send_message(
        message.chat.id,
        "Привет! Я твой личный проводник в мир Таро.\n\n"
        "🃏 *Карта дня* — одно послание на сегодня.\n"
        "🎲 *Перевытянуть карту* — ответь на вопрос и получи ещё одну попытку.\n"
        "💕 🤝 💼 💰 *Расклады* — три карты по теме, каждый *раз в день*.\n\n"
        "Жми кнопку ниже!",
        reply_markup=get_main_menu(),
        parse_mode='Markdown',
    )


@bot.message_handler(content_types=['text'])
def handle_text(message):
    if message.text == CARD_BUTTON:
        try:
            handle_card_of_day(message)
        except Exception as e:
            print(f'❌ Ошибка карты дня: {e}')
        return

    if message.text == REDRAW_BUTTON:
        try:
            start_redraw_quiz(message.chat.id)
        except Exception as e:
            print(f'❌ Ошибка викторины: {e}')
        return

    topic_key = BUTTON_TO_TOPIC.get(message.text)
    if topic_key:
        try:
            send_spread(message.chat.id, topic_key)
        except Exception as e:
            print(f'❌ Ошибка расклада ({topic_key}): {e}')
        return

    if message.text not in MENU_BUTTONS:
        try:
            handle_quiz_answer(message)
        except Exception as e:
            print(f'❌ Ошибка ответа на викторину: {e}')


if __name__ == '__main__':
    found = len(list_images())
    print(f'Таро-Бот: картинок в images/ — {found}, вопросов — {len(TRIVIA_QUESTIONS)}')
    if TELEGRAM_PROXY:
        print(f'Прокси: {TELEGRAM_PROXY}')

    while True:
        try:
            print('Подключение к Telegram...')
            me = bot.get_me()
            print(f'Бот @{me.username} запущен. Жду сообщений...')
            bot.infinity_polling(
                timeout=60,
                long_polling_timeout=60,
                skip_pending=True,
                logger_level=40,
            )
        except KeyboardInterrupt:
            print('\nБот остановлен.')
            break
        except Exception as e:
            print(f'\n❌ Не удалось подключиться к Telegram: {e}')
            print('Проверь VPN и порт в файле .env:')
            print('TELEGRAM_PROXY=socks5h://127.0.0.1:2408')
            print('Или в PowerShell: $env:TELEGRAM_PROXY="socks5h://127.0.0.1:2408"')
            print('Повтор через 10 сек...\n')
            time.sleep(10)