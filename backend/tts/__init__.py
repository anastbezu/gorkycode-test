"""Озвучка через Gemini, независимо от LLM агента и распознавания речи."""

from .client import TTSUnavailableError, synthesize

__all__ = ["TTSUnavailableError", "synthesize"]
