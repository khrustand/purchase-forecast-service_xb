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

