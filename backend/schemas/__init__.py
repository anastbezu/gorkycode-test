"""Pydantic-модели из docs/contracts/ — единое место, откуда их импортируют все модули.

    from schemas import Record, ChatRequest, ActionResult
"""

from .actions import (
    ActionResult,
    AskUser,
    CreateRecord,
    ListRecords,
    LLMAction,
    SearchFilters,
    SearchRecords,
    TargetRef,
)
from .api import ChatRequest, ChatResponse
from .conversation import ConversationState
from .record import Record, RecordStatus, RecordType
from .search import SearchHit

__all__ = [
    "ActionResult",
    "AskUser",
    "ChatRequest",
    "ChatResponse",
    "ConversationState",
    "CreateRecord",
    "ListRecords",
    "LLMAction",
    "Record",
    "RecordStatus",
    "RecordType",
    "SearchFilters",
    "SearchHit",
    "SearchRecords",
    "TargetRef",
]
