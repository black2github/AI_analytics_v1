# app/api/dto/analyze_dto.py
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Union

class AnalyzeTextRequest(BaseModel):
    text: str
    prompt_template: Optional[str] = None
    service_code: Optional[str] = None

class AnalyzeTextResponse(BaseModel):
    result: Optional[str] = None
    error: Optional[str] = None

class AnalyzePagesRequest(BaseModel):
    page_ids: List[str]
    prompt_template: Optional[str] = None
    service_code: Optional[str] = None

class PageAnalysisResult(BaseModel):
    page_id: str
    analysis: Union[str, Dict[str, Any]]

class AnalyzePagesResponse(BaseModel):
    results: Optional[List[PageAnalysisResult]] = None
    error: Optional[str] = None

class AnalyzeWithTemplatesRequest(BaseModel):
    items: List[dict]  # Each item: {"requirement_type": str, "page_id": str}
    prompt_template: Optional[str] = None
    service_code: Optional[str] = None

class TemplateAnalysisResult(BaseModel):
    page_id: str
    requirement_type: str
    template_analysis: Dict[str, Any]
    legacy_formatting_issues: List[str]
    template_used: Optional[str] = None
    analysis_timestamp: Optional[float] = None
    storage_used: Optional[str] = None

class AnalyzeWithTemplatesResponse(BaseModel):
    results: Optional[List[TemplateAnalysisResult]] = None
    error: Optional[str] = None

class AnalyzeServicePagesRequest(BaseModel):
    page_ids: List[str]
    prompt_template: Optional[str] = None