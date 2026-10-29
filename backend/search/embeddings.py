"""Модель эмбеддингов поиска: текст → вектор из 312 чисел (docs/modules/search.md).

Модель — `sergeyzh/rubert-mini-frida` (MIT), одна на сервере, от `llm_config` пользователя
не зависит. Запускается через sentence-transformers на PyTorch CPU: самый короткий путь
к модели в том виде, в каком её выпустил автор, без конвертации. Чтобы перейти
на другой рантайм (например, ONNX), достаточно поменять этот файл: снаружи видны только
`embed_queries()` / `embed_documents()` и `MODEL_KEY`.

Модель загружается при первом поиске «похожих», а не при старте приложения: уровню «точно»
она не нужна. В образе бэкенда файлы модели скачиваются при сборке (Dockerfile), в работе
сервер в сеть за ними не ходит.
"""

import threading

import numpy as np

MODEL_ID = "sergeyzh/rubert-mini-frida"
# Ревизия закреплена: новая версия модели дала бы другие векторы и другие пороги.
MODEL_REVISION = "32a82388a9f99c99eca74494731f7ee6e9a9fe3a"
# Ключ векторов в базе: при смене модели или ревизии старые векторы не смешиваются с новыми.
MODEL_KEY = f"{MODEL_ID}@{MODEL_REVISION[:8]}"

# Задачи frida: запрос и документ кодируются с разными префиксами — «search_query: » и
# «search_document: » (настройки модели, `config_sentence_transformers.json`). Префикс
# подставляет sentence-transformers по имени. Дописывать его к тексту руками нельзя: у модели
# префикс по умолчанию «categorize: », и текст ушёл бы как «categorize: search_query: …»
# (проверено 2026-10-27: так закодированные векторы дают другую шкалу сходства).
QUERY_PROMPT = "query"
DOCUMENT_PROMPT = "passage"


class ModelUnavailableError(RuntimeError):
    """Файлов модели нет локально, а скачивать их запрещено (офлайн)."""


_model = None
_model_lock = threading.Lock()


def _get_model():
    # Агент зовёт поиск из пула потоков (`asyncio.to_thread`): загрузка — один раз, под замком.
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                try:
                    _model = SentenceTransformer(
                        MODEL_ID, revision=MODEL_REVISION, device="cpu", local_files_only=True
                    )
                except OSError as exc:
                    raise ModelUnavailableError(
                        f"модели {MODEL_ID}@{MODEL_REVISION} нет в кэше Hugging Face: {exc}"
                    ) from exc
    return _model


def _encode(texts: list[str], prompt_name: str) -> np.ndarray:
    # normalize_embeddings: векторы длины 1, косинус = скалярное произведение.
    return _get_model().encode(
        texts, prompt_name=prompt_name, normalize_embeddings=True, convert_to_numpy=True
    )


def embed_queries(texts: list[str]) -> np.ndarray:
    return _encode(texts, QUERY_PROMPT)


def embed_documents(texts: list[str]) -> np.ndarray:
    return _encode(texts, DOCUMENT_PROMPT)
