# REST API для меню ресторана

Стек:

```FastAPI```
```PostgreSQL```
```Docker```
```Pytest```
```Redis```
```Celery```
```RabbitMQ```

Асинхронное приложение по работе с меню ресторана. Реализованы 3 сущности: Меню, Подменю, Блюдо.
Зависимости:
+ У меню есть подменю
+ В подменю есть блюда

Реализовано кэширование, в качестве кэш-хранилища используется Redis.

Выгрузка меню в excel — надёжное фоновое задание (Celery + RabbitMQ + transactional outbox в PostgreSQL), см. раздел «Фоновые задания».

#### Запустить приложение
```
cp .env.example .env   # и задать свои пароли
docker-compose up -d
```
Процессы: `web` (API), `dispatcher` (outbox + сверка), `celery` (worker), `db`, `redis`, `rabbitmq`.

#### Запустить тесты
```
docker-compose -f docker-compose.tests.yml up --build --abort-on-container-exit --exit-code-from test_app
```
Тесты идут на реальном PostgreSQL (`test_db`), схема создаётся из моделей.
Документация доступна по адресу ```http://127.0.0.1:8000/docs```

### Data Dump
+ **POST**   ```/api/v1/dump``` наполнение базы готовыми данными

### Report (совместимый API, работает поверх `jobs`)
+ **POST**   ```/api/v1/report``` запрос для генерации отчета в формате xlsx
+ **GET**   ```/api/v1/report/{task_id}``` запрос статуса задачи (`200`, когда отчёт готов, иначе `425`)
+ **GET**   ```/api/v1/report/{task_id}/download``` скачивание отчета

### Jobs
+ **POST**   ```/api/v1/jobs``` тело `{"kind":"menu_report"}`; `202`, заголовок `Location`
+ **GET**   ```/api/v1/jobs/{id}``` состояние, `attempts`, `max_attempts`, код и безопасное описание ошибки
+ **GET**   ```/api/v1/jobs?status=failed&limit=20&offset=0``` список метаданных (`limit` ≤ 100)
+ **GET**   ```/api/v1/jobs/{id}/result``` XLSX `menu-report-{id}.xlsx`; `404` — нет задания, `409` — результата ещё нет

### Menus
+ **POST**   ```/api/v1/menus```создание меню
+ **GET** ```/api/v1/menus``` просмотр списка меню
+ **PATCH** ```/api/v1/menus/{menu_id}``` обновление меню
+ **GET**    ```/api/v1/menus/{menu_id}```просмотр определенного меню
+ **DELETE**  ```/api/v1/menus/{menu_id}``` удаление меню

### Submenus
+ **POST** ```/api/v1/menus/{menu_id}/submenus/``` создание подменю
+ **GET**  ```/api/v1/menus/{menu_id}/submenus/``` просмотр списка подменю
+ **PATCH** ```/api/v1/menus/{menu_id}/submenus/{submenu_id}``` обновление подменю
+ **GET**  ```/api/v1/menus/{menu_id}/submenus/{submenu_id}``` просмотр определенного подменю
+ **DELETE** ```/api/v1/menus/{menu_id}/submenus/{submenu_id}``` удаление подменю

### Dishes
+ **POST** ```/api/v1/menus/{menu_id}/submenus/{submenu_id}/dishes``` создание блюда
+ **GET**   ```/api/v1/menus/{menu_id}/submenus/{submenu_id}/dishes``` просмотр списка блюд
+ **PATCH** ```/api/v1/menus/{menu_id}/submenus/{submenu_id}/dishes/{dish_id}``` обновление блюда
+ **GET**   ```/api/v1/menus/{menu_id}/submenus/{submenu_id}/dishes/{dish_id}``` просмотр определенного блюда
+ **DELETE** ```/api/v1/menus/{menu_id}/submenus/{submenu_id}/dishes/{dish_id}``` удаление блюда

## Фоновые задания

Дизайн: [docs/superpowers/specs/2026-10-03-reliable-jobs-design.md](docs/superpowers/specs/2026-10-03-reliable-jobs-design.md).

Состояния: `queued → running → succeeded`; при ошибке `retry_wait` (до 3 попыток, задержки 5 и 30 с) и `failed`.

+ Приём: снимок меню, запись в `jobs` и событие в `outbox` фиксируются одной транзакцией; `202` не зависит от RabbitMQ.
+ `dispatcher` публикует события с publisher confirms и `mandatory`; строка отмечается отправленной только после подтверждения брокера. Каждые 10 с он же восстанавливает задания с истёкшим владением и неподхваченные события.
+ Worker получает только `job_id`, номер попытки и ID события; состояние и результат (XLSX, SHA-256) хранятся в PostgreSQL. Результат и переход в `succeeded` — одна транзакция под токеном владения, поэтому повторная доставка не создаёт второй результат.
+ Терминальные ошибки пишутся в очередь `jobs.failed` (событие с постоянным ID), список ошибочных заданий — `GET /api/v1/jobs?status=failed`.
+ Интервалы настраиваются переменными `JOB_LEASE_SECONDS`, `JOB_RETRY_DELAYS`, `JOB_TIME_LIMIT`, `RECONCILE_INTERVAL`, `REDELIVERY_TIMEOUT`, `PUBLISH_TIMEOUT` и др. (см. `app/core/config.py`).

### Демонстрация падений

Испытания идут на реальных PostgreSQL, RabbitMQ, диспетчере и worker (нужны Docker Compose и Python 3.10+):
```
e2e/run.sh
```
Стенд `docker-compose.e2e.yml` сокращает интервалы, а worker в нём поддерживает тестовые барьеры (`JOB_TEST_BARRIER=before_commit|after_commit`) и принудительную ошибку (`JOB_TEST_FAIL=1`); в обычном запуске они выключены.

| Сценарий | Что проверяется |
| --- | --- |
| RabbitMQ остановлен во время `POST /jobs` | `202`, строки в `jobs` и `outbox`; после запуска брокера — `succeeded` |
| worker убит во время построения XLSX | после истечения владения задание выполняется заново, результат один |
| worker убит после коммита результата, до ack | повторная доставка не меняет `succeeded`, `COUNT(job_results)=1`, SHA-256 тот же |
| дубль публикации и два worker | одно задание, один результат |
| постоянная ошибка | ровно 3 попытки, `failed`, событие в `jobs.failed` |
| сбой транзакции создания | нет `202` и нет задания без события outbox (`tests/test_jobs_api.py`) |

Вручную: `docker-compose stop rabbitmq`, `curl -X POST localhost:8000/api/v1/jobs -H 'content-type: application/json' -d '{"kind":"menu_report"}'`, затем `docker-compose start rabbitmq` и `GET /api/v1/jobs/{id}`.

Миграции: `alembic upgrade head` (проверено up/down/up на PostgreSQL).
