# Шаблон структуры проекта

Используйте этот шаблон, чтобы описать целевую структуру репозитория до реализации.

## Структура

```text
.
├── src/
│   ├── app/
│   ├── domain/
│   ├── infrastructure/
│   └── shared/
├── tests/
├── android/
│   └── app/
├── data/
│   └── examples/
├── docs/
├── reports/
├── scripts/
├── .codex/
│   ├── starter/
│   └── project/
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

## Ответственность директорий

| Путь | Ответственность |
| --- | --- |
| `src/app/` | Entry points фреймворка, routing, dependency wiring. |
| `src/domain/` | Business entities, rules, use cases. |
| `src/domain/production.py` | Ежедневный план собственного производства по истории продаж и переданным погодным коэффициентам, без файловых и сетевых зависимостей. |
| `src/domain/demand_planning.py` | Общая модель колебаний спроса, стоимости резерва и нехватки для ТТ и поставок. |
| `src/app/demand_views.py` | Показ модельных рисков, сравнения политик и сценариев потенциального спроса. |
| `src/app/order_exports.py` | Подготовка Excel по показанному заказу, ограниченный кэш снимков на экземпляре сервера. |
| `src/app/order_navigation.py` | Шесть ближайших дат заказа и навигация к существующему расчету выбранного периода. |
| `src/app/order_finance.py` | Финансовые показатели, итоги с полнотой данных и роли блюд в матрице: основное меню, ротация, тест. |
| `src/app/order_interactions.py` | Скрипт диалога «Подробнее», выдаваемый с того же origin без ослабления CSP. |
| `src/infrastructure/order_workbook.py` | Выгрузка поставки и ежедневного плана ТТ в OOXML/XLSX стандартной библиотекой Python. |
| `src/domain/traffic.py` | Поправка спроса по чекам и распределение общего питания сотрудников. |
| `src/domain/staff_meals.py` | Исключение онигири и темаки из расчетного резерва питания. |
| `src/domain/order_policy.py` | Срок заказа до 18:00 МСК, календарь поставок, вместимость витрины и партии ТТ. |
| `src/domain/assortment.py` | Ранжирование блюд по прибыли после потерь и предложение матрицы 32. |
| `src/domain/loss_budget.py` | Пять групп общего таргета и распределение бюджета потерь по выручке. |
| `src/infrastructure/menu_uploads.py` | Постоянная папка загруженных меню вне временного каталога exe. |
| `src/infrastructure/handoff.py` | Приватный экспорт отчетов и профиля, проверка целостности снимка. |
| `scripts/export_handoff.py`, `scripts/run_handoff.py` | Создание снимка вне Git и запуск отдельной локальной копии без ключей. |
| `src/app/analytics_views.py` | Представление месячных списаний, матрицы и истории чеков. |
| `src/infrastructure/assortment_catalog.py` | Локальный каталог кандидатов, отдельно от примененного меню. |
| `src/infrastructure/report_formats.py` | Распознавание отчетов по чекам и строк подробных актов списания. |
| `src/infrastructure/report_analytics.py` | Объединение чеков, дедупликация актов и экономика отдельных блюд. |
| `src/infrastructure/` | Database, external APIs, queues, filesystem, providers. |
| `src/shared/` | Shared utilities, constants, types. |
| `tests/` | Unit, integration и end-to-end tests. |
| `android/` | Android APK module, Gradle project, Compose UI and future Android storage. |
| `data/examples/` | Synthetic sample data for local demos and documentation. |
| `docs/` | Architecture, decisions, operations, workflows. |
| `reports/` | Generated local reports; usually ignored by git. |
| `scripts/` | Repeatable local automation and data generation scripts. |
| `.codex/project/` | Current project context, decisions, risks and next steps. |
| `.codex/starter/` | Synced shared starter kit rules, prompts and templates. |

## Правила

- Держать domain logic независимой от infrastructure.
- Делать public interfaces стабильными и документированными.
- Не хранить production-данные, приватные дампы и реальные секреты в репозитории.
- Реальные пользовательские выгрузки хранить вне репозитория или в игнорируемой директории.
- Добавлять новые папки только при понятной зоне ответственности.
- Обновлять этот файл при существенном изменении структуры.

