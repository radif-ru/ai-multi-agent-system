---
name: pull-request-discipline
description: "Подготовка pull request (GitHub) / merge request (GitLab): ветка, атомарные коммиты, тело PR, зелёные проверки, merge только пользователем."
---

# Skill: pull-request-discipline

Правила подготовки PR/MR. Источник истины — `_board/process.md` §7, §9 и `_docs/instructions.md` §2.

## Когда использовать

- Готовишь pull request (GitHub) или merge request (GitLab).
- Пользователь попросил создать PR/MR.
- Проверяешь готовность ветки к merge.

## Алгоритм

1. **Ветка.** Одна `feature/<NN>-<short-name>` на спринт, от `main`. Не смешивать задачи разных спринтов в одной ветке.
2. **Коммиты — атомарные**, по Conventional Commits на русском (см. `git-discipline`). Ритуал задачи: `chore(plan): начать` → код/доки → `chore(plan): закрыть` + `plan.md`.
3. **Перед открытием PR — все зелёные:**
   - `pytest -q` (включая порог `--cov-fail-under`);
   - `flake8 app tests`;
   - `python -m scripts.check_env_sync`;
   - `python -m scripts.check_sprint_sync`.
4. **Тело PR/MR:**
   - **Summary** — что сделано и зачем, 2–5 строк. Ссылка на спринт (`_board/sprints/<NN>-*.md`).
   - **Test plan** — как проверялось: `pytest -q`, smoke-test, конкретные тесты на новое поведение.
   - **DoD** — отметить выполненные пункты из файла спринта.
5. **Скоуп PR** — один спринт. Не добавлять задачи следующих спринтов (см. `process.md` §9 п.6).
6. **Merge / push в `main` — только пользователь** по явному запросу (см. `process.md` §2 п.8 и §9). Агент никогда не делает merge/push самостоятельно.
7. **GitHub vs GitLab:**
   - GitHub: `gh pr create --base main --head feature/<NN>-...`.
   - GitLab: `glab mr create --target-branch main --source-branch feature/<NN>-...`.
   - Если CLI нет — дать готовый заголовок и тело для веб-интерфейса.

## Чего избегать

- Открытия PR при красных `pytest`/`flake8`/покрытии.
- Смешивания задач разных спринтов в одном PR.
- Самостоятельного merge/push в `main` — это делает **только пользователь**.
- PR без Test plan — reviewer не знает, как проверять.
- Больших PR (>300 строк diff) без разбиения на ревьюемые части.
