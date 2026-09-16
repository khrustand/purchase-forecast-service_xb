# Сервис заказов кулинарии

Для ежедневной работы начните с короткой инструкции: [Как пользоваться сервисом](docs/how-to-use.md).

Локальный сервис для формирования заказов кулинарии в кофейню: обеды, салаты, роллы, супы, горячие блюда и похожие позиции. Другие товарные группы сейчас не рассматриваются.

Главная задача MVP - по списку позиций и заказам за прошлые периоды собрать понятную рекомендацию: сколько заказать на ближайшие 2 дня, где есть риск нехватки, где вероятны списания и какие позиции требуют ручной проверки.

Выпечка будет следующим отдельным блоком: сначала разбираемся с кулинарией, затем переходим к отпеку.

## Технологический стек

| Слой | Технология |
| --- | --- |
| Веб-панель | Python 3.11, стандартный HTTP-сервер |
| Расчетная логика | Python 3.11, доменные модули |
| Данные MVP | JSON/CSV |
| Инфраструктура | Docker Compose, локальный запуск |

## Локальная установка

```powershell
python -m venv .venv
python -m unittest
Copy-Item .env.example .env
# Заменить APP_PASSWORD в .env перед первым запуском.
docker compose up --build
```

Открыть веб-панель:

```text
http://localhost:8000
```

API:

```text
http://localhost:8000/api/dashboard
```

Ежемесячные отчеты:

```text
http://localhost:8000/reports
```

На странице можно загрузить XLSX с продажами или списаниями, увидеть определенный по книге период и скачать исходный файл. Загруженные месяцы автоматически объединяются в историю прогнозирования.

## Переменные окружения

| Имя | Назначение | Пример | Обязательность | По умолчанию |
| --- | --- | --- | --- | --- |
| `APP_PORT` | Порт веб-сервера | `8000` | нет | `8000` |
| `APP_USERNAME` | Логин Basic Auth | `manager` | для внешнего доступа | авторизация выключена |
| `APP_PASSWORD` | Пароль Basic Auth | случайный длинный пароль | для внешнего доступа | авторизация выключена |
| `REPORT_UPLOAD_DIR` | Каталог загруженных XLSX | `data/uploads` | нет | `data/uploads` |
| `TZ` | Часовой пояс | `Europe/Moscow` | нет | системный |
| `WEATHER_PROVIDER` | Провайдер актуального прогноза | `met-no` | нет | `off` |
| `WEATHER_LATITUDE` | Широта точки прогноза | `59.9343` | при включенной погоде | Санкт-Петербург |
| `WEATHER_LONGITUDE` | Долгота точки прогноза | `30.3351` | при включенной погоде | Санкт-Петербург |
| `WEATHER_TIMEZONE` | Часовой пояс агрегации прогноза | `Europe/Moscow` | нет | `Europe/Moscow` |
| `WEATHER_CACHE_PATH` | Файл кэша MET Norway | `data/uploads/met_norway_forecast.json` | нет | в каталоге загрузок |
| `WEATHER_CACHE_TTL_MINUTES` | Интервал обновления прогноза | `180` | нет | `180` |
| `WEATHER_USER_AGENT` | Идентификатор приложения для MET Norway | имя приложения и URL репозитория | да | идентификатор проекта |
| `STORAGE_BACKEND` | Где хранить загруженные отчеты | `local` или `supabase` | нет | `local` |
| `SUPABASE_URL` | URL проекта Supabase | `https://bzwnnccqlbmlxigyrmhy.supabase.co` | для облачного режима | нет |
| `SUPABASE_ANON_KEY` | Publishable key Supabase | `sb_publishable_...` | для облачного режима | нет |
| `SUPABASE_SERVICE_ROLE_KEY` | Secret key Supabase для backend | `sb_secret_...` | для облачного режима | нет |
| `SUPABASE_STORAGE_BUCKET` | Bucket для XLSX-файлов | `uploads` | для облачного режима | `uploads` |
| `DATABASE_URL` | Строка подключения к Supabase Postgres | `postgresql://...` | для облачного режима | нет |

Локальные значения хранятся в `.env`. Файл исключен из Git; в репозиторий входит только безопасный шаблон `.env.example`. Для Render значения `APP_USERNAME` и `APP_PASSWORD` из локального файла добавляются вручную как Secret-переменные.
Ключи `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` и `DATABASE_URL` нельзя отправлять в чат и нельзя коммитить; их нужно хранить только в локальном `.env` и в Render Environment Variables.

## Команды разработки

| Команда | Назначение |
| --- | --- |
| `python -m unittest` | Запустить unit-тесты. |
| `python -m src.app.cli --items data/examples/purchase_items.json --start 2026-06-18 --days 14` | Построить календарь заказов кулинарии из демо-данных. |
| `py -m scripts.analyze_culinary_strategy --sales data\local\culinary_sales_june_july.xlsx --waste data\local\culinary_waste_june_july.xlsx --shelf-life "data\local\Хранение и сроки годности, реализации.xlsx" --start 2026-06-01 --end 2026-07-31 --days 2 --output reports\culinary_strategy_with_waste_june_july.md` | Пересобрать отчет по продажам, списаниям и срокам годности. |
| `docker compose up --build` | Запустить локальную веб-панель. |
| `py -m scripts.generate_current_order_report --date 2026-08-19 --output reports/current_order_2026-08-19.md` | Сформировать датированный отчет заказа с учетом погоды и списаний. |

## Логика заказа

Базовая формула:

```text
заказ = прогноз спроса на 2 дня + страховой запас - текущий остаток
```

После этого количество округляется до кратности заказа или производственной партии.

Срок годности ограничивает запас: готовая кулинария по умолчанию считается на 3 дня, а позиции со сроком 2 дня рассчитываются без страхового запаса сверх горизонта заказа.

Для первых расчетов нужны:

- список позиций: название, категория, срок годности, себестоимость, кратность заказа;
- продажи или заказы за прошлые периоды;
- остатки перед заказом;
- списания;
- пометки по дням: будни, выходные, погода, акции, локальные события.

## Структура проекта

```text
.
├── src/
│   ├── app/
│   ├── domain/
│   ├── infrastructure/
│   └── shared/
├── tests/
├── data/
│   └── examples/
├── docs/
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Документация

- Простая пользовательская инструкция: [docs/how-to-use.md](docs/how-to-use.md).

- Сценарии продукта: [docs/product-scenarios.md](docs/product-scenarios.md).
- Модель заказов кулинарии: [docs/culinary-order-model.md](docs/culinary-order-model.md).
- Веб-панель: [docs/web-dashboard.md](docs/web-dashboard.md).
- Руководство для заказчика: [docs/customer-order-dashboard-guide.md](docs/customer-order-dashboard-guide.md).
- Внешнее размещение: [docs/external-deployment.md](docs/external-deployment.md).

## Диагностика проблем

| Проблема | Решение |
| --- | --- |
| Прогноз слишком ровный | Прислать продажи по нескольким прошлым периодам и дням недели. |
| Заказ завышен | Добавить остатки и списания. |
| Не видно риска нехватки | Добавить минимальный остаток и кратность заказа. |
| Не открывается веб-панель | Проверить `docker compose ps` и порт `APP_PORT`. |

## Supabase

Для облачного режима нужно один раз выполнить SQL из файла `supabase/migrations/001_uploaded_reports.sql` в Supabase SQL Editor и создать private bucket `uploads`.

После этого можно включить хранение отчетов в Supabase:

```env
STORAGE_BACKEND=supabase
```

В этом режиме оригинальные XLSX-файлы хранятся в Supabase Storage, а реестр загрузок хранится в таблице `uploaded_reports`. Расчетная модель продолжает читать файлы через тот же интерфейс, поэтому локальный режим остается запасным вариантом.

Если Supabase Storage обрывает загрузку большого XLSX, сервис сохраняет файл в таблицу `uploaded_report_chunks` небольшими частями и затем собирает его обратно при расчете. Для этого после `001_uploaded_reports.sql` нужно выполнить миграцию `supabase/migrations/002_uploaded_report_chunks.sql`.

## Облачный веб-запуск без Docker

Для работы независимо от компьютера сервис размещается как Render Python Web Service:

```text
GitHub -> Render Python Web Service -> Supabase
```

Render запускает приложение командой:

```powershell
python -m src.app.web_server
```

Постоянные данные остаются в Supabase, поэтому ноутбук в пекарне открывает только веб-адрес сервиса. Подробная инструкция: [docs/external-deployment.md](docs/external-deployment.md).

## Windows-приложение

Windows-выпуск работает как самостоятельное локальное приложение: запускается `purchase-forecast-service.exe`, поднимает сервер внутри процесса и открывает отдельное окно приложения через Microsoft Edge в режиме `--app`. В обычном сценарии пользователь не работает с адресной строкой `localhost` и не видит консоль.

Сборка:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -InstallPyInstaller
```

Готовый файл:

```text
dist\purchase-forecast-service.exe
```

Установщик для чистой Windows-машины:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_installer.ps1 -InstallInno
```

Готовый установщик:

```text
dist\PurchaseForecastServiceSetup.exe
```

Этот файл можно перенести на новый компьютер с Windows и интернетом. Установщик не требует Python, Docker, VS Code или Android Studio: он ставит уже собранное приложение, создает ярлыки и предлагает запустить сервис сразу после установки.

Если Supabase уже настроен, exe сразу открывает главный экран заказов. Загрузка отчетов не является стартовым шагом: программа берет данные из подключенной базы и Supabase Storage.

Если настроек еще нет, exe откроет экран первичной настройки. На нем нужно один раз указать Supabase URL, secret key, bucket `uploads` и при необходимости логин/пароль входа в сервис. Настройки сохраняются локально:

```text
%APPDATA%\purchase-forecast-service\.env
```

Если рядом с exe положить `.env`, он будет иметь приоритет над AppData-настройками. Это удобно для переносного режима, но реальные ключи Supabase и пароль панели нельзя коммитить и нельзя отправлять в чат.
