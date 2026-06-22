# Reputation Telegram Bot

Telegram-бот на aiogram 3 для репутации в групповых чатах.

## Возможности

- `/rep` ответом на сообщение: добавить пользователю +1 репутации.
- `/repdis` ответом на сообщение: добавить пользователю -1 репутации.
- `/repinfo`: посмотреть свою репутацию или репутацию пользователя, если команда отправлена ответом.
- `/reptop`: топ пользователей в текущем чате.
- Логирование чатов, пользователей и сообщений в PostgreSQL/Supabase.
- Защита от повторного голосования за одного и того же пользователя в одном чате.

## Локальный запуск

1. Создай виртуальное окружение:

```bash
python -m venv .venv
```

2. Активируй окружение:

```bash
.venv\Scripts\activate
```

3. Установи зависимости:

```bash
pip install -r requirements.txt
```

4. Создай `.env` по примеру `.env.example`:

```env
BOT_TOKEN=your_telegram_bot_token
SUPABASE_URI=postgresql://user:password@host:5432/database
```

5. Запусти бота:

```bash
python bot.py
```

## Настройка Telegram

В BotFather желательно отключить privacy mode:

```text
/setprivacy -> выбрать бота -> Disable
```

Так бот сможет видеть команды в группах.

## Деплой на Render

Проект подготовлен для Render Web Service. Это позволяет использовать Free instance.
Бот продолжает работать через Telegram polling, а встроенный HTTP endpoint нужен Render для проверки порта.

1. Залей репозиторий на GitHub.
2. Создай новый Web Service на Render.
3. Укажи команду запуска:

```bash
python bot.py
```

4. Добавь переменные окружения:

```env
BOT_TOKEN=...
SUPABASE_URI=...
```

5. После деплоя проверь логи Render: бот должен вывести сообщение о запуске.

Health endpoints:

- `/`
- `/health`

## Безопасность

Не коммить `.env`, токены Telegram и строку подключения к базе. Если секреты уже попадали в код, перевыпусти токен в BotFather и пароль базы в Supabase.
