"""Лимит частоты запросов на одного пользователя — в памяти процесса (бэкенд один)."""

import time
from collections import deque
from collections.abc import Callable, Hashable


class RateLimiter:
    """Не больше `limit` запросов за скользящее окно `window` секунд на ключ."""

    def __init__(
        self, limit: int, window: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window = window
        self._clock = clock
        self._hits: dict[Hashable, deque[float]] = {}

    def hit(self, key: Hashable) -> float | None:
        """Учесть запрос. `None` — можно; число — через сколько секунд можно снова.

        Отклонённый запрос не учитывается: иначе частые повторы продлевали бы блокировку.
        """
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return max(hits[0] + self.window - now, 0.0)
        hits.append(now)
        if len(self._hits) > 10_000:
            self._forget_idle(now)
        return None

    def _forget_idle(self, now: float) -> None:
        """Убрать пользователей без запросов в окне — чтобы словарь не рос бесконечно."""
        idle = [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window]
        for key in idle:
            del self._hits[key]

    def reset(self) -> None:
        self._hits.clear()
