#!/bin/bash
# Запуск бота в собственной группе процессов с trap на graceful shutdown.
# Ctrl+C или SIGTERM завершает всё дерево процессов (бот + ollama serve).

set -e

# Каталог проекта (скрипт должен запускаться из корня репозитория)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Активация виртуального окружения
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "Ошибка: .venv не найден. Создайте виртуальное окружение:"
    echo "  python -m venv .venv"
    echo "  source .venv/bin/activate"
    echo "  pip install -r requirements.txt"
    exit 1
fi

# Опции
START_OLLAMA="${START_OLLAMA:-true}"  # запускать ollama serve вместе с ботом
CHANNEL="${CHANNEL:-telegram}"         # telegram | max | console

# Функция graceful shutdown
shutdown() {
    echo "Получен сигнал завершения, останавливаю все процессы..."
    # Убиваем всю группу процессов (включая ollama serve, если запущен)
    kill -- -$$ 2>/dev/null || true
    exit 0
}

# Trap на SIGINT (Ctrl+C) и SIGTERM
trap shutdown SIGINT SIGTERM

# Запуск ollama serve (если включено)
if [ "$START_OLLAMA" = "true" ]; then
    echo "Запуск Ollama..."
    ollama serve &
    OLLAMA_PID=$!
    # Дать Ollama время на старт
    sleep 2
fi

# Запуск бота в зависимости от канала
case "$CHANNEL" in
    telegram)
        echo "Запуск Telegram-бота..."
        python -m app
        ;;
    max)
        echo "Запуск MAX-бота..."
        python -m app.max_main
        ;;
    console)
        echo "Запуск консольного режима..."
        python -m app.console_main
        ;;
    *)
        echo "Ошибка: неизвестный канал '$CHANNEL'. Допустимые значения: telegram, max, console"
        exit 1
        ;;
esac
