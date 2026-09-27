# Архитектура AXIOM

Документ описывает, как устроен проект и почему. Краткая версия правил живёт в
корневом `README.md`, здесь — детали с указанием модулей.

---

## Два принципа

### 1. REAL FIRST

Axiom не симулирует работу AI. Запрещены fake responses, fake reasoning,
fake web search, fake статусы, fake счётчики токенов и статические
демо-данные в production flow.

Практические следствия:

* reasoning существует в UI только тогда, когда модель реально прислала поле
  `thinking` (или legacy `<think>`-теги в контенте);
* блок «WEB SEARCH» в сообщении возникает только после реального вызова
  `SearchProvider`;
* статус `COMPLETED` невозможен при пустом ответе — в `ChatSession` встроена
  empty-answer protection (`axiom/core/chat.py`);
* capabilities модели берутся из ответа `/api/tags`; если Ollama не сообщила
  возможность — она показывается как `unknown`, а не `supported`
  (`axiom/core/models.py::ModelInfo.supports`).

### 2. UI ≠ LOGIC

Axiom — это ядро, у которого есть фронтенды. Ядро не знает слов «Textual»,
«Rich», «Qt»: оно общается снаружи только через:

* **команды** — методы `ChatSession` (`send`, `cancel`, `switch_model`,
  `new_conversation`, `load_conversation`, `refresh_models`, `reconnect` ...);
* **события** — `AsyncIterator[ChatEvent]` из `ChatSession.send()`;
* **структуры данных** — pydantic-модели из `axiom/core/events.py`.

Фронтенд — тонкий адаптер: подписывается на события, рисует их, шлёт команды
обратно. Проверка чистоты — тест `test_no_ui_imports` (см. `TODO.md`).

---

## Карта модулей

```text
src/axiom/
├── __init__.py            ← __version__ + публичный API
├── __main__.py            ← единственное место выбора фронтенда
├── core/                  ← frontend-agnostic ядро
│   ├── events.py          ← ChatEvent: все события потока
│   ├── state.py           ← GenerationState (перечисление)
│   ├── state_machine.py   ← валидатор переходов
│   ├── chat.py            ← ChatSession: send/cancel/startup/история
│   ├── agent.py           ← агентный цикл: model → tools → model → answer
│   ├── models.py          ← discovery + capabilities (ModelRegistry)
│   ├── ollama.py          ← HTTP-клиент + адаптивный streaming-парсер
│   ├── config.py          ← загрузка/сохранение конфигурации
│   ├── history.py         ← Conversation + HistoryStore (SQLite/FTS5, W2.6)
│   ├── memory.py          ← MemoryItem/MemoryStore + memory-инструменты (W2.1)
│   ├── errors.py          ← доменные ошибки (AxiomError и наследники)
│   ├── tools/             ← base / registry / web_search
│   └── search/            ← provider (ABC) / duckduckgo
├── frontends/
│   ├── tui/               ← Textual: app.py + widgets/ + theme.tcss
│   └── gui/               ← лаунчер `axiom --gui` (main.py), само приложение в desktop/
└── shared/                ← данные для всех фронтендов: theme, logo, formatting
```

Ответственность каждого модуля — одна; новых «параллельных» реализаций одной
функции нет (правило §50 исходной спецификации).

---

## Поток событий (ChatEvent)

`ChatSession.send()` возвращает `AsyncIterator[ChatEvent]`. Типы
(`axiom/core/events.py`):

| Событие | Поля | Когда возникает |
|---|---|---|
| `StatusChange` | `state`, `detail` | подтверждённый переход state machine |
| `ReasoningChunk` | `text` | дельта реального reasoning |
| `ContentChunk` | `text` | дельта реального ответа |
| `ToolCallEvent` | `name`, `arguments` | модель запросила инструмент |
| `ToolResultEvent` | `name`, `ok`, `content`, `error`, `duration_ms` | результат реального выполнения |
| `SearchResultEvent` | `query`, `sources: list[SourceItem]` | поиск вернул источники (`index`, `title`, `url`, `snippet`) |
| `ErrorEvent` | `message`, `kind`, `hint` | ошибка пользователя (никогда traceback) |
| `Done` | `state`, `duration_ms`, `tokens_out`, `tokens_in`, `tokens_per_second` | терминальное событие с метриками Ollama |

Инвариант: после `Done` поток завершается; `Done.state` — одно из
`COMPLETED / CANCELLED / ERROR`.

## State machine генерации

`axiom/core/state.py` + `state_machine.py`. Состояния:

```text
IDLE → CONNECTING → THINKING ⇄ TOOL_CALL ⇄ SEARCHING → RECEIVING → COMPLETED
                                                                → CANCELLED / ERROR
```

Правила:

* busy-состояния (`CONNECTING/THINKING/TOOL_CALL/SEARCHING/RECEIVING`) могут
  переходить друг в друга — реальный цикл агента нелинеен;
* любой busy-стейт → финальный (`COMPLETED/CANCELLED/ERROR`);
* из финального разрешён только переход в `IDLE` (новая отправка делает
  `machine.reset()`);
* недопустимый переход вызывает `InvalidTransitionError` — UI не может
  показать статус, которого не было в реальности.

`Agent._status()` эмитит `StatusChange` только если переход разрешён —
state machine это единственный источник статусов.

## Агентный цикл

`axiom/core/agent.py`:

```text
USER → CONTEXT (последние 40 сообщений) → SYSTEM PROMPT
     → MODEL STREAM
        ├── reasoning deltas → ReasoningChunk
        ├── content deltas   → ContentChunk
        └── tool_calls?
              ├── web_search → SearchProvider.search → источники
              │     └── чтение топ-N страниц (fetch_url) → блок результатов
              ├── результат → system-сообщение → MODEL снова
              └── максимум MAX_TOOL_ROUNDS = 3 раундов
     → финальный ANSWER
```

Принудительный поиск (`/search`, флаг `-s`) выполняется до первого вызова
модели: результаты подмешиваются в system prompt. Если поиск недоступен,
агент честно сообщает об этом модели и отвечает без источников.

## Слои промпта (W2.5)

`axiom/core/prompt_builder.py` собирает system prompt из упорядоченных слоёв:
`core` → `role` (профиль) → `workspace` → `project` → `memory` →
`knowledge` → `skills` → стиль ответа → текущий запрос. Агент подставляет
только готовые блоки (workspace, бюджетный срез памяти, skill-блоки) — никакой
бизнес-логики в сборке нет, и кастомный `Config.system_prompt` пользователя
всегда побеждает сборщик целиком.

* два варианта политики: `mini` (только жёсткие правила, бюджет 4000
  символов) и `full` (полная политика решений с тулами, бюджет 12000);
  выбор детерминированный — сложность запроса + `thinking_mode`/`budget`,
  без дополнительного вызова модели;
* бюджет жёсткий: при переполнении сначала сдаются `role`/`knowledge`/
  `skills`, а `core`, `workspace`, правила проекта и текущий запрос не
  вытесняются никогда;
* в промпт не инжектится непроверяемых требований и скрытых
  chain-of-thought-инструкций — каждый собранный промпт обязан содержать
  правило честности («never claim unobserved results») и запрет угадывания.

## Инструменты и права

`axiom/core/tools/`: `ToolDefinition` (name, description, JSON-schema
параметров, permission) + `ToolRegistry.execute()`.

| Инструмент | Назначение | Permission |
|---|---|---|
| `web_search` | реальный поиск DuckDuckGo (HTML/lite endpoints, без ключей) | `ALWAYS` |
| `fetch_url` | чтение текста страницы для источников | `ALWAYS` |

`Permission.NEVER` блокирует вызов даже если модель его запросила; исключения
обработчиков превращаются в структурированный `ToolResult(ok=False)` — тул
никогда не валит агента. Произвольный доступ к файлам/шеллу отсутствует
(правило LOCAL FILE ACCESS = OFF); архитектура позволяет добавить tool
с нужным permission позже.

## Десктоп-фронтенд: декомпозиция и виртуализация (W2.7)

Desktop-слой — тонкий адаптер над core, но два модуля выросли слишком сильно и
тормозили длинные чаты и большие деревья файлов. Правило W2.7: визуал не
меняется (тёмная тема и все стили сохранены), меняется только организация кода
и стоимость рендера.

* **CSS по доменам**: `desktop/src/styles.css` (быстро разрастался до ~3941
  строки) разделён — boot-экран и доска оркестрации вынесены дословно в
  `src/styles/boot.css` и `src/styles/orchestration.css`, правила виртуализации
  — в `src/styles/virtualization.css`. `main.tsx` импортирует их в исходном
  порядке следования, поэтому каскад и внешний вид не изменились ни в одной
  теме (obsidian/light/midnight/terminal/solarized и акценты W1.1).
* **Хук состояния**: чистые pure-функции (`liveAssistant`/`updateLive`,
  подписи и статусы тулов, `resolveModel`, `orchestrationProgress` и др.)
  вынесены из `useAxiom.ts` в `useAxiom.helpers.ts`; хук держит только state и
  эффекты, хелперы реэкспортируются — существующие импорты не тронуты.
* **Рендер списка сообщений**: `UserMessage`/`AssistantMessage` обёрнуты в
  `React.memo`; колбэки стабилизированы через ref (без устаревших замыканий),
  а live-пропсы (`liveState`/`statusText`/`elapsedMs`) доходят только до
  стримящегося сообщения — осевшие ответы не перерисовываются на каждом
  сбросе текста.
* **Виртуализация без библиотек**: сообщения чата и строки Explorer используют
  `content-visibility: auto` + `contain-intrinsic-size` — браузер пропускает
  layout/paint вне вьюпорта, DOM, скролл и поведение (автоскролл, sticky
  низ) сохранены.
* **Батчинг потока**: токены дельт накапливаются и сбрасываются фиксированным
  таймером ~30 мс (очищается при завершении/ошибке/размонтировании) вместо
  перерисовки на каждый animation frame.
* **Бандл**: `manualChunks` (vendor-react / vendor-markdown / vendor-highlight)
  убрали предупреждение о чанке > 500 кБ; максимальный чанк упал с
  822.72 кБ до 342.86 кБ (gzip 245.22 → 105.71 кБ), суммарный минифицированный
  размер не вырос (822.72 → 818.87 кБ).

Проверки: `tsc --noEmit`, сборка Vite и весь E2E-прогон (47/47, включая
реальную потоковую генерацию через мост).

## TUI package (W2.8)

TUI остаётся тонким Textual-адаптером: `/memory`, `/knowledge` и `/plugins`
проецируют существующие core-менеджеры без копирования бизнес-логики. Дополнительно:

* `Ctrl+F` ищет только в реально смонтированных сообщениях текущего чата и
  переключает совпадения через `Enter`/`Shift+Enter`; поиск не подмешивает старую
  историю и не создаёт отдельный индекс.
* `OrchestrationPanel` показывает события из `ChatSession.trajectory` начиная с
  baseline текущего запуска. В timeline попадают только реальные events; `s`
  вызывает обычный `session.cancel()`.
* `/benchmark` запускает существующий `BenchmarkRunner` с изолированными
  `ChatSession`, показывает cold/warm runs, реальные timing/throughput metrics и
  ошибки. Недоступная модель отображается как failed run, а не как fake success.
* Акцентная тема и правила hover остаются общими с W1.1; новые панели используют
  те же `$accent`, `$secondary` и глубокий чёрный фон.

## Диалог разрешений (W2.4)

## Orchestrator v2 и Security Package (W2.3/W2.9)

`ChatSession.run_orchestrated()` сохраняет общую `Trajectory` через
`TrajectoryStore` на выходе из запуска. `Trajectory` содержит фактическую
последовательность событий, usage и `export_markdown()`; `resume_orchestrated()`
загружает тот же run id и `Orchestrator` пропускает workers, для которых уже
есть `agent.done`. План содержит также реальные зависимости (`analyst` →
workers → `reviewer`), а bridge предоставляет `trajectory_export` и
`orchestrate_resume`.

W2.9 подключён на границах core:

* `ToolRegistry.execute()` пишет JSONL-аудит с длительностью, результатом,
  SHA-256 аргументов и рекурсивной маскировкой секретов;
* `WorkspaceTools` делает атомарный pre-edit snapshot через `CheckpointStore`
  перед write/edit/delete/move/copy; rollback восстанавливает существующий
  файл или удаляет новый;
* `WebSearchTool.fetch()` прогоняет URL через `NetGuard` и оборачивает текст
  источника в `[untrusted: host]`; `Config.local_only` блокирует web search,
  fetch и embeddings до сетевого вызова;
* все ограничения fail-closed и покрыты детерминированными локальными тестами.

`PermissionManager` (`axiom/core/permissions.py`) — единственный движок
решений: режим (`ask` / `auto_approve_safe` / `auto_approve_all`) и
`Permission.NEVER` проверяются первыми, а для `ASK`-инструментов вызывается
`request_callback` фронтенда. Ответ диалога — `PermissionOutcome`:
`allow_once` (только этот вызов), `allow_always` (помнить инструмент до
конца сессии), `deny`. Кэшируется только `allow_always` (по имени
инструмента); `once` и `deny` спрашиваются заново. Неизвестный ответ
трактуется как отказ (fail-closed).

Desktop: bridge эмитит событие `permission_request` (`tool`, `arguments`,
`cwd`, `risk`) и **приостанавливает** вызов инструмента, пока UI не вернёт
`permission_respond {id, decision}` (`_ask_permission` /
`_resolve_permission` в `desktop/src-tauri/bridge/axiom_bridge.py`). Диалог —
`ConfirmDialog.tsx` (три действия; Esc = отказ). TUI: `PermissionDialog`
возвращает тот же `PermissionOutcome` (Enter / F2 / Esc) и подключён в
`WorkspaceScreen.on_mount`. Отказ приходит модели как структурированный
`ToolResult(ok=False)` — агент не падает.

## Плагины и UI-контракт (W1.5)

Плагины живут в `~/.axiom/plugins/<name>/`: `manifest.json` + точка входа
(`plugin.py`), которая регистрирует **реальные инструменты** через
`register(registry)` или `TOOLS`/`HANDLERS` (`axiom/core/plugins.py`).
Встроенный каталог — `src/axiom/plugins/bundled/`.

W1.5 определяет версионированный **UI-контракт точек расширения**: блок `ui`
в манифесте (`api_version`, `scopes`, `extensions[]`) декларирует точки
`panel`, `command`, `setting`, `renderer`, `theme` и scopes
`fs`/`net`/`ui`/`clipboard`. Валидация выполняется до импорта кода плагина:
несовместимая версия (`UI_EXTENSION_API_VERSION`), неизвестная точка или scope
отклоняются с `PluginLoadError`. Хост (iframe/Worker) появляется в W3.1 и
обязан соблюдать гарантии контракта: только типизированные
request/response/события, изоляция, least-privilege scopes. Полный контракт —
в `docs/plugins.md` (раздел 11).

## Память (W2.1)

`axiom/core/memory.py` — долговременные факты о пользователе поверх чата.
Модель работает с памятью **только через три инструмента**: `memory_write`,
`memory_read`, `memory_forget` (все `Permission.ALWAYS`). Прямой записи в файл
из других мест нет: `MemoryStore` — единственный владелец `~/.axiom/memory.json`
(атомарная запись + `fcntl.flock`, повреждённый файл не роняет ядро).

* `MemoryItem` — факт с `scope` (`global`/`project`/`user`) и `tags`;
  `scope=project` подмешивает путь workspace, поэтому факты проекта не
  перепутываются с личными;
* `add()` отклоняет пустой текст, `update()` — правку чужого id;
* `recall(query, limit)` — поиск по тексту и тегам с жёстким лимитом: в промпт
  попадает ограниченное число фактов, а не вся память.

Память — часть `ChatSession`: у клиента (`axiom/client.py`) ровно один
`MemoryStore`, инструменты регистрируются в общий `ToolRegistry`, а
`ChatSession.config()` показывает активную память в `/config`. Очистка памяти
проекта при выходе из него выполняется на уровне session, чтобы не осталось
смешанных фактов.

## База знаний (W2.2)

`axiom/core/knowledge/` — локальный RAG поверх пользовательских папок и
документов. Модель работает с базой **только через три инструмента**:
`knowledge_search`, `knowledge_index`, `knowledge_status` (все
`Permission.ALWAYS`, чтение/идемпотентная индексация).

* `chunking.py` — детерминированный чанкер: разрез по абзацам с overlap,
  реальные номера строк каждого фрагмента; секреты (`.env`, ключи) и бинарные
  файлы никогда не индексируются;
* `store.py` — `KnowledgeStore` на SQLite/FTS5 (`~/.axiom/knowledge/<name>.db`):
  BM25-ранжирование работает полностью офлайн; индексация инкрементальная
  (fingerprint = mtime+size, перечитываются только изменённые файлы, удалённые
  выпадают из индекса). Эмбеддинги — опциональный слой переранжирования через
  реальный Ollama `/api/embed` (60% косинус + 40% нормированный BM25); статус
  честный — `ok` / `unavailable: <причина>` / `disabled`, недоступные
  эмбеддинги не ломают поиск;
* `manager.py` — реестр коллекций (`~/.axiom/knowledge.json`, атомарная
  запись) и общий `Embedder`; модель эмбеддингов настраивается через
  `Config.knowledge_embed_model`;
* `tools.py` — каждый поиск возвращает цитируемые фрагменты
  `[n] <коллекция>/<источник>:<строки>` с текстом чанка, пустой результат —
  честное «no knowledge fragments».

`ChatSession` владеет `KnowledgeManager`/`KnowledgeTools`, регистрирует три
инструмента и отдаёт UI-проекции (`knowledge_rows`, `knowledge_search_rows`);
Desktop (Настройки → Знания) и TUI (`/knowledge`) — тонкие адаптеры над ними.


## Память (Memory)

Модель работает с памятью **только через три инструмента**: `memory_write`,
`memory_read`, `memory_forget` (все `Permission.ALWAYS`). Прямой записи в файл
из других мест нет: `MemoryStore` — единственный владелец `~/.axiom/memory.json`
(атомарная запись + `fcntl.flock`, повреждённый файл не роняет ядро).

* `MemoryItem` — факт с `scope` (`global`/`project`/`user`) и `tags`;
  `scope=project` подмешивает путь workspace, поэтому факты проекта не
  перепутываются с личными;
* `add()` отклоняет пустой текст, `update()` — правку чужого id;
* `recall(query, limit)` — поиск по тексту и тегам с жёстким лимитом: в промпт
  попадает ограниченное число фактов, а не вся память.

Память — часть `ChatSession`: у клиента (`axiom/client.py`) ровно один
`MemoryStore`, инструменты регистрируются в общий `ToolRegistry`, а
`ChatSession.config()` показывает активную память в `/config`. Очистка памяти
проекта при выходе из него выполняется на уровне session, чтобы не осталось
смешанных фактов.

## Память (Memory)

`axiom/core/memory.py` — модель работает с памятью **только через три
инструмента**: `memory_write`, `memory_read`, `memory_forget` (все
`Permission.ALWAYS`). Прямой записи в файл из других мест нет: `MemoryStore` —
единственный владелец `~/.axiom/memory.json` (атомарная запись + `fcntl.flock`,
повреждённый файл не роняет ядро).

* `MemoryItem` — факт с `scope` (`global`/`project`/`user`) и `tags`;
  `scope=project` подмешивает путь workspace, поэтому факты проекта не
  перепутываются с личными;
* `add()` отклоняет пустой текст, `update()` — правку чужого id;
* `recall(query, limit)` — поиск по тексту и тегам с жёстким лимитом: в промпт
  попадает ограниченное число фактов, а не вся память.

Память — часть `ChatSession`: у клиента (`axiom/client.py`) ровно один
`MemoryStore`, инструменты регистрируются в общий `ToolRegistry`, а
`ChatSession.config()` показывает активную память в `/config`. Очистка памяти
проекта при выходе из него выполняется на уровне session, чтобы не осталось
смешанных фактов.

## Context-сборщик сессии (session.py)

`axiom/core/session.py` — **сборщик контекста сессии**: хранит историю, системный
промпт, переменные и метаданные (cwd, модель, профиль), и по запросу отдаёт
`ContextBundle` — готовый к отправке набор сообщений с обрезкой по лимиту токенов.
`SessionState`/`ContextBundle` — модели состояния и сборки.

Переменные и метаданные проекта хранятся в `session`, а не в `cwd`: `cwd` — это
рабочая директория процесса, а не признак проекта, поэтому `set_project()` /
`clear_project()` вводят и выводят проект отдельно, не трогая `cwd`. Выход из
проекта при выходе из него выполняется на уровне session, чтобы не осталось
смешанных фактов.

### Связь с остальными модулями

* `axiom/cli.py` строит `Session` один раз и передаёт её в `ChatClient` и
  `ChatRenderer`, поэтому история и переменные не дублируются в layers;
* `axiom/core/streaming.py` складывает собранные `ChatChunk` в
  `Session.append_assistant()`, а `axiom/core/prompt.py` читает
  `Session.system_prompt` — слои не знают друг о друге;
* `axiom/core/session.py` не импортирует `cli` и `layers`: слои собираются на
  уровне `axiom/cli.py`.

## Streaming-парсер Ollama

`axiom/core/ollama.py::ChatStreamParser` — адаптивный разбор NDJSON
`/api/chat`:

* `message.thinking` — авторитетный reasoning;
* legacy-модели: `<think>...</think>` внутри content, включая частичные теги
  на границах чанков (буферизация + `flush()`);
* `message.tool_calls` → `ToolCallRequest` (arguments строкой → JSON);
* финальный `done`-чанк → метрики (`eval_count`, `eval_duration`, ...);
* ошибки: `InvalidResponseError` на мусор, `OllamaUnavailableError` на обрыв;
  неизвестные поля игнорируются, поток не падает.

## Модели и capabilities

`axiom/core/models.py::ModelRegistry` читает `/api/tags`. Из
`capabilities: ["completion", "tools", "thinking", "vision"]` строится
`ModelInfo.supports()`: `True/False` — если Ollama сообщила, `None` (`unknown`)
— если нет. Reasoning включается по реальной capability (или по явному
`think` из конфига), а не по названию модели.

## Персистентность

* `Config` — атомарная запись JSON (`*.json.tmp` → replace), устойчива к
  мусору: невалидные поля отбрасываются.
* `HistoryStore` (W2.6) — один `history.db` (SQLite) на область (глобальную
  или на проект) вместо файла JSON на разговор. Полнотекстовый поиск идёт через
  FTS5; если сборка SQLite без FTS5, поиск честно откатывается на скан в Python.
  Публичный API (`save`/`list`/`show`/`load`/`delete`/`search`/`rename`/
  `set_meta`/`set_limit`/`use_workspace`/`directory`) не изменился, `show`
  по-прежнему возвращает тот же отступованный JSON. При первом открытии
  выполняется идемпотентный импорт старых `*.json`: оригиналы переносятся в
  `migrated_json/` (остаются читаемыми), повторный запуск ничего не делает.
  Повреждённые строки пропускаются при листинге; разговор сохраняется после
  каждого завершённого оборота (включая частичный вывод при отмене).

