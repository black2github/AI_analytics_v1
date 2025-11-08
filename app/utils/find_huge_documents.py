# app/utils/find_huge_documents.py

from app.config import UNIFIED_STORAGE_NAME
from app.embedding_store import get_vectorstore
from app.llm_interface import get_embeddings_model


# Скрипт для поиска проблемных документов
def find_huge_documents():
    """Находит и выводит информацию о больших документах"""
    embeddings_model = get_embeddings_model()
    store = get_vectorstore(UNIFIED_STORAGE_NAME, embedding_model=embeddings_model)

    data = store.get()

    huge_docs = []
    for doc_content, metadata in zip(data['documents'], data['metadatas']):
        size = len(doc_content)
        if size > 100000:  # > 100k символов
            huge_docs.append({
                'page_id': metadata.get('page_id'),
                'title': metadata.get('title'),
                'size': size,
                'service_code': metadata.get('service_code')
            })

    # Сортируем по размеру
    huge_docs.sort(key=lambda x: x['size'], reverse=True)

    print(f"\n Найдено {len(huge_docs)} огромных документов:\n")
    for doc in huge_docs[:10]:  # Топ-10
        print(f"Page ID: {doc['page_id']}")
        print(f"Title: {doc['title']}")
        print(f"Size: {doc['size']:,} chars (~{doc['size'] // 4:,} tokens)")
        print(f"Service: {doc['service_code']}")
        print("-" * 80)

    return huge_docs

huge_docs = find_huge_documents()