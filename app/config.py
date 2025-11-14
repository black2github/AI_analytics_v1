# app/config.py

import os
from dotenv import load_dotenv

load_dotenv()

APP_VERSION = os.getenv("APP_VERSION", "0.30.0")


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL")
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
KIMI_API_URL = os.getenv("KIMI_API_URL")
KIMI_API_KEY = os.getenv("KIMI_API_KEY")

CONFLUENCE_API_TOKEN = os.getenv("CONFLUENCE_API_TOKEN")
CONFLUENCE_USER = os.getenv("CONFLUENCE_USER")
CONFLUENCE_BASE_URL = os.getenv("CONFLUENCE_BASE_URL")
CONFLUENCE_PASSWORD = os.getenv("CONFLUENCE_PASSWORD")

# ДОБАВЛЯЕМ конфигурацию JIRA
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "https://jira.gboteam.ru")
JIRA_USER = os.getenv("JIRA_USER")
JIRA_PASSWORD = os.getenv("JIRA_PASSWORD")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")  # Альтернатива паролю

LLM_PROVIDER = os.getenv("LLM_PROVIDER")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4") # gpt-3.5-turbo, gpt-3.5-turbo-16k, gpt-4-32k...
LLM_TEMPERATURE = os.getenv("LLM_TEMPERATURE", "0.2")
LLM_CONTEXT_SIZE = 128000

# openai | huggingface
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "huggingface")
# EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/text-embedding-ada-002") # 1536
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2") # 384

CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma")

PAGE_ANALYSIS_PROMPT_FILE = os.getenv("PAGE_ANALYSIS_PROMPT_FILE", "page_prompt_template.txt")
TEMPLATE_ANALYSIS_PROMPT_FILE = os.getenv("TEMPLATE_ANALYSIS_PROMPT_FILE", "template-analysis-prompt.txt")

# Название единого хранилища
UNIFIED_STORAGE_NAME = "unified_requirements"

SERVICES_REGISTRY_FILE = os.getenv("SERVICES_REGISTRY_FILE", "services.json")
TEMPLATES_REGISTRY_FILE = os.getenv("TEMPLATES_REGISTRY_FILE", "templates.json")

PAGE_CACHE_TTL = int(os.getenv("PAGE_CACHE_TTL", "300"))  # по умолчанию 5 минут
PAGE_CACHE_SIZE = int(os.getenv("PAGE_CACHE_SIZE", "1000")) # по умолчанию 1000 странниц

# Chunking нужен, только если:
# - Страницы > 2-3k токенов
# - Используем маленькую LLM с малым контекстом
# - Нужен очень точный поиск специфичных деталей
# CHUNK_MODE: # "none", "fixed", "adaptive"
#   "none" - целые страницы,
#   "fixed" - разбиение на фрагменты,
#   "adaptive" - Целая страница + фрагменты с высоким overlap
#              Для точного поиска используем фрагменты
#              Для анализа подтягиваем целую страницу по page_id
CHUNK_MODE="none"
CHUNK_MAX_PAGE_SIZE=3000  # символов. Максимальный размер страницы, после которого она разбивается на чанки для адаптивной стратегии
CHUNK_SIZE=1500     # символов
CHUNK_OVERLAP=200   # символов