# app/api/dto/loader_dto.py
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

class LoadPagesRequest(BaseModel):
    page_ids: List[str]
    service_code: Optional[str] = None
    source: str = "DBOCORPESPLN"

class LoadPagesResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    total_pages: Optional[int] = None
    pages_with_approved_content: Optional[int] = None
    documents_created: Optional[int] = None
    is_platform: Optional[bool] = None
    storage: str
    error: Optional[str] = None

class LoadTemplatesRequest(BaseModel):
    templates: Dict[str, str]  # {requirement_type: page_id}

class LoadTemplatesResponse(BaseModel):
    message: Optional[str] = None
    templates_loaded: Optional[int] = None
    storage: str
    error: Optional[str] = None

class RemovePagesRequest(BaseModel):
    page_ids: List[str]
    service_code: Optional[str] = None

class RemovePagesResponse(BaseModel):
    status: str
    deleted_count: Optional[int] = None
    page_ids: List[str]
    storage: str
    error: Optional[str] = None

class ChildPagesResponse(BaseModel):
    page_ids: Optional[List[str]] = None
    load_result: Optional[LoadPagesResponse] = None
    storage: str
    error: Optional[str] = None

class DebugResponse(BaseModel):
    storage_name: Optional[str] = None
    total_documents: Optional[int] = None
    doc_type_stats: Optional[Dict[str, int]] = None
    platform_stats: Optional[Dict[str, int]] = None
    service_stats: Optional[Dict[str, int]] = None
    sample_metadata: Optional[List[Dict[str, Any]]] = None
    status: Optional[str] = None
    error: Optional[str] = None