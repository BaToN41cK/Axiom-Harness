# Создание плагинов

Плагин AXIOM — это папка с `manifest.json` и точкой входа `plugin.py`, которая
добавляет агенту **реальные инструменты** (tools). После установки инструменты
плагина становятся доступны модели в том же диалоге — без перезапуска ядра.

Встроенные плагины (`calculator`, `datetime`, `notes`, `security`, `texttools`)
собраны по тому же контракту и лежат в `src/axiom/plugins/bundled/` — их можно
использовать как готовые примеры.

---

## 1. Структура плагина

```
my-plugin/
├─ manifest.json     # обязательный — метаданные и объявление возможностей
├─ plugin.py         # точка входа с инструментами (имя можно поменять в manifest.entry)
└─ README.md         # необязательный — документация, видимая в TUI и Desktop
```

Минимум — `manifest.json` + `plugin.py`. `README.md` добавлять стоит: он
показывается в AXIOM по клавише `?` (TUI) или кнопкой «Показать документацию»
(Desktop).

## 2. manifest.json

Все поля, кроме `name`, необязательны. Поле `api_version` обязано совпадать с
версией API AXIOM (сейчас `1`) — плагин с другой версией **не запустится**.

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "Короткое описание: что умеет плагин и когда его включать.",
  "author": "Ваше имя",
  "api_version": 1,
  "capabilities": ["tools"],
  "tools": ["hello", "hello_world"],
  "providers": [],
  "skills": [],
  "events": [],
  "ui": [],
  "entry": "plugin.py",
  "enabled": true
}
```

| Поле | Тип | Назначение |
|---|---|---|
| `name` | string, обязательное | Имя папки и идентификатор плагина. Только латиница, цифры, `.`, `_`, `-` (до 64 символов) |
| `version` | string | Версия, показывается в списке (`v1.0.0`) |
| `description` | string | Короткое описание — показывается в списке плагинов |
| `author` | string | Автор — показывается в карточке и в TUI |
| `api_version` | integer | Версия контракта плагинов. Должна быть равна `1` |
| `capabilities` | string[] | Что добавляет плагин: `tools`, `providers`, `skills`, `events`, `ui` |
| `tools` | string[] | Имена инструментов — отображаются в UI и служат самодокументацией |
| `providers`, `skills`, `events`, `ui` | string[] | Дополнительные декларации (для будущих типов плагинов) |
| `entry` | string | Файл точки входа внутри папки. По умолчанию `plugin.py`. Должен оставаться внутри папки (без `..` и абсолютных путей) |
| `enabled` | boolean | Состояние «включён» при установке. Меняется из UI и сохраняется |

## 3. plugin.py — два способа добавить инструменты

Точка входа может использовать **один из двух** контрактов.

### Способ 1: декларативный — `TOOLS` + `HANDLERS`

Проще всего: список определений инструментов и словарь async-обработчиков.

```python
# plugin.py
from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult

TOOLS = [
    ToolDefinition(
        name="hello",
        description="Поздороваться с пользователем.",
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Имя, с которым поздороваться.",
                },
            },
            "required": [],
        },
        permission=ToolPermission.ALWAYS,
        max_output=400,
    ),
]


async def hello(name: str = "мир") -> ToolResult:
    return ToolResult(name="hello", ok=True, content=f"Привет, {name}!")


HANDLERS = {"hello": hello}
```

Правила декларативного контракта:

- каждому имени в `TOOLS` должен соответствовать handler в `HANDLERS`, иначе
  плагин отклоняется с ошибкой `no handler for tool '<имя>'`;
- handler — это `async def`, принимающий аргументы, описанные в `parameters`,
  и возвращающий `ToolResult`;
- ошибку не надо бросать: верните `ToolResult(ok=False, error="…")`.

### Способ 2: императивный — `register(registry)`

Максимальная гибкость: регистрируйте что угодно прямо в реестре. Если в модуле
есть `register`, используется только он (`TOOLS`/`HANDLERS` игнорируются).

```python
# plugin.py
from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult


async def ping() -> ToolResult:
    return ToolResult(name="ping", ok=True, content="pong")


def register(registry) -> None:
    registry.register(
        ToolDefinition(
            name="ping",
            description="Ответить 'pong'.",
            parameters={"type": "object", "properties": {}, "required": []},
            permission=ToolPermission.ALWAYS,
        ),
        ping,
    )
```

`registry` здесь — `ToolRegistry` из `axiom.core.tools.registry`; у него есть
`register(definition, handler)`, `unregister(name)` и `names`.


## 4. ToolDefinition — что можно настроить

| Поле | Значение по умолчанию | Назначение |
|---|---|---|
| `name` | — | Имя инструмента, которое видит модель |
| `description` | — | Описание для модели: **чем точнее, тем чаще модель вызовет инструмент правильно** |
| `parameters` | `{}` | JSON-schema аргументов (тот же формат, что у Ollama/OpenAI) |
| `permission` | `ASK` | `ALWAYS` — выполнять сразу; `ASK` — спрашивать разрешение; `NEVER` — выключить |
| `risk` | `safe` | Подсказка для аудита/UI: `safe` / `medium` / `dangerous` |
| `timeout` | `None` | Бюджет времени в секундах (`None` — без лимита) |
| `max_output` | `None` | Жёсткий потолок длины результата для модели, в символах |
| `streaming` | `False` | Инструмент умеет отдавать частичный результат |
| `cancellable` | `True` | Поддерживает кооперативную отмену |
| `dry_run` | `False` | Есть режим предпросмотра без изменений |
| `rollback` | `none` | Как откатить изменение: `none` / `checkpoint` / `undo` / `file` |
| `workspace_scoped` | `False` | Инструмент имеет смысл только внутри workspace |

## 5. ToolResult

Обработчик возвращает `ToolResult`:

```python
ToolResult(
    name="hello",        # имя инструмента
    ok=True,             # True — успех, False — ошибка
    content="Привет!",   # текст, который увидит модель (обязательный при ok=True)
    error=None,          # текст ошибки при ok=False
    duration_ms=0,       # сколько заняло выполнение (для метрик)
)
```

## 6. README.md — документация плагина

Положите `README.md` рядом с `manifest.json` — AXIOM загрузит его
автоматически. Формат — Markdown: заголовки, таблицы, примеры.

- **TUI**: `/plugins` → выберите плагин стрелками → `?` (или кнопка Info);
- **Desktop**: Настройки → Плагины → кнопка «Показать документацию» в карточке.

Краткое описание показывается в списке из `description`, а README — полная
документация. Пишите, что плагин умеет, какие инструменты добавляет, какие
параметры у них и как выглядят результаты — по образцу встроенных плагинов.

## 7. Установка

### TUI

1. Откройте `/plugins`.
2. Для установки из папки: введите путь в поле внизу панели и нажмите `i`
   (или кнопку Install…). Подсказка клавиш — в рамке панели.
3. Для встроенного плагина из каталога: выберите его стрелками и нажмите `i`.

### Desktop

Настройки → Плагины → «Установить из папки» и выберите папку плагина.
Встроенные плагины ставятся одной кнопкой «Установить» в каталоге ниже.

### Вручную

Скопируйте папку в каталог плагинов:

```text
~/.axiom/plugins/<имя-плагина>/
├─ manifest.json
├─ plugin.py
└─ README.md
```

Плагин будет обнаружен при следующем запуске или при перечитывании списка
(в TUI список плагинов перечитывает диск при открытии `/plugins`).

## 8. Управление

- **Включить/выключить** — Enter по плагину в TUI или переключатель в Desktop.
  Выключенный плагин остаётся на диске, но его код не загружается, а
  инструменты исчезают из реестра.
- **Удалить** — `d` в TUI или кнопка «Удалить» в Desktop. Папка удаляется с
  диска, плагин забывается. Встроенный плагин после удаления возвращается в
  каталог «встроенные, не установлены».
- **Обновить** — повторная установка из той же папки: статус `updated`, прежнее
  состояние `enabled` сохраняется, старые инструменты выгружаются до загрузки
  новых.

## 9. Безопасность и ограничения

- Код плагина исполняется **в процессе AXIOM с его правами** — песочницы нет.
  Устанавливайте только код, которому доверяете.
- Плагин с несовместимым `api_version` отклоняется **до** импорта кода.
- Точка входа не может выйти за пределы папки плагина.
- Имя плагина ограничено безопасным набором символов — это же имя папки в
  `~/.axiom/plugins/`.
- Плагин без точки входа (только `manifest.json`) допустим: он декларирует
  capabilities/skills без исполняемого кода.

## 10. Частые ошибки

| Ошибка | Причина и решение |
|---|---|
| `Plugin manifest is missing a name` | В `manifest.json` нет `name` |
| `Plugin name must contain only letters…` | В имени недопустимые символы (кириллица, пробелы, `/`) |
| `targets API v…, but AXIOM supports v1` | Несовпадение `api_version` |
| `no handler for tool '…'` | В `TOOLS` есть имя, которого нет в `HANDLERS` |
| `Plugin '…' failed to register: …` | Исключение при выполнении `register()`/сборке инструментов |
| `Plugin folder does not exist` / `No manifest.json found` | При установке указана не папка плагина |
| Плагин не появляется в списке | Проверьте, что папка лежит в `~/.axiom/plugins/` и открыт свежий список (закрыть/открыть `/plugins`) |
| Инструмент не предлагается моделью | Уточните `description` в `ToolDefinition` и проверьте, что плагин включён |


