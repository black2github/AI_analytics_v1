# 🔍 AI Requirements Analyzer (RAG + Confluence + LangChain + WireGuard)

FastAPI-сервис для анализа изменений в требованиях на основе Retrieval-Augmented Generation (RAG). Поддерживает интеграцию с Confluence, ChromaDB и WireGuard.

---

## 📦 Возможности

* 📄 Автоматическая загрузка требований по `pageId` из Confluence
* 🔍 Анализ новых требований в сравнении с платформенными ограничениями
* 🧠 Интеграция с OpenAI GPT и Anthropic Claude
* 🔗 LangChain RAG-пайплайн на базе ChromaDB
* 🧳 Поддержка WireGuard внутри контейнера
* 🚀 REST API-интерфейс

---

## 🚀 Быстрый старт

### 1. Клонируйте репозиторий

```bash
git clone https://github.com/black2github/AI_analytics_v1.git
cd AI_analytics_v1
```

### 2. Настройте `.env`

Создайте файл `.env` на основе примера:

```bash
cp .env.example .env
```

Измените значения переменных в соответствии с вашей конфигурацией.

### 3. Соберите и запустите контейнер

```bash
docker compose up --build
```

---

## ⚙️ Переменные окружения

| Переменная             | Описание                                                           |
| ---------------------- | ------------------------------------------------------------------ |
| `OPENAI_API_KEY`       | Ключ OpenAI API для GPT                                            |
| `CLAUDE_API_KEY`       | Ключ Anthropic Claude API                                          |
| `CONFLUENCE_BASE_URL`  | Базовый URL Confluence (например, `https://confluence.gboteam.ru`) |
| `CONFLUENCE_USER`      | Email Atlassian-аккаунта                                           |
| `CONFLUENCE_API_TOKEN` | API-токен Atlassian для доступа к Confluence                       |

> 🔐 [Создать токен Atlassian](https://id.atlassian.com/manage/api-tokens)

---

## 🧭 Структура проекта

```
.
├── app/
│   ├── __init__.py
│   ├── config.py                  # Конфигурация проекта и чтение переменных окружения
│   ├── confluence_loader.py      # Загрузка требований из Confluence по заданным pageId
│   ├── embedding_store.py        # Работа с векторным хранилищем Chroma (создание, загрузка, поиск)
│   ├── llm_interfaces.py         # Интерфейсы для взаимодействия с LLM (OpenAI GPT, Claude)
│   ├── rag_pipeline.py           # Основная логика цепочки RAG: генерация промпта, выбор контекста, вызов LLM
│   └── main.py                   # FastAPI-приложение и маршруты REST API
├── chroma_db/                    # Каталог с персистентным хранилищем Chroma (создаётся автоматически)
├── requirements.txt              # Зависимости Python-проекта
├── Dockerfile                    # Инструкция сборки Docker-образа
├── .dockerignore                 # Исключения для Docker-контекста
├── docker-compose.yml           # Компоновка контейнеров, включая WireGuard
├── .env                          # Переменные окружения (локально)
├── .env.example                  # Пример переменных окружения
└── README.md                     # Документация по установке и использованию

```
📄 Назначение файлов

📁 app/
__init__.py: позволяет использовать директорию app/ как модуль Python. Обычно пустой, но нужен для корректного импорта.
config.py: загружает переменные окружения через Pydantic. Используется всеми частями проекта.
confluence_loader.py: функции для подключения к API Confluence и загрузки содержания страниц по pageId. Поддерживает передачу множества страниц.
embedding_store.py: создаёт и управляет хранилищем Chroma DB, добавляет документы, ищет похожие элементы по вектору.
llm_interfaces.py: абстракции для вызова моделей OpenAI и Claude. Обеспечивает единый интерфейс взаимодействия с LLM.
rag_pipeline.py: организует цепочку RAG: загрузка контекста из Chroma, сборка промпта, вызов LLM и возврат результата.
main.py: точка входа FastAPI-приложения, маршруты /analyze, /load_platform, /load_service.

📁 chroma_db/
Содержит хранилище Chroma — создаётся автоматически при первом запуске, не требует ручного создания.

📄 Корень проекта
Dockerfile: создаёт образ, включая установку Python-зависимостей и WireGuard, запуск FastAPI.
.dockerignore: исключает лишние файлы из Docker-контекста (например, .env, __pycache__, *.log).
docker-compose.yml: запускает контейнер с сервисом и WireGuard, монтирует .env, пробрасывает порты.
.env: реальные переменные окружения (не добавляется в репозиторий).
.env.example: шаблон для .env, содержит описание всех нужных переменных.
requirements.txt: зависимости Python (LangChain, FastAPI, Chroma, OpenAI SDK и др.).
README.md: полная инструкция по запуску, переменным окружения, API-маршрутам, запуску в Docker.


---

## 📡 REST API

### 🔎 `POST /analyze`

Анализирует новое требование и возвращает вывод GPT/Claude.

#### Запрос:

```json
{
  "requirement": "Сервис должен отправлять SMS при каждой авторизации.",
  "top_k": 3,
  "model": "gpt"
}
```

#### Ответ:

```json
{
  "prompt": "Анализируй следующее требование: ...",
  "context": ["...", "..."],
  "analysis": "Это требование нарушает ... потому что ..."
}
```

---

### 🧠 `POST /load_platform_context`

Загрузка стабильных платформенных требований в векторное хранилище.

```json
{
  "documents": [
    {"id": "auth-1", "text": "Авторизация использует JWT с TTL 30 мин."},
    {"id": "acl-1", "text": "ACL реализован через справочник ролей"}
  ]
}
```

---

### 📥 `POST /load_service_pages`

Загрузка новых страниц сервиса в Chroma по списку `page_ids`.

```json
{
  "page_ids": [12345678, 87654321]
}
```

---

### 💬 `POST /analyze_service_pages`

Анализ требований из переданных `page_ids` с учетом платформенного контекста.

```json
{
  "page_ids": [12345678, 87654321],
  "model": "claude"
}
```

---

## 🛡️ WireGuard

WireGuard поднимается внутри контейнера. Убедитесь, что:

* У вас есть `.conf` файл для WireGuard в `wg/`
* Он называется `wg0.conf`

---

## 📑 Пример `.env.example`

```dotenv
OPENAI_API_KEY=sk-...
CLAUDE_API_KEY=sk-ant-...
CONFLUENCE_BASE_URL=https://confluence.gboteam.ru
CONFLUENCE_USER=your.name@example.com
CONFLUENCE_API_TOKEN=your-confluence-token
```

---

## 🐳 Docker-команды

```bash
# Сборка
docker compose build

# Запуск
docker compose up

# Остановка
docker compose down
```

---

## 🔗 Полезные ссылки

* [Atlassian API токены](https://id.atlassian.com/manage/api-tokens)
* [WireGuard документация](https://www.wireguard.com/)
* [LangChain](https://docs.langchain.com/)

---

## 🛠 TODO

* Авторизация в FastAPI
* Интерфейс загрузки требований через веб
* Интерфейс аннотации платформенных ограничений

---

