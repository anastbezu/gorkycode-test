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
- Задача выполнена (её результат работает в `develop`) — файл переносится в [`archive/`](archive/) без изменений текста, кроме относительных ссылок. Мелкий недоделанный пункт задачу не держит — он доделывается отдельно.
- Приоритеты, сроки и статусы здесь не ведутся.

## Текущие постановки задач

| Задача | Модуль | Исполнитель | Описание |
|---|---|---|---|
| [agent-03](agent-03-slot-filling-i-kontekst.md) | `agent` | Давид | Слот-филлинг: черновик `pending` в состоянии разговора, ответ дополняет черновик без истории сообщений |
| [agent-04](agent-04-scenarii-spiska-i-poiska.md) | `agent` | Илья | Сценарии списков за период (`ListRecords`) и смыслового поиска (`SearchRecords`) |
| [agent-05](agent-05-integratsiya-s-servisami-i-api.md) | `agent` | Илья | Агент на настоящих сервисах и в `/api/chat`: Сценарий 1 до PostgreSQL, проверка живого провайдера (продолжение agent-02) |
| [product-03](product-03-teksty-assistenta.md) | `product` | Маша | Тексты ассистента: один текст для чата и голоса, приведённый к принятым решениям, — `docs/assistant-texts.md` |
| [product-04](product-04-dorabotka-maketa.md) | `product` | Маша | Доработка макета: номера в списках и чипах, все виды результата, пустые состояния и ошибки, «Без срока», календарь, голос |

## Архив — выполненные задачи

| Задача | Модуль | Исполнитель | Описание |
|---|---|---|---|
| [devops-01](archive/devops-01-nastroyka-servera.md) | `devops` | Настя | Сервер `gorky.bond`: HTTPS, защита, Docker |
| [devops-02](archive/devops-02-deploy-prilozheniya-i-ci-cd.md) | `devops` | Настя | Автоматический деплой приложения при пуше в `develop` и CI/CD в GitHub Actions |
| [backend-01a](archive/backend-01a-shema-bd.md) | `backend` | Денис | Схема базы данных, модели records / conversation_states и миграции Alembic |
| [backend-01b](archive/backend-01b-import-dataset.md) | `backend` | Денис | Импорт и инициализация стартового датасета (1000 строк CSV) для нового пользователя |
| [backend-02a](archive/backend-02a-servisy-zapisej.md) | `backend` | Денис | Сервисный слой записей (`create_record`, `list_records_for_period`) и состояния |
| [backend-02b](archive/backend-02b-api-routes.md) | `backend` | Денис | Маршруты API FastAPI (`/api/chat`, `/api/items`, `X-User-Id`, Swagger `/docs`) |
| [agent-01](archive/agent-01-prompty-i-shemy-tools.md) | `agent` | Давид | Компактный системный промпт (361 токен), схемы инструментов и опорные даты |
| [agent-02](archive/agent-02-klient-llm-i-vyzov-tulov.md) | `agent` | Илья | Клиент OpenAI SDK по LLMConfig, принудительный tool calling и реестр ACTIONS; оставшиеся критерии перешли в agent-05 |
| [backend-03](backend-03-izmenenie-status-konflikty.md) | `backend` | Денис | Изменение и статус записей, конфликты, список без конца периода, новые поля состояния, один коммит на реплику |
| [agent-06](agent-06-sostoyanie-v-prompte.md) | `agent` | Давид | Состояние разговора в промпте, смена темы, отказ без LLM, правила дат (после agent-03) |
| [agent-07](agent-07-izmenenie-status-otkat.md) | `agent` | Илья | Изменить, выполнить, отменить, вернуть, «не эту, а ту», несколько команд, справка |

Новая задача создаётся по шаблону [`_template.md`](_template.md).
