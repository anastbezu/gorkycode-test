# Контракт: поиск

Граница: поиск (Родион) ↔ агент (Илья, Давид). Типы — `data-model.md`, `SearchFilters` — `agent-tools.md`.

```python
from uuid import UUID
from pydantic import BaseModel
from sqlalchemy.orm import Session

class SearchHit(BaseModel):
    record: Record
    score: float

def search(db: Session, user_id: UUID, query: str, filters: SearchFilters,
           limit: int = 10) -> list[SearchHit]: ...
```

## Правила
- Синхронная, как сервисы записей: сессию БД передаёт вызывающий первым аргументом, транзакцией управляет он. Агент вызывает `search()` через `asyncio.to_thread` (`docs/decisions.md`, «Доступ к БД»).
- Фильтры (пользователь, тип, даты, статус) применяются до смыслового поиска; по смыслу ищется только `query`.
- Интервал дат необязателен: «когда-то ставил задачу» — без дат.
- Результатов не больше `limit`, ниже порога похожести — не возвращаются. Пустой список — «ничего не нашлось».
- Одинаковые тексты с разными датами — разные записи.
