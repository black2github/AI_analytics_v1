FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Устанавливаем зависимости с явным указанием использовать CPU-версию torch
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt && \
    rm -rf /root/.cache/pip && \
    rm -rf /root/.cache/huggingface

COPY app /app
COPY store /app/store
COPY page_prompt_template.txt /app
COPY template_analysis_prompt.txt /app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]