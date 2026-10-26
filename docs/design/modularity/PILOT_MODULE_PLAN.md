# Buddie — Pilot Module Plan

Задание на первый архитектурный эксперимент. Его можно передать Claude Code как есть.
Контекст: [ARCHITECTURE_AUDIT.md](ARCHITECTURE_AUDIT.md), [MODULAR_ARCHITECTURE_PROPOSAL.md](MODULAR_ARCHITECTURE_PROPOSAL.md),
[MODULARIZATION_ROADMAP.md](MODULARIZATION_ROADMAP.md) (это задача R6).

---

## 1. Выбор пилота

Сравнение четырёх реальных кандидатов. Оценка: «+» — хорошо для пилота, «−» — плохо.

| Критерий | `sources` (цитаты и числа) | `execution/choice:` | `github pr:/ci:` | observer `environment` |
|---|---|---|---|---|
| Связанность | + `verbatim` грузит 5 модулей (E3); вне подпакета только ленивый `runner` | ± маленький код, но тянет `summary`→`decisions`→`logbook`, `config`, `mandate` | − `freshness`, `policy`, `evidence`, `own_get`, токен | + 2 модуля (`environment`, `runner`) |
| Число зависимостей | + `verbatim/*`, `stores.UnionStore` (как объект) | − 5+ | − 6+ | + 1 |
| Сложность выделения | ± нужно перенести `check_quotes`/`check_numbers`/`_quote_row` и учесть `quote_backed` | + мала (это R1) | − высокая | + почти нулевая: уже отделён |
| Наличие тестов | + `tests/quotes/` (1300+ строк), `test_buddie`, `test_receipts`, `test_modules`, golden-сценарии гейта | ± `test_summary`, `test_decisions` | + `test_effects`, `test_provenance_*` | + `test_environment` (726 строк) |
| Риск изменения поведения | ± средний: это основной продукт, но поведение полностью детерминировано offline | + низкий | − высокий (security-sensitive) | + низкий |
| Польза для модульности | + высокая: первый модуль, вызываемый через реестр, — шаблон для остальных | − низкая: исправление границы, а не модуль | + высокая, но рано | − низкая: не модуль проверки, ничего не доказывает про `Module.run` |
| Объективная проверка успеха | + байт-в-байт receipts на golden-корпусе offline | + один тест | ± нужна сеть или моки GitHub | ± нечего сравнивать: API не меняется |

**Выбор: `sources`.** Это единственный кандидат, который одновременно проверяет предложенный `Module.run`, имеет
изолированный код и даёт бинарный критерий успеха (байт-в-байт). `execution/choice:` — обязательный, но отдельный шаг
(R1). `github` — следующий модуль после пилота (R8). `environment` для пилота модуля проверки не подходит.

---

## 2. Предусловия

- Слиты R0 (golden-корпус receipts), R1 (явный журнал) и R2 (ленивые импорты `mandate` и `freshness`).
- Ветка от актуального `main`, например `refactor/sources-module`. `main` не трогать, PR не сливать автоматически.
- Локально проходит `python -m pytest -q` (Windows: `PYTHONUTF8=1`).

---

## 3. Точные границы изменений

**Разрешено изменять:**

| Файл | Что |
|---|---|
| `buddie/modules.py` | добавить `Inputs`, `Output`, `API_VERSION`; поле `run: Callable \| None = None` у `Module`; `by_id(id)`; заполнить `run` у `sources` |
| `buddie/sources.py` (новый) | `run(text, inputs, checks) -> Output`; перенесённые из `verify.py` `check_quotes`, `check_numbers`, `_quote_row`, `KEEP` |
| `buddie/verify.py` | в `_assess` вызывать `sources` через реестр вместо прямых `check_quotes`/`check_numbers` (`verify.py:226, 233, 238`); оставить алиасы `check_quotes = sources.check_quotes`, `check_numbers = sources.check_numbers`, `_quote_row`, `KEEP` для обратной совместимости |
| `tests/test_module_contract.py` (новый) | тесты из §5 |
| `docs/architecture.md` | один абзац в разделе Modules: у `sources` есть `run`, у остальных пока нет |
| `CHANGELOG.md` | строка в Unreleased: «internal: the sources module runs through the registry; no change to receipts» |

**Запрещено изменять:** `core.py`, `findings.py`, `receipts.py`, `anchors.py`, `effects.py`, `mandate.py`,
`summary.py`, `hook.py`, `cli.py`, `mcp.py`, `remote.py`, `config.py`, `policy.py`, `evidence.py`, `stores.py`,
`buddie/verbatim/**`, любые существующие тесты и `tests/data/**`, `pyproject.toml`, манифесты плагинов, `server.json`,
`manifest.json`.

**Остаётся в `verify._assess` (Core), не переносится в модуль:**
- создание `Store`/`UnionStore`, снимок `store.collected` до и после, `evidence.network_clean()`. Это provenance, и её
  решает ядро (`verify.py:214-225, 239-240`);
- `quote_backed` и `anc.unanchored`: межмодульный сигнал, где результат `sources` влияет на подсчёт голых чисел;
- подсчёт `terms` (unlinked terms), сборка `rows`, `blocking`, `gaps`, `summary`, `line`, receipt-v0;
- `fnd.from_rows` и `fnd.coverage`: перевод слов в Fact и Provenance.

---

## 4. Шаги

1. **`modules.py`.** Добавить:
   ```python
   @dataclass(frozen=True)
   class Inputs:
       store: object
       fetch: bool = True
       access: str | None = None
       numbers: str = "gap"
       journal: tuple[Path, ...] = ()  # разрешён R1 до вызова модуля
       quotes: bool = True          # call option: False = anchors only (as today's `quotes`)

   @dataclass(frozen=True)
   class Output:
       rows: dict                    # {"quotes": [...raw verbatim results...], "numbers": [...]}
       executed: frozenset           # core.Check that ran
       extra: dict                   # {"skipped": int, "verbatim": str | None}

   API_VERSION = 1
   ```
   В пилоте `Inputs` содержит поля `sources` и явный journal после R1. Поля для `github`/`execution` (repos, github,
   transcript, mandate, rev) добавляются в R8, не сейчас. Поле `run` у `Module` по умолчанию `None`, так
   что `github` и `execution` не меняются. Обновить docstring модуля: у модуля может быть `run`, загрузки кода
   по-прежнему нет.
2. **`sources.py`.** Перенести `check_quotes`, `check_numbers`, `_quote_row`, `KEEP` из `verify.py` без изменений
   тела. Реализовать:
   ```python
   def run(text: str, inputs: Inputs, checks: frozenset) -> Output:
       quotes = inputs.quotes and Check.QUOTE in checks
       numbers = inputs.numbers if (inputs.quotes and Check.NUMBER in checks) else "off"
       q, skipped, vv = check_quotes(text, store=inputs.store, fetch=inputs.fetch, access=inputs.access) \
           if quotes else ([], 0, None)
       n = check_numbers(text, store=inputs.store, fetch=inputs.fetch) if numbers != "off" else []
       return Output({"quotes": q, "numbers": n},
                     frozenset({Check.QUOTE} if quotes else set()) | frozenset({Check.NUMBER} if numbers != "off" else set()),
                     {"skipped": skipped, "verbatim": vv})
   ```
   Импорты `sources.py` — только `buddie.core`, `buddie.modules` и ленивые `buddie.verbatim.*`.
3. **`verify._assess`.** До строки 215 сохранить исходные опции вызова: `quotes_asked, numbers_asked = quotes,
   numbers`. Строки 215-217 перезаписывают эти имена. Сами вычисления `quotes`/`numbers`/`run_numbers` оставить как
   есть: они нужны и для других веток (`coverage`, `not_run`). Заменить строку 226 вызовом
   `out = mods.by_id("sources").run(text, mods.Inputs(store=store, fetch=fetch, access=access, numbers=numbers_asked, quotes=quotes_asked, journal=journal), on)`.
   `q_results`, `skipped`, `vv` брать из `out`; строку 238 — `n_rows = [... из out.rows["numbers"] ...]`.
   **Порядок обращений к хранилищу сохраняется:** сначала цитаты, затем числа. Между ними сейчас выполняются якоря и
   `mandate`, но хранилище они не используют. Если R0 покажет расхождение, вернуть вызов чисел на прежнее место
   отдельным `run`-вызовом с `checks={NUMBER}`.
   `ran` для QUOTE/NUMBER (`verify.py:297-298`) брать из `out.executed` и проверить `assert`-ом в тесте (не в коде),
   что результат совпадает с прежней формулой.
4. **Алиасы** в `verify.py`: `from buddie.sources import check_quotes, check_numbers, _quote_row, KEEP` — ленивый
   импорт недопустим, имена должны остаться атрибутами `verify`. Проверить, что это не создаёт цикл:
   `sources` не импортирует `verify`.
5. **Тесты** (§5), затем полный прогон.
6. **Документация:** абзац в `docs/architecture.md`, строка в CHANGELOG.

---

## 5. Необходимые тесты

Новый файл `tests/test_module_contract.py`:

| Тест | Проверяет |
|---|---|
| `test_sources_runs_through_the_registry` | `modules.by_id("sources").run is sources.run`; у `github`/`execution` `run is None` |
| `test_inputs_names_cover_declared_inputs` | для модулей с `run`: каждое имя из `Module.inputs` — поле `Inputs` или документированный синоним (`store`, `fetch`) |
| `test_sources_imports_no_other_checker` | AST `buddie/sources.py`: импорты ⊆ {`buddie.core`, `buddie.modules`, `buddie.verbatim.*`} |
| `test_a_module_cannot_claim_support_with_an_unknown_word` | monkeypatch `sources.run`, строка с `verdict="TOTALLY_TRUE"` → `Fact.UNRECOGNIZED`; v0 GAPS, v1 UNKNOWN (инвариант 1) |
| `test_a_module_cannot_claim_collector_provenance` | monkeypatch `sources.run`, строка `FOUND` с `sha256`, которого нет в `store.collected` → `Provenance.UNKNOWN` (инвариант 1) |
| `test_nothing_executed_is_not_a_pass` | `sources` выбран, но `quotes=False` → v1 `NOT_RUN` или `scope.coverage=PARTIAL`, v1 outcome ≠ PASS (инвариант 2) |
| `test_a_module_error_fails_closed` | `sources.run` бросает исключение → `assessment` пробрасывает его; хук на Stop с этим текстом возвращает ответ (exit 2), как в `tests/test_failsafe.py` (инвариант 3) |
| `test_verify_still_exports_the_moved_names` | `verify.check_quotes is sources.check_quotes` и т.д. |
| `test_executed_matches_the_old_formula` | для сетки (`quotes` × `numbers` × выбор) `out.executed` = прежняя формула `ran` |

Существующие тесты, которые **должны пройти без правок**: весь набор, особенно `tests/test_receipts_golden.py` (R0),
`tests/test_buddie.py`, `tests/test_receipts.py`, `tests/test_modules.py`, `tests/test_profiles.py`,
`tests/test_layers.py`, `tests/test_provenance_unforgeable.py`, `tests/test_provenance_boundaries.py`,
`tests/test_gate.py` (+ `tests/data/gate_golden.json`), `tests/test_failsafe.py`, `tests/quotes/`.

---

## 6. Критерии завершения

1. `git diff --stat main...` затрагивает только файлы из таблицы §3.
2. `python -m pytest -q` зелёный локально; CI зелёный на всех jobs (`test` 3.11–3.13, `os` ×3, `release-candidate`,
   `catalogs`, `docker`).
3. Golden receipts (R0) совпадают байт-в-байт для v0 и v1.
4. Новые тесты §5 зелёные.
5. `verify.verify(...)` на тексте из одного file-якоря загружает тот же набор `buddie.*`, что и `main` после R2, плюс
   только `buddie.sources`.
6. Новый файл проходит `tests/test_release_hardening.py`: тест сканирует все `buddie/**/*.py`.
7. `buddie verify examples/quickstart/report.md --no-fetch` и шаги CI «examples behave as the README says» дают тот
   же вывод.
8. В PR описано: что перенесено, что намеренно оставлено в Core и почему (provenance, `quote_backed`).

---

## 7. Критерии остановки и отката

- Если golden receipts расходятся и причину нельзя устранить без изменения порядка вызовов или формы строк,
  **остановиться** и записать причину в PR. Это результат эксперимента: оркестратор держит неявный контракт порядка.
  Не «чинить» эталон.
- Если для пилота приходится править любой запрещённый файл из §3, остановиться и вынести вопрос на ревью.
- Откат: `git revert` PR целиком. R0, R1 и R2 остаются полезными сами по себе.

---

## 8. Что не делать в пилоте

- Не трогать `github`/`execution`, `effects.py`, `anchors.py`.
- Не перехватывать исключения модулей.
- Не добавлять поля в receipts, флаги CLI, MCP-аргументы.
- Не вводить entry points, загрузку из путей, версии модулей сверх константы `API_VERSION`.
- Не переносить `quote_backed`, provenance, сборку receipt в модуль.
- Не переименовывать модули и не менять `IDS`.
