# Внешнее размещение сервиса

## Назначение

Сервис должен работать независимо от ноутбука в пекарне. Ноутбук, телефон или другое устройство открывают веб-адрес в браузере, а приложение постоянно работает на внешнем хостинге.

## Рекомендуемая схема

```text
GitHub
  хранит код проекта

Render Python Web Service
  запускает python -m src.app.web_server
  отдает веб-интерфейс

Supabase
  хранит XLSX-файлы, список загруженных отчетов и резервные chunks
```

Docker остается только для локальной разработки. В облаке сервис запускается как обычное Python-приложение без контейнера.

## Что уже подготовлено

- `render.yaml` настроен как `runtime: python`.
- Команда сборки: `python -m unittest`.
- Команда запуска: `python -m src.app.web_server`.
- Healthcheck: `/health`.
- Сервер поддерживает переменную `PORT`, которую выдает Render.
- Данные отчетов читаются из Supabase при `STORAGE_BACKEND=supabase`.

## Переменные окружения Render

В Render нужно задать:

```env
APP_ENV=production
PORT=10000
TZ=Europe/Moscow

APP_USERNAME=<логин для входа>
APP_PASSWORD=<пароль для входа>

STORAGE_BACKEND=supabase
SUPABASE_URL=<url проекта Supabase>
SUPABASE_ANON_KEY=<publishable key>
SUPABASE_SERVICE_ROLE_KEY=<secret key>
SUPABASE_STORAGE_BUCKET=uploads
DATABASE_URL=<строка подключения Postgres>

WEATHER_PROVIDER=met-no
WEATHER_LATITUDE=59.9343
WEATHER_LONGITUDE=30.3351
WEATHER_TIMEZONE=Europe/Moscow
WEATHER_CACHE_PATH=data/uploads/met_norway_forecast.json
WEATHER_CACHE_TTL_MINUTES=180
WEATHER_USER_AGENT=purchase-forecast-service/1.0 github.com/khrustand/purchase-forecast-service_xb
```

Секреты нельзя коммитить и нельзя отправлять в чат. В Render для них нужно использовать secret environment variables.

## Порядок размещения

1. Запушить актуальный код в GitHub.
2. В Render создать новый Blueprint или Web Service из репозитория.
3. Использовать `render.yaml`.
4. Добавить secret-переменные:
   - `APP_USERNAME`
   - `APP_PASSWORD`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `DATABASE_URL`
5. Дождаться успешной сборки.
6. Проверить `/health`.
7. Открыть `/reports` и убедиться, что блок "Используется в расчете" показывает Supabase, 2 файла продаж и 2 файла списаний.

## Supabase

Перед облачным запуском должны быть выполнены миграции:

```text
supabase/migrations/001_uploaded_reports.sql
supabase/migrations/002_uploaded_report_chunks.sql
```

Также должен существовать private bucket:

```text
uploads
```

## Ограничения

- На бесплатных тарифах Render сервис может засыпать после неактивности.
- Supabase Free подходит для MVP, но проект может быть поставлен на паузу при долгой неактивности.
- Сейчас авторизация простая: HTTP Basic Auth через `APP_USERNAME` и `APP_PASSWORD`.
- Локальный cache `data/uploads` не является постоянным хранилищем в облаке; постоянные данные должны оставаться в Supabase.
