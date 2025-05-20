FROM python:3.10-slim

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    iproute2 \
    iptables \
    wireguard \
    openresolv \
    curl \
    gnupg \
    net-tools \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Установка зависимостей Python
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем приложение
COPY ./app /app
COPY ./entrypoint.sh /entrypoint.sh

# Делаем entrypoint исполняемым
RUN chmod +x /entrypoint.sh

# Установка рабочей директории
WORKDIR /app

ENV PYTHONPATH=/

ENTRYPOINT ["/entrypoint.sh"]
