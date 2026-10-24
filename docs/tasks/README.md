# Задачи

Постановки задач от техлида. Одна задача — один файл — одна ветка — один PR.

Отдайте файл задачи своему AI-агенту вместе с [контрактами](../contracts/), описанием своего [модуля](../modules/) и [правилами работы](../dev-guide.md).

## Имя файла
`<модуль>-<номер>-<суть>.md`, латиницей через дефис:

```
agent-01-razbor-dat.md
search-01-indeks-embeddingov.md
backend-01-model-dannyh.md
```

Модули: `agent`, `search`, `backend`, `voice`, `frontend`, `devops`.

## Жизненный цикл
- Выданная постановка — запись: её не правят и не удаляют, даже когда задача сделана.
- Если задача изменилась — новый файл со следующим номером и ссылкой на прежний.
- Приоритеты, сроки и статусы здесь не ведутся.

## Текущие постановки задач

| Задача | Модуль | Исполнитель | Описание |
|---|---|---|---|
| [backend-01a](backend-01a-shema-bd.md) | `backend` | Денис | Схема базы данных, модели records / conversation_states и миграции Alembic |
| [backend-01b](backend-01b-import-dataset.md) | `backend` | Денис | Импорт и инициализация стартового датасета (1000 строк CSV) для нового пользователя |
| [backend-02a](backend-02a-servisy-zapisej.md) | `backend` | Денис | Сервисный слой записей (`create_record`, `list_records_for_period`) и состояния |
| [backend-02b](backend-02b-api-routes.md) | `backend` | Денис | Маршруты API FastAPI (`/api/chat`, `/api/items`, `X-User-Id`, Swagger `/docs`) |
| [agent-01](agent-01-prompty-i-shemy-tools.md) | `agent` | Давид | Компактный системный промпт (361 токен), схемы инструментов и опорные даты |
| [agent-02](agent-02-klient-llm-i-vyzov-tulov.md) | `agent` | Илья | Клиент OpenAI SDK по LLMConfig, принудительный tool calling и реестр ACTIONS |
| [agent-03](agent-03-slot-filling-i-kontekst.md) | `agent` | Давид | Слот-филлинг, слияние `pending_action`, 1 строка якоря и прямой путь через UI |
| [agent-04](agent-04-scenarii-spiska-i-poiska.md) | `agent` | Илья | Сценарии списков за период (`ListRecords`) и смыслового поиска (`SearchRecords`) |
| [product-01](product-01-makety-i-dizayn.md) | `product` | Маша | Макеты 3 экранов в Figma и дизайн-система |
| [devops-02](devops-02-deploy-prilozheniya-i-ci-cd.md) | `devops` | Настя | Автоматический деплой приложения при пуше в `develop` и CI/CD в GitHub Actions |

Новая задача создаётся по шаблону [`_template.md`](_template.md).
