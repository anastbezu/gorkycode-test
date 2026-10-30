# Набор `status`

выполнено / отменено / вернуть, массовые, «не эту, а ту». Модель агента `gemini-3.5-flash-lite`. Общий отчёт — [report.md](report.md).

| Метрика | Значение |
|---|---|
| Пройдено кейсов | 44/50 = 88.0% |
| Выбор инструмента, macro-F1 | 0.894 |
| Время реплики, медиана / 95-й процентиль | 1.13 с / 1.57 с |
| Не прогонялись (проверка в интерфейсе или другим набором) | 0 |

## По категориям

| Категория | Пройдено |
|---|---|
| вид статуса | 8/10 = 80.0% |
| массовая смена | 9/10 = 90.0% |
| не эту а ту | 3/5 = 60.0% |
| синонимы | 4/5 = 80.0% |
| цель её | 6/6 = 100.0% |
| цель по номеру | 6/6 = 100.0% |
| цель по описанию | 8/8 = 100.0% |

## Выбор инструмента

| Инструмент | Precision | Recall | F1 | Реплик |
|---|---|---|---|---|
| `create_record` | 1.000 | 1.000 | 1.000 | 3 |
| `list_records` | 1.000 | 1.000 | 1.000 | 9 |
| `none` | 1.000 | 1.000 | 1.000 | 1 |
| `set_status` | 1.000 | 0.935 | 0.967 | 62 |
| `undo_last` | 1.000 | 1.000 | 1.000 | 1 |
| `update_record` | 0.250 | 1.000 | 0.400 | 1 |

`none` — модель ничего не вызвала или код ответил без модели (отказ «не надо»).

## Поля вызова

| Поле | Верно |
|---|---|
| ждёт ответа | 62/66 = 93.9% |
| исполнено | 62/67 = 92.5% |
| «не этот, а тот» | 3/5 = 60.0% |
| начало (и «время названо») | 2/2 = 100.0% |
| новый статус | 56/61 = 91.8% |
| цель: «все» | 9/10 = 90.0% |
| цель: «её» | 7/7 = 100.0% |
| цель: номер | 10/10 = 100.0% |
| цель: описание | 28/31 = 90.3% |
| название | 3/3 = 100.0% |
| тип записи | 3/3 = 100.0% |

Неверный инструмент — поля засчитаны неверными.

## Ошибки (6)

- **st.2** (вид статуса) — «Готово, смету отправил»
  - ожидалось: `{"action": "set_status", "status": "done", "target_text": ["смет"], "ok": true, "awaiting": "none"}`
  - вызвано: `action=search_records, query=смету, filters={'types': [<RecordType.TASK: 'task'>, <RecordType.REMINDER: 'reminder'>], 'status': [<RecordStatus.ACTIVE: 'active'>]}`
  - действие: ожидалось set_status, получено search_records
- **st.7** (вид статуса) — «Нет, не сделал, верни её в активные»
  - ожидалось: `{"action": "set_status", "status": "active", "target_focus": true, "ok": true, "awaiting": "none"}`
  - вызвано: `action=set_status, target={'focus': True, 'all': False}, status=done, replaces_last=True`
  - status: ожидалось active, получено done
- **st.33** (массовая смена) — «Очисти завтрашний день»
  - ожидалось: `{"action": "set_status", "status": "cancelled", "target_all": true, "ok": false, "awaiting": "confirm"}`
  - вызвано: `action=update_record, target={'focus': False, 'filters': {'date_from': datetime.datetime(2026, 10, 22, 0, 0, tzinfo=TzInfo(10800)), 'date_to': datetime.datetime(2026, 10, 23, 0, 0, tzinfo=TzInfo(10800))}, 'all': True}, title=cancelled, replaces_last=False`
  - действие: ожидалось set_status, получено update_record
- **st.44** (не эту а ту) — «Ой, не с Ярославом, а с Ростиславом»
  - ожидалось: `{"action": "set_status", "status": "cancelled", "replaces_last": true, "target_text": ["Ростислав"], "ok": true, "awaiting": "none"}`
  - вызвано: `action=update_record, target={'focus': True, 'all': False}, title=Встреча с Ростиславом, replaces_last=True`
  - действие: ожидалось set_status, получено update_record
- **st.45** (не эту а ту) — «Нет, я Григорию позвонил, не Георгию»
  - ожидалось: `{"action": "set_status", "status": "done", "replaces_last": true, "target_text": ["Григор"], "ok": true, "awaiting": "none"}`
  - вызвано: `action=update_record, target={'focus': True, 'all': False}, title=Позвонить Григорию, replaces_last=True`
  - действие: ожидалось set_status, получено update_record
- **st.47** (синонимы) — «Закрой задачу про печать»
  - ожидалось: `{"action": "set_status", "status": "done", "target_text": ["печат"], "ok": true, "awaiting": "none"}`
  - вызвано: `action=set_status, target={'focus': False, 'text': 'печать', 'all': False}, status=done, replaces_last=False`
  - исполнение: ожидалось ok=True, получено False

