"""Озвучка через Gemini, независимо от LLM агента и распознавания речи."""

from .client import TTSUnavailableError, speech_text, synthesize

__all__ = ["TTSUnavailableError", "speech_text", "synthesize"]
