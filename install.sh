#!/bin/bash
# Текстовый конвертер в аудио - скрипт установки
# Автоматически настраивает окружение для работы программы

set -e

echo "=== Text to Speech Converter - Установка ==="

# Определяем ОС
OS="$(uname -s)"
echo "Определена ОС: $OS"

# Установка основных зависимостей
install_system_deps() {
    echo "Установка системных зависимостей..."
    
    if command -v apt-get &> /dev/null; then
        # Debian/Ubuntu
        sudo apt-get update
        sudo apt-get install -y python3 python3-pip python3-venv ffmpeg libsox-fmt-mp3
    elif command -v dnf &> /dev/null; then
        # Fedora
        sudo dnf install -y python3 python3-pip ffmpeg
    elif command -v pacman &> /dev/null; then
        # Arch Linux / Manjaro
        sudo pacman -S --noconfirm python python-pip ffmpeg
    elif command -v brew &> /dev/null; then
        # macOS
        brew install python3 ffmpeg
    fi
}

# Создание виртуального окружения
create_venv() {
    echo "Создание виртуального окружения..."
    
    if [ -d "venv" ]; then
        echo "Виртуальное окружение уже существует"
        return
    fi
    
    python3 -m venv venv
    echo "Виртуальное окружение создано"
}

# Активация окружения
activate_venv() {
    echo "Активация виртуального окружения..."
    
    if [ "$OS" = "Darwin" ]; then
        source venv/bin/activate
    else
        source venv/bin/activate
    fi
}

# Установка Python зависимостей
install_python_deps() {
    echo "Установка Python зависимостей..."
    
    ./venv/bin/pip install --upgrade pip
    
    ./venv/bin/pip install -r requirements.txt
    
    echo "Python зависимости установлены"
}

# Основная функция установки
main() {
    # Установка системных зависимостей (опционально)
    if [ "$1" = "--with-system-deps" ]; then
        install_system_deps
    fi
    
    create_venv
    activate_venv
    install_python_deps
    
    echo ""
    echo "=== Установка завершена! ==="
    echo ""
    echo "Использование:"
    echo "  source venv/bin/activate"
    echo "  python tts_converter.py --gui"
    echo ""
    echo "Или для CLI:"
    echo "  source venv/bin/activate"
    echo "  python tts_converter.py -i book.txt -o output/ --split 30"
}

# Запуск
main "$@"