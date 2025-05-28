# app/service_registry.py

import json
import os
from typing import List, Dict

SERVICE_REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "data", "services.json")


def load_services() -> List[Dict]:
    try:
        with open(SERVICE_REGISTRY_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Ошибка при чтении services.json: {e}")
        return []


def get_service_by_code(code: str) -> Dict:
    services = load_services()
    for service in services:
        if service["code"] == code:
            return service
    return {}


def get_platform_services() -> List[dict]:
    return [s for s in load_services() if s.get("platform") is True]


def is_valid_service(code: str) -> bool:
    return get_service_by_code(code) is not None


# Заглушка — заменить на авторизацию через текущего пользователя
def resolve_service_code_by_user() -> str:
    # TODO: интеграция с пользователем
    return "CC" # Default

def is_platform_service(service_code: str) -> bool:
    """
    Проверяет, является ли сервис платформенным по коду.
    Возвращает True, если найден и platform=true, иначе False.
    """
    services = load_services()
    for svc in services:
        if svc.get("code") == service_code:
            return svc.get("platform", False)
    return False

# Проверка, был ли page_id уже ранее сохранен в индекс и имеет ли привязанный сервис
def resolve_service_code_from_pages_or_user(page_ids: List[str]) -> str:
    from app.embedding_store import get_vectorstore

    store = get_vectorstore("service_pages")
    for pid in page_ids:
        matches = store.similarity_search("", filter={"page_id": pid})
        if matches:
            metadata = matches[0].metadata
            if "service_code" in metadata:
                return metadata["service_code"]

    return resolve_service_code_by_user()
