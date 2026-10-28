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

Модули: `agent`, `search`, `backend`, `voice`, `frontend`, `devops`, `product`, `calendar`.

## Жизненный цикл
- Выданная постановка — запись: её не правят и не удаляют, даже когда задача сделана.
- Если задача изменилась — новый файл со следующим номером и ссылкой на прежний.
- Задача выполнена (её результат работает в `develop`) — файл переносится в [`archive/`](archive/) без изменений текста, кроме относительных ссылок. Мелкий недоделанный пункт задачу не держит — он доделывается отдельно.
- Приоритеты, сроки и статусы здесь не ведутся.

## Текущие постановки задач

| Задача | Модуль | Исполнитель | Описание |
|---|---|---|---|
| [frontend-01](frontend-01-stranitsa-chata.md) | `frontend` | Ася | Страница чата и панель «Мои дела» на стенде: ответ и результат, пронумерованный список, перезагрузка, ошибки, настройки LLM, телефон |
| [agent-03](agent-03-slot-filling-i-kontekst.md) | `agent` | Давид | Слот-филлинг: черновик `pending` в состоянии разговора, ответ дополняет черновик без истории сообщений |
| [agent-05](agent-05-integratsiya-s-servisami-i-api.md) | `agent` | Илья | Агент на настоящих сервисах и в `/api/chat`: Сценарий 1 до PostgreSQL, проверка живого провайдера (продолжение agent-02) |
| [product-03](product-03-teksty-assistenta.md) | `product` | Маша | Тексты ассистента: один текст для чата и голоса, приведённый к принятым решениям, — `docs/assistant-texts.md` |
| [product-04](product-04-dorabotka-maketa.md) | `product` | Маша | Доработка макета: номера в списках и чипах, все виды результата, пустые состояния и ошибки, «Без срока», календарь, голос |
| [backend-03](backend-03-izmenenie-status-konflikty.md) | `backend` | Денис | Изменение и статус записей, конфликты, список без конца периода, новые поля состояния, один коммит на реплику |
| [agent-06](agent-06-sostoyanie-v-prompte.md) | `agent` | Давид | Состояние разговора в промпте, смена темы, отказ без LLM, правила дат (после agent-03) |
| [agent-07](agent-07-izmenenie-status-otkat.md) | `agent` | Илья | Изменить, выполнить, отменить, вернуть, «не эту, а ту», несколько команд, справка |
| [voice-01](voice-01-raspoznavanie-rechi.md) | `voice` | Денис | Распознавание речи на сервере: `POST /api/stt`, сначала Gemini, запись до 30 секунд, ошибки по кодам |
| [frontend-02](frontend-02-golos-na-stranitse.md) | `frontend` | Ася | Голос на странице: микрофон, запись, «распознаю», распознанный текст в ленте, озвучка ответа и выключение звука |
| [devops-03](devops-03-limit-zaprosa-nginx.md) | `devops` | Ася | Nginx на сервере пропускает голосовые записи: явный лимит размера запроса для `/api/stt` |
| [agent-08](agent-08-avtotest-agenta.md) | `agent` | Илья | Автотест агента по эталонным кейсам: в CI без модели, живой прогон через модель перед изменением промпта |
| [search-01](search-01-modul-poiska.md) | `search` | Родион | Модуль поиска: `search()` в два уровня («точно» и «похоже»), `find_target()` для цели изменения, векторы на текст, локальная модель |
| [agent-09](agent-09-tsel-i-pohozhie-cherez-poisk.md) | `agent` | Илья | Поправка к agent-07 и agent-04: цель изменения через `find_target()`, ответ «точно не нашёл, похожие» |
| [product-05](product-05-makety-vhod-i-upravlenie.md) | `product` | Маша | Макеты: вход и учётки, действия с записями в карточке и календаре, подключение календаря; `features.md` |
| [backend-04](backend-04-uchetki-i-vhod.md) | `backend` | Денис | Учётки и вход по токену, гость пустой, демо-учётки с датасетом и сброс, срок хранения 30 дней |
| [backend-05](backend-05-zapisi-iz-interfeysa.md) | `backend` | Давид | Записи из интерфейса без LLM: создать, перенести, выполнено, удалить и вернуть; сброс `last_action` |
| [frontend-04](frontend-04-vhod-na-stranitse.md) | `frontend` | Ася | Вход на странице: гость по умолчанию, учётка по желанию, 401 → гость |
| [frontend-05](frontend-05-deystviya-s-zapisyami.md) | `frontend` | Ася | Кнопки в карточке, «Моих делах» и календаре: создать, перенести, выполнено, удалить с «Вернуть» |
| [voice-02](voice-02-neyrosetevaya-ozvuchka.md) | `voice` | Давид | Нейросетевая озвучка: сравнение сервисов → выбор техлида → `POST /api/tts`, браузер — запасной |
| [calendar-01](calendar-01-vneshniy-kalendar.md) | `calendar` | Илья | Google Календарь у учётки: наши функции синхронизируют, правда в нашей базе; API или MCP — выбор исполнителя |

## Архив — выполненные задачи

| Задача | Модуль | Исполнитель | Описание |
|---|---|---|---|
| [devops-01](archive/devops-01-nastroyka-servera.md) | `devops` | Ася | Сервер `gorky.bond`: HTTPS, защита, Docker |
| [devops-02](archive/devops-02-deploy-prilozheniya-i-ci-cd.md) | `devops` | Ася | Автоматический деплой приложения при пуше в `develop` и CI/CD в GitHub Actions |
| [backend-01a](archive/backend-01a-shema-bd.md) | `backend` | Денис | Схема базы данных, модели records / conversation_states и миграции Alembic |
| [backend-01b](archive/backend-01b-import-dataset.md) | `backend` | Денис | Импорт и инициализация стартового датасета (1000 строк CSV) для нового пользователя |
| [backend-02a](archive/backend-02a-servisy-zapisej.md) | `backend` | Денис | Сервисный слой записей (`create_record`, `list_records_for_period`) и состояния |
| [backend-02b](archive/backend-02b-api-routes.md) | `backend` | Денис | Маршруты API FastAPI (`/api/chat`, `/api/items`, `X-User-Id`, Swagger `/docs`) |
| [agent-01](archive/agent-01-prompty-i-shemy-tools.md) | `agent` | Давид | Компактный системный промпт (361 токен), схемы инструментов и опорные даты |
| [agent-02](archive/agent-02-klient-llm-i-vyzov-tulov.md) | `agent` | Илья | Клиент OpenAI SDK по LLMConfig, принудительный tool calling и реестр ACTIONS; оставшиеся критерии перешли в agent-05 |
| [agent-04](archive/agent-04-scenarii-spiska-i-poiska.md) | `agent` | Илья | Сценарии списков за период (`ListRecords`) и смыслового поиска (`SearchRecords`) |

Новая задача создаётся по шаблону [`_template.md`](_template.md).
