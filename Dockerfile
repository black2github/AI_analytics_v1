FROM python:3.10-slim

WORKDIR /app

# Системные зависимости (кешируется отдельно)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Копируем requirements рано, чтобы кешировать установку зависимостей
COPY requirements.txt .

# Обновляем pip (кешируется отдельно)
RUN pip install --no-cache-dir --upgrade pip

# Устанавливаем зависимости с CPU-версией torch
# Если упадет здесь, следующий запуск продолжит отсюда
# Увеличиваем таймауты для pip
ENV PIP_DEFAULT_TIMEOUT=100

RUN pip install --no-cache-dir \
    --timeout 100 \
    --retries 5 \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt

# Очистка (быстрая операция)
RUN rm -rf /root/.cache/pip && \
    rm -rf /root/.cache/huggingface

# Копируем код приложения в конце (не влияет на кеш зависимостей)
COPY app /app
COPY store /app/store
COPY page_prompt_template.txt /app
COPY template_analysis_prompt.txt /app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]