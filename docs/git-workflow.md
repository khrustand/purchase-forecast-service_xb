# Отправка изменений на GitHub

Репозиторий: https://github.com/khrustand/purchase-forecast-service_xb

Изменения подготовлены в локальной ветке `codex/culinary-updates`.
Отправлять рабочие изменения следует в эту ветку, затем создавать Pull Request
в `main`. Реальные отчеты, `.env`, локальные настройки, кэш и сборки
исключены из Git. Коммиты и отправка не выполняются автоматически.

## Git на этом компьютере

Git установлен, но пока отсутствует в PATH текущего терминала. В PowerShell:

```powershell
$projectGit = 'C:/Program Files/Git/cmd/git.exe'
& $projectGit status
```

Команды выполняются из корня проекта. В локальной конфигурации включены
`push.default=current` и `push.autoSetupRemote=true`. Для коммитов требуется
явно заданное имя и email автора (`user.useConfigOnly=true`).

## Однократная настройка автора и входа

Укажите собственное имя и email, связанный с GitHub; при необходимости
используйте приватный адрес из GitHub Settings → Emails.

```powershell
& $projectGit config --local user.name 'Ваше имя'
& $projectGit config --local user.email 'Ваш email для коммитов'
& $projectGit credential-manager github login --device
```

Последняя команда запускает вход через браузер с одноразовым кодом.
Пароли и токены не нужно добавлять в репозиторий или отправлять в чат.
Вход в GitHub и право записи в репозиторий — отдельные условия: после выдачи
доступа необходимо принять приглашение владельца репозитория, если оно есть.

## Проверка доступа без публикации

```powershell
& $projectGit push --dry-run origin HEAD:refs/heads/codex/culinary-updates
```

Проверка ничего не публикует. Если она сообщает об отсутствии авторизации
или запрете доступа, реальную отправку выполнять рано.

## Сохранение и отправка

Сначала выполните тесты и просмотрите изменения. Добавляйте только файлы,
которые относятся к обновлению проекта:

```powershell
.\.venv\Scripts\python.exe -m unittest
& $projectGit status --short
& $projectGit diff
& $projectGit add -- AGENTS.md README.md docs scripts src tests
& $projectGit diff --cached --stat
& $projectGit diff --cached
& $projectGit commit -m 'feat: improve culinary forecasting and report uploads'
& $projectGit push -u origin codex/culinary-updates
```

Перед отправкой нужно проверить весь состав коммита, включая изменения,
перенесенные с прежнего компьютера. При ошибке отправки коммит остается
локально: после получения доступа достаточно повторить `push`.

Если удаленная ветка уже содержит другую историю, не используйте
`--force`: сначала выполните `fetch` и сравните ветки.
