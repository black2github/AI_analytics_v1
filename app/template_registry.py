# app/template_registry.py

import logging
from typing import Optional
from app.embedding_store import get_vectorstore, prepare_documents_for_index
from app.confluence_loader import load_pages_by_ids
from app.llm_interface import get_embeddings_model

logger = logging.getLogger(__name__)  # Лучше использовать __name__ для именованных логгеров

def get_template_by_type(requirement_type: str) -> Optional[str]:
    logger.debug("[get_template_by_type] <- requirement type='%s'", requirement_type)
    embeddings_model = get_embeddings_model()
    store = get_vectorstore("requirement_templates", embedding_model=embeddings_model)
    filters = { "$and": [
                    {"type": {"$eq": "requirement_template"}},
                    {"requirement_type": {"$eq": requirement_type}}
                 ]
    }
    logger.debug("[get_template_by_type] filters='%s'", filters)
    matches = store.similarity_search("", filter=filters)

    if matches:
        logger.debug("[get_template_by_type] -> {%s}", matches[0].page_content)
        return matches[0].page_content
    logger.warning("[get_template_by_type] -> No template with type '%s'", requirement_type)
    return None


def store_templates(templates: dict[str, str]) -> int:
    """
    Сохраняет шаблоны требований в коллекцию `requirement_templates`.

    :param templates: Словарь {requirement_type: page_id}
    :return: Количество успешно сохранённых шаблонов
    """
    logger.debug("[store_templates] <- templates: %s", templates)

    embeddings_model = get_embeddings_model()
    store = get_vectorstore("requirement_templates", embedding_model=embeddings_model)
    docs_to_store = []

    for requirement_type, page_id in templates.items():
        pages = load_pages_by_ids([page_id])
        if not pages:
            continue

        page = pages[0]

        # Формируем документ для хранения
        doc = prepare_documents_for_index(
            [page],
            service_code=None,
            source="confluence",
            doc_type="requirement_template",
            enrich_with_type=False
        )[0]

        # Добавляем доп. атрибуты
        doc.metadata.update({
            "requirement_type": requirement_type,
            "page_id": page_id,
        })

        docs_to_store.append(doc)

    # TODO потеряно удаление предыдущих версий шаблонов

    if docs_to_store:
        store.add_documents(docs_to_store)

    logger.debug("[store_templates] -> stored %d documents", len(docs_to_store))
    return len(docs_to_store)

