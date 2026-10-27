"""Pydantic-модели из docs/contracts/ — единое место, откуда их импортируют все модули.

from schemas import Record, ChatRequest, ActionResult
"""

from .actions import (
    ActionResult,
    AskUser,
    CreateRecord,
    Help,
    ListRecords,
    LLMAction,
    SearchFilters,
    SearchRecords,
    SetStatus,
    TargetRef,
    UndoLast,
    UpdateRecord,
)
from .api import ChatRequest, ChatResponse, LLMConfig, STTResponse
from .conversation import ConversationState, LastAction
from .record import Record, RecordStatus, RecordType
from .search import SearchHit, TargetMatch

__all__ = [
    "UpdateRecord",
    "UndoLast",
    "SetStatus",
    "STTResponse",
    "LastAction",
    "Help",
    "ActionResult",
    "AskUser",
    "ChatRequest",
    "ChatResponse",
    "ConversationState",
    "CreateRecord",
    "ListRecords",
    "LLMAction",
    "LLMConfig",
    "Record",
    "RecordStatus",
    "RecordType",
    "SearchFilters",
    "SearchHit",
    "SearchRecords",
    "TargetMatch",
    "TargetRef",
]
