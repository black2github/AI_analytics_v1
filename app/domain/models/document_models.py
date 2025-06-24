# app/domain/models/document_models.py
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from enum import Enum

class DocumentType(Enum):
    REQUIREMENT = "requirement"
    TEMPLATE = "template"

@dataclass
class LoadResult:
    success: bool
    total_pages: int
    pages_with_approved_content: int
    documents_created: int
    is_platform: bool
    storage: str
    message: str
    error: Optional[str] = None

@dataclass
class RemovalResult:
    success: bool
    deleted_count: int
    page_ids: List[str]
    storage: str
    error: Optional[str] = None

@dataclass
class ChildPagesResult:
    page_ids: List[str]
    load_result: Optional[LoadResult] = None

@dataclass
class DebugInfo:
    storage_name: str
    total_documents: int
    doc_type_stats: Dict[str, int]
    platform_stats: Dict[str, int]
    service_stats: Dict[str, int]
    sample_metadata: List[Dict[str, Any]]
    status: str