# app/template_registry.py

from typing import Optional
from app.embedding_store import get_vectorstore, prepare_documents_for_index
from app.confluence_loader import load_pages_by_ids
from app.llm_interface import get_embeddings_model


def get_template_by_type(requirement_type: str) -> Optional[str]:
    embeddings_model = get_embeddings_model()
    store = get_vectorstore("requirement_templates", embedding_model=embeddings_model)
    matches = store.similarity_search("", filter={
        "type": "requirement_template",
        "requirement_type": requirement_type
    })
    if matches:
        return matches[0].page_content
    return None


def store_templates(templates: dict[str, str]) -> int:
    """
    Сохраняет шаблоны требований в коллекцию `requirement_templates`.

    :param templates: Словарь {requirement_type: page_id}
    :return: Количество успешно сохранённых шаблонов
    """
    # embeddings_model = get_embeddings_model()
    # store = get_vectorstore("requirement_templates", embedding_model=embeddings_model)
    store = get_vectorstore("requirement_templates")
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

    if docs_to_store:
        store.add_documents(docs_to_store)

    return len(docs_to_store)
