# app/config.py

import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
CONFLUENCE_API_TOKEN = os.getenv("CONFLUENCE_API_TOKEN")
CONFLUENCE_USER = os.getenv("CONFLUENCE_USER")
CONFLUENCE_BASE_URL = os.getenv("CONFLUENCE_BASE_URL")
CONFLUENCE_PASSWORD = os.getenv("CONFLUENCE_PASSWORD")
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4") # gpt-3.5-turbo, gpt-3.5-turbo-16k, gpt-4-32k...
LLM_TEMPERATURE = os.getenv("LLM_TEMPERATURE", "0.2")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2") # 384
# EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/text-embedding-ada-002") # 1536
