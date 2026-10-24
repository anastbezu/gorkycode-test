# Контракт: поиск

Граница: поиск (Родион) ↔ агент (Давид). Типы — `data-model.md`, `SearchFilters` — `agent-tools.md`.

```python
from uuid import UUID
from pydantic import BaseModel

class SearchHit(BaseModel):
    record: Record
    score: float

def search(user_id: UUID, query: str, filters: SearchFilters,
           limit: int = 10) -> list[SearchHit]: ...
```

## Правила
- Фильтры (пользователь, тип, даты, статус) применяются до смыслового поиска; по смыслу ищется только `query`.
- Интервал дат необязателен: «когда-то ставил задачу» — без дат.
- Результатов не больше `limit`, ниже порога похожести — не возвращаются. Пустой список — «ничего не нашлось».
- Одинаковые тексты с разными датами — разные записи.
