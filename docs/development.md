# Разработка

## Окружение

```bash
git clone https://github.com/BaToN41cK/Axiom-Harness.git
cd Axiom-Harness
pip install -e ".[dev]"
```

Запуск из исходников без установки не требуется: editable-установка
регистрирует пакет и entry point `axiom`.

```bash
axiom                     # TUI
axiom --gui               # десктопный GUI (Tauri-приложение в desktop/)
pytest                    # тесты
```

## Правила, которые нельзя нарушать

1. **Один пакет** — `axiom`, всё внутри `src/axiom/` (src-layout).
2. **`core/` не импортирует UI** — ни `textual`, ни `rich`, ни `pyqt`.
   Контролируется тестом `tests/core/test_no_ui_imports.py`.
3. **Фронтенды не импортируют друг друга** — `tui` не знает про `gui`.
4. **`shared/` — только данные**: палитра, глифы, логотип, форматтеры.
   Никакого I/O и состояния.
5. **`__main__.py` — единственное место выбора фронтенда.**
6. **REAL FIRST** — никаких моков и заглушек в production flow; незавершённая
   функция честно сообщает о недоступности.
7. **Не ломать работающее** — `inspect → understand → change → test`
   (правило §50 исходной спецификации).

## Проверки перед коммитом

```bash
ruff check src tests            # линт — обязателен, 0 замечаний
ruff format --check src tests   # формат — пока ЦЕЛЬ, не gate: 19 существующих файлов
                                # ещё не приведены к ruff-формату (см. TODO §4)
pytest -q                       # тесты — обязательны, 0 падений
pyright src tests               # статические типы (тот же движок, что Pylance)
```

`pyright` объявлен в `.[dev]` (вместе с `ruff`), потому что ошибки редактора
— это те же диагностики, и держать 0 ошибок нужно воспроизводимо из чистого
окружения. Именно так был найден реальный баг в
`frontends/tui/widgets/panels.py` (пропущенный `+` превращал f-строку в вызов
и `/settings` падал).

## Тестовая инфраструктура

`pyproject.toml` уже настроен: `pytest`, `asyncio_mode = "auto"`,
`testpaths = ["tests"]`. Существующий набор:

```text
tests/core/test_ollama_parser.py   reasoning/content, legacy thinking, чанки, метрики
tests/core/test_state_machine.py   переходы, финалы, reset
tests/core/test_chat.py            send-поток, cancel, empty-answer, история
tests/core/test_send_config.py     temperature/system/vision доезжают до Ollama
tests/core/test_pasted_links.py    ссылки читаются без tool-calling
tests/core/test_tools_registry.py  permissions, неизвестный tool, исключения
tests/core/test_no_ui_imports.py   core не тянет UI-фреймворки
tests/live/test_ollama_live.py     живой Ollama (opt-in: AXIOM_LIVE_OLLAMA=1)
```

Живые проверки против настоящей Ollama (сеть, модели, tool-calling) — только
в `tests/live/` под `@pytest.mark.ollama` и включаются явным
`AXIOM_LIVE_OLLAMA=1`; по умолчанию пропускаются. Разовые скрипты и логи в
корне репозитория не оставляем.

## Как добавить инструмент (tool)

1. Опишите `ToolDefinition` (name, description, JSON-schema, permission)
   в `axiom/core/tools/<имя>.py`.
2. Реализуйте async-обработчик, возвращающий `ToolResult`.
3. Зарегистрируйте в `ToolRegistry` (см. `WebSearchTool.register`).
4. UI менять **не нужно**: фронтенды рендерят `ToolCallEvent`/`ToolResultEvent`
   и `StatusChange(detail=...)`-generic.

```python
definition = ToolDefinition(
    name="my_tool",
    description="What it does (for the model).",
    parameters={"type": "object", "properties": {...}, "required": [...]},
    permission=ToolPermission.ALWAYS,   # ASK — потребует явного разрешения позже
)
registry.register(definition, my_handler)
```

## Как добавить фронтенд

Контракт — :class:`~axiom.core.chat.ChatSession`: конструктор принимает
`Config`, `send()` возвращает поток `ChatEvent`, `cancel()` останавливает
генерацию. Реализация может быть на чём угодно (TUI, Tauri-десктоп в
`desktop/`) — ядро менять не придётся.

## Стиль и практики

* Типизация везде (`from __future__ import annotations`), pydantic для
  событий/конфига/истории.
* Доменные ошибки — наследники `AxiomError` (message + hint); наружу не
  просачивается ни traceback.
* Долгие операции — только `async`/workers; UI никогда не блокируется.
* Статусы — проекции `GenerationState`; парсинг ответа не доверяет формату
  (адаптивный parser + empty-answer protection).
* Cleanup-чеклист перед релизом — §51 исходной спецификации: без
  TODO/FIXME/MOCK/DEMO/PLACEHOLDER в ключевых функциях, без мёртвого кода.

## Навигация по коду

| Хочешь понять… | Смотри |
|---|---|
| как стримится ответ | `core/ollama.py` (клиент + парсер) → `core/agent.py` (`_stream_pass`) |
| откуда берутся статусы | `core/state_machine.py`, `core/agent.py` (`_status`) |
| как работает поиск | `core/search/duckduckgo.py`, `core/tools/web_search.py`, `core/agent.py` (`_execute_tool`, `_read_sources`) |
| как TUI подписан на ядро | `frontends/tui/app.py` (`_dispatch_event`) |
| как устроены панели | `frontends/tui/widgets/panels.py` |
| как работают инструменты | `core/tools/registry.py`, `core/agent.py` (`_execute_tool`, `OFFERED_TOOLS`) |
| почему ссылка из вопроса читается сама | `core/agent.py` (`_urls_in_text`, `_read_pasted_links`) |
| где сохраняются разговоры | `core/history.py` |
