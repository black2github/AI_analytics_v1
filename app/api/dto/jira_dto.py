# app/api/dto/jira_dto.py
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

class JiraTaskRequest(BaseModel):
    """Модель запроса для анализа задач Jira."""
    jira_task_ids: List[str]
    prompt_template: Optional[str] = None
    service_code: Optional[str] = None

class JiraTaskResponse(BaseModel):
    """Модель ответа с результатом анализа."""
    success: bool
    jira_task_ids: List[str]
    confluence_page_ids: List[str]
    total_pages_found: int
    analysis_results: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None

class JiraHealthResponse(BaseModel):
    """Модель ответа для проверки здоровья."""
    success: bool
    message: str
    endpoints: List[str]
    error: Optional[str] = None