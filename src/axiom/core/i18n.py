"""Localization primitives (W3.8).

A small, deterministic catalog of the strings the *core* emits — task states,
permission outcomes and autonomy labels — so both frontends can render the same
surface in English or Russian. ``translate`` falls back to the key itself for
anything not yet catalogued, so an untranslated string degrades to an identifier
instead of crashing or silently switching language.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class Locale(str, Enum):
    EN = "en"
    RU = "ru"


DEFAULT_LOCALE = Locale.EN

TRANSLATIONS: dict[str, dict[str, str]] = {
    # Task states (W4.1)
    "task.pending": {"en": "Pending", "ru": "Ожидает"},
    "task.analyzing": {"en": "Analyzing", "ru": "Анализ"},
    "task.planning": {"en": "Planning", "ru": "Планирование"},
    "task.executing": {"en": "Executing", "ru": "Выполнение"},
    "task.verifying": {"en": "Verifying", "ru": "Проверка"},
    "task.completed": {"en": "Completed", "ru": "Завершено"},
    "task.failed": {"en": "Failed", "ru": "Ошибка"},
    "task.cancelled": {"en": "Cancelled", "ru": "Отменено"},
    "task.waiting_for_user": {"en": "Waiting for user", "ru": "Ожидание пользователя"},
    # Permission outcomes (W2.4)
    "permission.allow_once": {"en": "Allow once", "ru": "Разрешить один раз"},
    "permission.allow_always": {"en": "Always allow", "ru": "Всегда разрешать"},
    "permission.deny": {"en": "Deny", "ru": "Запретить"},
    # Autonomy presets (W4.9)
    "autonomy.plan": {"en": "Plan", "ru": "План"},
    "autonomy.edit": {"en": "Edit", "ru": "Правка"},
    "autonomy.auto": {"en": "Auto", "ru": "Авто"},
    "autonomy.full": {"en": "Full", "ru": "Полный"},
    # Navigation tabs + topbar (W3.8 slice: App side-tabs and header only).
    # The Desktop renders these via `Config.locale` through the `i18n` bridge
    # command; the core catalog stays the single source of truth.
    "ui.tabs.files": {"en": "Files", "ru": "Файлы"},
    "ui.tabs.terminal": {"en": "Terminal", "ru": "Терминал"},
    "ui.tabs.git": {"en": "Git", "ru": "Git"},
    "ui.tabs.tasks": {"en": "Tasks", "ru": "Задачи"},
    "ui.tabs.documents": {"en": "Documents", "ru": "Документы"},
    "ui.panel.resize": {"en": "Resize panel", "ru": "Изменить размер панели"},
    "ui.sidebar.toggle": {"en": "Show / hide panel L (Ctrl+B)", "ru": "Панель показать, скрыть L (Ctrl+B)"},
    "ui.panel.toggle_right": {"en": "Show / hide panel R", "ru": "Панель показать, скрыть R"},
    "ui.topbar.route": {"en": "Current route", "ru": "Текущий маршрут"},
    "ui.topbar.no_model": {"en": "no model selected", "ru": "модель не выбрана"},
    "ui.topbar.tools_on": {"en": "Tools enabled", "ru": "Tools включены"},
    "ui.topbar.tools_off": {"en": "Text only", "ru": "Только текст"},
    "ui.topbar.theme": {"en": "Theme: {current} · Switch to {next}", "ru": "Тема: {current} · Переключить на {next}"},
    "ui.topbar.theme_aria": {"en": "Theme {current}. Switch to {next}", "ru": "Тема {current}. Переключить на {next}"},
    # Slash-command palette (W3.8 slice: lib/commands.ts descriptions + hints).
    "ui.cmd.help": {"en": "Command and hotkey reference", "ru": "Справка по командам и горячим клавишам"},
    "ui.cmd.new": {"en": "New chat", "ru": "Новый чат"},
    "ui.cmd.clear": {"en": "Clear current conversation", "ru": "Очистить текущий разговор"},
    "ui.cmd.history": {"en": "Conversation history", "ru": "История разговоров"},
    "ui.cmd.model": {"en": "Switch model", "ru": "Переключить модель"},
    "ui.cmd.models": {"en": "Models, capabilities, status", "ru": "Модели, возможности, состояние"},
    "ui.cmd.permissions": {
        "en": "Permission mode: ask, auto_approve_safe, auto_approve_all",
        "ru": "Режим разрешений: ask, auto_approve_safe, auto_approve_all",
    },
    "ui.cmd.profiles": {"en": "System prompt profiles", "ru": "Системные prompt-профили"},
    "ui.cmd.memory": {
        "en": "Memory: facts and preferences (add/remove)",
        "ru": "Память: факты и предпочтения (добавить/удалить)",
    },
    "ui.cmd.knowledge": {
        "en": "Knowledge base: collections, indexing, cited search",
        "ru": "База знаний: коллекции, индексация, поиск с цитатами",
    },
    "ui.cmd.trajectory": {
        "en": "Run timeline, tools, tokens and timing",
        "ru": "Timeline запуска, tools, tokens и timing",
    },
    "ui.cmd.providers": {
        "en": "Providers, API key, Test and model selection",
        "ru": "Провайдеры, API-ключ, Test и выбор модели",
    },
    "ui.cmd.agents": {
        "en": "Agents, orchestrator and assigned models",
        "ru": "Агенты, оркестратор и назначенные модели",
    },
    "ui.cmd.plugins": {
        "en": "Install and manage custom plugins",
        "ru": "Установка и управление пользовательскими плагинами",
    },
    "ui.cmd.orchestrate": {
        "en": "Run a task via ANALYST, CODER, DEBUGGER, TESTER and REVIEWER",
        "ru": "Запустить задачу через ANALYST, CODER, DEBUGGER, TESTER и REVIEWER",
    },
    "ui.cmd.context": {"en": "Context: tokens, messages, files", "ru": "Контекст: токены, сообщения, файлы"},
    "ui.cmd.search": {"en": "Web search with sourced answers", "ru": "Веб-поиск и ответ по источникам"},
    "ui.cmd.tools": {"en": "Agent tools", "ru": "Инструменты агента"},
    "ui.cmd.status": {"en": "Ollama, model and core status", "ru": "Состояние Ollama, модели и ядра"},
    "ui.cmd.settings": {"en": "AXIOM settings", "ru": "Настройки AXIOM"},
    "ui.cmd.exit": {"en": "Quit AXIOM", "ru": "Закрыть AXIOM"},
    "ui.cmd.arg.name": {"en": "[name]", "ru": "[name]"},
    "ui.cmd.arg.task": {"en": "task", "ru": "задача"},
    "ui.cmd.arg.query": {"en": "query", "ru": "query"},
    # Shortcut labels (lib/commands.ts SHORTCUTS + SettingsModal table).
    "ui.shortcut.send": {"en": "Send message", "ru": "Отправить сообщение"},
    "ui.shortcut.newline": {"en": "New line", "ru": "Перенос строки"},
    "ui.shortcut.send_search": {"en": "Send with forced web search", "ru": "Отправить с принудительным веб-поиском"},
    "ui.shortcut.palette": {"en": "Command palette (in an empty input)", "ru": "Палитра команд (в пустом поле ввода)"},
    "ui.shortcut.stop": {"en": "Stop generation / close panel", "ru": "Остановить генерацию / закрыть панель"},
    "ui.shortcut.new": {"en": "New chat", "ru": "Новый чат"},
    "ui.shortcut.new_conversation": {"en": "New conversation", "ru": "Новый разговор"},
    "ui.shortcut.panel": {"en": "Show/hide sidebar", "ru": "Показать/скрыть боковую панель"},
    "ui.shortcut.history_search": {"en": "History search", "ru": "Поиск по истории"},
    "ui.shortcut.history_search_pl": {"en": "Search conversations", "ru": "Поиск по разговорам"},
    "ui.shortcut.chat_search": {"en": "Search current conversation", "ru": "Поиск по текущему разговору"},
    "ui.shortcut.settings": {"en": "Settings", "ru": "Настройки"},
    "ui.shortcut.focus_input": {"en": "Focus the input", "ru": "Фокус в поле ввода"},
    "ui.shortcut.edit_last": {
        "en": "In an empty input — edit the last message",
        "ru": "В пустом поле — редактировать прошлое сообщение",
    },
    "ui.shortcut.copy": {"en": "Copy the selected answer", "ru": "Копировать выделенный ответ"},
    "ui.shortcut.paste_image": {"en": "Paste image (vision models)", "ru": "Вставить изображение (vision-модели)"},
    "ui.shortcut.close": {"en": "Stop generation / close window", "ru": "Остановить генерацию / закрыть окно"},
    "ui.shortcut.send_web": {"en": "Send with web search", "ru": "Отправить с веб-поиском"},
    # Tool labels (useAxiom.helpers.ts toolLabel).
    "ui.tool.web_search": {"en": "Web search", "ru": "Веб-поиск"},
    "ui.tool.fetch_url": {"en": "Page reader", "ru": "Чтение страницы"},
    "ui.tool.list_files": {"en": "Folder view", "ru": "Просмотр папки"},
    "ui.tool.read_file": {"en": "File reader", "ru": "Чтение файла"},
    "ui.tool.write_file": {"en": "File writer", "ru": "Запись файла"},
    "ui.tool.edit_file": {"en": "Editing", "ru": "Редактирование"},
    "ui.tool.search_text": {"en": "Code search", "ru": "Поиск по коду"},
    "ui.tool.search_files": {"en": "File search", "ru": "Поиск файлов"},
    "ui.tool.run_command": {"en": "Terminal", "ru": "Терминал"},
    "ui.tool.inspect_project": {"en": "Project inspection", "ru": "Осмотр проекта"},
    "ui.tool.git": {"en": "Git", "ru": "Git"},
    # Verification tools (§34) — their own card kind in the chat timeline.
    "ui.tool.run_tests": {"en": "Running tests", "ru": "Запуск тестов"},
    "ui.tool.run_linter": {"en": "Running linter", "ru": "Запуск линтера"},
    "ui.tool.build_project": {"en": "Building project", "ru": "Сборка проекта"},
    "ui.tool.verify_changes": {"en": "Running checks", "ru": "Запуск проверок"},
    # Tool live-status lines (toolStatusText); {target} is the query/path/command.
    "ui.toolstatus.searching": {"en": "Searching: «{target}»", "ru": "Ищет: «{target}»"},
    "ui.toolstatus.searching_plain": {"en": "Searching the web…", "ru": "Ищет в интернете…"},
    "ui.toolstatus.reading_page": {"en": "Reading: {target}", "ru": "Читает: {target}"},
    "ui.toolstatus.reading_page_plain": {"en": "Reading page…", "ru": "Читает страницу…"},
    "ui.toolstatus.browsing": {"en": "Viewing folder: {target}", "ru": "Смотрит папку: {target}"},
    "ui.toolstatus.browsing_plain": {"en": "Browsing files…", "ru": "Смотрит файлы…"},
    "ui.toolstatus.reading_file": {"en": "Reading: {target}", "ru": "Читает: {target}"},
    "ui.toolstatus.reading_file_plain": {"en": "Reading file…", "ru": "Читает файл…"},
    "ui.toolstatus.writing_file": {"en": "Writing: {target}", "ru": "Пишет: {target}"},
    "ui.toolstatus.writing_file_plain": {"en": "Writing file…", "ru": "Пишет файл…"},
    "ui.toolstatus.editing": {"en": "Editing: {target}", "ru": "Правит: {target}"},
    "ui.toolstatus.editing_plain": {"en": "Editing…", "ru": "Редактирует…"},
    "ui.toolstatus.searching_project": {"en": "Searching: «{target}»", "ru": "Ищет: «{target}»"},
    "ui.toolstatus.searching_project_plain": {"en": "Searching the project…", "ru": "Ищет по проекту…"},
    "ui.toolstatus.running": {"en": "Running: {target}", "ru": "Выполняет: {target}"},
    "ui.toolstatus.running_plain": {"en": "Running command…", "ru": "Выполняет команду…"},
    "ui.toolstatus.checks": {"en": "Running checks…", "ru": "Запускает проверки…"},
    "ui.toolstatus.git": {"en": "Git…", "ru": "Git…"},
    # Orchestration live status (orchestrationProgress); {actor}/{summary} vary.
    "ui.orch.plan": {"en": "Orchestration: planning…", "ru": "Оркестрация: план…"},
    "ui.orch.agent_run": {"en": "Orchestration: {actor} is working…", "ru": "Оркестрация: {actor} выполняет задачу…"},
    "ui.orch.agent_done": {"en": "Orchestration: {actor} done", "ru": "Оркестрация: {actor} готов"},
    "ui.orch.agent_failed": {"en": "Orchestration: {actor} — failed", "ru": "Оркестрация: {actor} — ошибка"},
    "ui.orch.model": {"en": "Orchestration: {actor} → {summary}", "ru": "Оркестрация: {actor} → {summary}"},
    "ui.orch.reasoning": {"en": "Orchestration: {actor} is thinking…", "ru": "Оркестрация: {actor} — думает…"},
    "ui.orch.answer": {"en": "Orchestration: {actor} is writing…", "ru": "Оркестрация: {actor} — пишет…"},
    "ui.orch.tool": {"en": "Orchestration: {actor} — {summary}", "ru": "Оркестрация: {actor} — {summary}"},
    "ui.orch.review": {"en": "Orchestration: review…", "ru": "Оркестрация: review…"},
    "ui.orch.verification": {"en": "Orchestration: verification…", "ru": "Оркестрация: verification…"},
    "ui.orch.done": {"en": "Orchestration: complete", "ru": "Оркестрация: завершена"},
    "ui.orch.cancelled": {"en": "Orchestration stopped", "ru": "Оркестрация остановлена"},
    "ui.orch.failed": {"en": "Orchestration: failed", "ru": "Оркестрация: сбой"},
    # Help overlay chrome (OverlayPanel).
    "ui.help.commands": {"en": "Commands", "ru": "Команды"},
    "ui.help.shortcuts": {"en": "Shortcuts", "ru": "Клавиши"},
    "ui.help.note": {
        "en": "AXIOM runs locally via Ollama: reasoning, tools, sources and metrics "
        "are shown only when the backend really returned them.",
        "ru": "AXIOM работает локально через Ollama: reasoning, инструменты, источники и метрики "
        "показываются только тогда, когда их действительно вернул бэкенд.",
    },
    # Generation status pill (useAxiom applyStatus).
    "ui.status.thinking": {"en": "Thinking…", "ru": "Размышляет…"},
    "ui.status.connecting": {"en": "Connecting to {detail}…", "ru": "Подключается к {detail}…"},
    "ui.status.connecting_plain": {"en": "Connecting…", "ru": "Подключается…"},
    "ui.status.tool": {"en": "Tool", "ru": "Инструмент"},
    "ui.status.permission_wait": {"en": "Waiting for approval: {tool}", "ru": "Ожидает разрешения: {tool}"},
    # Task live states as shown in status text and toasts (progressive verbs,
    # distinct from the nominal `task.*` core states).
    "ui.task.label": {"en": "Task", "ru": "Задача"},
    "ui.task.background": {"en": "Background task", "ru": "Фоновая задача"},
    "ui.task.state.pending": {"en": "Ready to start", "ru": "готова к запуску"},
    "ui.task.state.analyzing": {"en": "Analyzing project", "ru": "анализирует проект"},
    "ui.task.state.planning": {"en": "Composing plan", "ru": "составляет план"},
    "ui.task.state.executing": {"en": "Running step", "ru": "выполняет шаг"},
    "ui.task.state.waiting_for_permission": {"en": "Waiting for approval", "ru": "ожидает разрешения"},
    "ui.task.state.verifying": {"en": "Verifying result", "ru": "проверяет результат"},
    "ui.task.state.waiting_for_user": {"en": "Needs a decision", "ru": "требует решения"},
    "ui.task.state.completed": {"en": "completed", "ru": "завершена"},
    "ui.task.state.failed": {"en": "failed with an error", "ru": "завершилась с ошибкой"},
    "ui.task.state.cancelled": {"en": "stopped", "ru": "остановлена"},
    # Composer palette chrome + @-mention chips.
    "ui.palette.head": {"en": "COMMANDS", "ru": "КОМАНДЫ"},
    "ui.palette.foot": {"en": "select · ↑↓ navigate · Esc close", "ru": "выбрать · ↑↓ навигация · Esc закрыть"},
    "ui.composer.files_in_prompt": {"en": "Files in the prompt", "ru": "Файлы в запросе"},
    "ui.composer.remove_mention": {"en": "Remove @{file}", "ru": "Убрать @{file}"},
    # Tool-activity summary groups + counts (ToolActivity Overview/summarize).
    "ui.toolgroup.read": {"en": "Reading", "ru": "Чтение"},
    "ui.toolgroup.edit": {"en": "Edits", "ru": "Правки"},
    "ui.toolgroup.search": {"en": "Search", "ru": "Поиск"},
    "ui.toolgroup.run": {"en": "Runs", "ru": "Запуск"},
    "ui.toolgroup.checks": {"en": "Checks", "ru": "Проверки"},
    "ui.toolgroup.check_passed": {"en": "PASSED", "ru": "ПРОЙДЕНО"},
    "ui.toolgroup.check_failed": {"en": "FAILED", "ru": "ПРОВАЛЕНО"},
    "ui.orch.no_model": {"en": "no model assigned", "ru": "модель не назначена"},
    "ui.summary.lines": {"en": "lines {s}–{e}", "ru": "строки {s}–{e}"},
    "ui.summary.lines_from": {"en": "lines {s}+", "ru": "строки {s}+"},
    "ui.summary.line.one": {"en": "{n} line", "ru": "{n} строка"},
    "ui.summary.line.few": {"en": "{n} lines", "ru": "{n} строки"},
    "ui.summary.line.many": {"en": "{n} lines", "ru": "{n} строк"},
    "ui.summary.match.one": {"en": "{n} match", "ru": "{n} совпадение"},
    "ui.summary.match.few": {"en": "{n} matches", "ru": "{n} совпадения"},
    "ui.summary.match.many": {"en": "{n} matches", "ru": "{n} совпадений"},
    "ui.summary.item.one": {"en": "{n} item", "ru": "{n} элемент"},
    "ui.summary.item.few": {"en": "{n} items", "ru": "{n} элемента"},
    "ui.summary.item.many": {"en": "{n} items", "ru": "{n} элементов"},
    "ui.summary.in_glob": {"en": "in {glob}", "ru": "в {glob}"},
    # Settings chrome (W3.8 settings slice).
    "ui.settings.language": {"en": "Language", "ru": "Язык"},
    "ui.settings.language_hint": {"en": "Interface language", "ru": "Язык интерфейса"},
    # Tool-activity overview chips (ToolActivity Overview).
    "ui.toolgroup.web": {"en": "Web", "ru": "Веб"},
    "ui.overview.working": {"en": "Agent is working", "ru": "Агент работает"},
    "ui.overview.actions": {"en": "Agent actions", "ru": "Действия агента"},
    "ui.overview.error.one": {"en": "{n} error", "ru": "{n} ошибка"},
    "ui.overview.error.few": {"en": "{n} errors", "ru": "{n} ошибки"},
    "ui.overview.error.many": {"en": "{n} errors", "ru": "{n} ошибок"},
    # Tool-activity bodies (CodeLines / SearchBody / TerminalBody / summarize).
    "ui.summary.collapse": {"en": "Collapse", "ru": "Свернуть"},
    "ui.summary.more.one": {"en": "Show {n} more line", "ru": "Показать ещё {n} строку"},
    "ui.summary.more.few": {"en": "Show {n} more lines", "ru": "Показать ещё {n} строки"},
    "ui.summary.more.many": {"en": "Show {n} more lines", "ru": "Показать ещё {n} строк"},
    "ui.summary.more_files.one": {"en": "and {n} more file", "ru": "и ещё {n} файл"},
    "ui.summary.more_files.few": {"en": "and {n} more files", "ru": "и ещё {n} файла"},
    "ui.summary.more_files.many": {"en": "and {n} more files", "ru": "и ещё {n} файлов"},
    "ui.summary.more_hits": {"en": "{k} more", "ru": "ещё {k}"},
    "ui.summary.no_matches": {"en": "No matches", "ru": "Совпадений нет"},
    "ui.summary.output_more.one": {"en": "+ {n} more line of output", "ru": "+ ещё {n} строку вывода"},
    "ui.summary.output_more.few": {"en": "+ {n} more lines of output", "ru": "+ ещё {n} строки вывода"},
    "ui.summary.output_more.many": {"en": "+ {n} more lines of output", "ru": "+ ещё {n} строк вывода"},
    "ui.summary.terminal": {"en": "terminal", "ru": "терминал"},
    "ui.summary.hidden.one": {"en": "… {n} hidden line", "ru": "… {n} строка скрыта"},
    "ui.summary.hidden.few": {"en": "… {n} hidden lines", "ru": "… {n} строки скрыты"},
    "ui.summary.hidden.many": {"en": "… {n} hidden lines", "ru": "… {n} строк скрыто"},
    "ui.summary.ms": {"en": "{n} ms", "ru": "{n} мс"},
    "ui.summary.sec": {"en": "{n} s", "ru": "{n} с"},
    "ui.summary.min": {"en": "{n} min {s} s", "ru": "{n} мин {s} с"},
    # Shared chrome (W3.8 full-slice).
    "ui.common.cancel": {"en": "Cancel", "ru": "Отмена"},
    "ui.common.save": {"en": "Save", "ru": "Сохранить"},
    "ui.common.delete": {"en": "Delete", "ru": "Удалить"},
    "ui.common.rename": {"en": "Rename", "ru": "Переименовать"},
    "ui.common.refresh": {"en": "Refresh", "ru": "Обновить"},
    "ui.common.close": {"en": "Close", "ru": "Закрыть"},
    "ui.common.no": {"en": "No", "ru": "Нет"},
    "ui.common.search": {"en": "Search", "ru": "Найти"},
    "ui.common.new": {"en": "New", "ru": "Новый"},
    "ui.common.settings": {"en": "Settings", "ru": "Настройки"},
    "ui.common.models": {"en": "Models", "ru": "Модели"},
    "ui.common.export": {"en": "Export", "ru": "Экспорт"},
    "ui.common.nothing_found": {"en": "Nothing found", "ru": "Ничего не найдено"},
    "ui.common.edit": {"en": "Edit", "ru": "Изменить"},
    "ui.common.refreshing": {"en": "Refreshing…", "ru": "Обновление…"},
    # Sidebar (conversation list).
    "ui.sidebar.new_chat": {"en": "New chat", "ru": "Новый чат"},
    "ui.sidebar.new_chat_title": {"en": "New chat (Ctrl+N)", "ru": "Новый чат (Ctrl+N)"},
    "ui.sidebar.search_history": {"en": "Search history…", "ru": "Поиск по истории…"},
    "ui.sidebar.clear_search": {"en": "Clear search", "ru": "Очистить поиск"},
    "ui.sidebar.empty": {"en": "History is empty — start a conversation", "ru": "История пуста — начните разговор"},
    "ui.sidebar.group.today": {"en": "Today", "ru": "Сегодня"},
    "ui.sidebar.group.yesterday": {"en": "Yesterday", "ru": "Вчера"},
    "ui.sidebar.group.week": {"en": "Last 7 days", "ru": "Последние 7 дней"},
    "ui.sidebar.group.older": {"en": "Earlier", "ru": "Ранее"},
    "ui.sidebar.model_hint": {"en": "model: {model}", "ru": "модель: {model}"},
    "ui.sidebar.delete_chat": {"en": "Delete conversation", "ru": "Удалить разговор"},
    "ui.sidebar.models_ollama": {"en": "Ollama models", "ru": "Модели Ollama"},
    "ui.sidebar.settings_title": {"en": "Settings (Ctrl+,)", "ru": "Настройки (Ctrl+,)"},
    "ui.sidebar.history_empty": {"en": "History is empty", "ru": "История пуста"},
    "ui.sidebar.delete_all": {"en": "Delete all ({n})", "ru": "Удалить все ({n})"},
    "ui.sidebar.clear_all": {"en": "Clear entire history", "ru": "Очистить всю историю"},
    "ui.sidebar.conversation.one": {"en": "{n} conversation", "ru": "{n} разговор"},
    "ui.sidebar.conversation.few": {"en": "{n} conversations", "ru": "{n} разговора"},
    "ui.sidebar.conversation.many": {"en": "{n} conversations", "ru": "{n} разговоров"},
    # Main-task workspace (§4): left-rail section tabs.
    "ui.sidebar.sections_aria": {"en": "Sidebar sections", "ru": "Разделы боковой панели"},
    "ui.sidebar.section.work": {"en": "Work", "ru": "Работа"},
    "ui.sidebar.section.chats": {"en": "Chats", "ru": "Чаты"},
    # Composer.
    "ui.composer.placeholder": {
        "en": "Ask Axiom…  / — commands, ↑↓ — history",
        "ru": "Спросите Axiom…  / — команды, ↑↓ — история",
    },
    "ui.composer.placeholder_disabled": {
        "en": "Ollama unavailable — check the connection",
        "ru": "Ollama недоступна — проверьте подключение",
    },
    "ui.composer.web_search_title": {
        "en": "Web search: the agent searches the web when needed",
        "ru": "Веб-поиск: агент ищет в интернете, если нужно",
    },
    "ui.composer.attach_title": {
        "en": "Attach image (Ctrl+V or drag & drop)",
        "ru": "Прикрепить изображение (Ctrl+V или drag & drop)",
    },
    "ui.composer.photo": {"en": "Photo", "ru": "Фото"},
    "ui.composer.context_title": {
        "en": "Context: tokens, messages, tools",
        "ru": "Контекст: токены, сообщения, инструменты",
    },
    "ui.composer.token_title": {"en": "Prompt token estimate", "ru": "Оценка токенов запроса"},
    "ui.composer.stop": {"en": "Stop (Esc)", "ru": "Остановить (Esc)"},
    "ui.composer.send": {"en": "Send (Enter)", "ru": "Отправить (Enter)"},
    # §6 — composer context chips (rules + skills) and the mode picker.
    "ui.composer.mode": {"en": "Mode", "ru": "Режим"},
    "ui.composer.mode_title": {
        "en": "Autonomy: plan — read only, edit — project edits, auto — safe steps, full — everything",
        "ru": "Автономность: plan — только чтение, edit — правки в проекте, auto — безопасное само, full — всё само",
    },
    "ui.mode.plan": {"en": "Plan", "ru": "План"},
    "ui.mode.edit": {"en": "Edit", "ru": "Правка"},
    "ui.mode.auto": {"en": "Auto", "ru": "Авто"},
    "ui.mode.full": {"en": "Full", "ru": "Полный"},
    "ui.composer.ctx.rules": {"en": "Rules", "ru": "Правила"},
    "ui.composer.ctx.rules_title": {
        "en": "Rule files (AXIOM.md) attached to the request",
        "ru": "Файлы правил (AXIOM.md), прикреплённые к запросу",
    },
    "ui.composer.ctx.rules_empty": {
        "en": "No global or project rule files discovered",
        "ru": "Глобальные и проектные файлы правил не найдены",
    },
    "ui.composer.ctx.skills": {"en": "Skills", "ru": "Skills"},
    "ui.composer.ctx.skills_title": {
        "en": "Skills attached to the request",
        "ru": "Skills, прикреплённые к запросу",
    },
    "ui.composer.ctx.skills_empty": {"en": "No skills registered", "ru": "Skills не зарегистрированы"},
    "ui.composer.remove_image": {"en": "Remove image", "ru": "Убрать изображение"},
    "ui.composer.attachment": {"en": "attachment {n}", "ru": "вложение {n}"},
    "ui.composer.no_vision": {
        "en": "Current model does not support images — switch to a vision model",
        "ru": "Текущая модель не поддерживает изображения — переключитесь на vision-модель",
    },
    "ui.composer.max_images": {"en": "Maximum {n} images", "ru": "Максимум {n} изображения"},
    "ui.composer.too_large": {"en": "{name}: over 10 MB", "ru": "{name}: больше 10 МБ"},
    "ui.composer.files_head": {"en": "PROJECT FILES", "ru": "ФАЙЛЫ ПРОЕКТА"},
    "ui.composer.read_failed": {"en": "Could not read {name}", "ru": "Не удалось прочитать {name}"},
    # Permission confirm dialog (W2.4/W4.9).
    "ui.confirm.title": {"en": "Permission request", "ru": "Запрос разрешения"},
    "ui.confirm.paused": {
        "en": "Tool paused until you answer. Workspace: {cwd}, risk: {risk}{autonomy}.",
        "ru": "Инструмент приостановлен до вашего ответа. Рабочая папка: {cwd}, риск: {risk}{autonomy}.",
    },
    "ui.confirm.danger_note": {
        "en": "Dangerous action: asked every time, approval is never remembered.",
        "ru": "Опасное действие: спрашиваем каждый раз, запоминание не применяется.",
    },
    "ui.confirm.scope_note": {
        "en": (
            "“Once” runs only this call. “Task”/“Project” remember within the task/project, “Always” until the end "
            "of the session. Later calls within the scope will not ask."
        ),
        "ru": (
            "«Один раз» выполнит только этот вызов. «Задача»/«Проект» запомнят в пределах задачи/проекта, «Всегда» "
            "— до конца сессии. Следующие вызовы в пределах scope не будут спрашивать."
        ),
    },
    "ui.confirm.deny": {"en": "Deny", "ru": "Отклонить"},
    "ui.confirm.allow_once": {"en": "Once", "ru": "Один раз"},
    "ui.confirm.allow_task": {"en": "Task", "ru": "Задача"},
    "ui.confirm.allow_project": {"en": "Project", "ru": "Проект"},
    "ui.confirm.allow_always": {"en": "Always", "ru": "Всегда"},
    "ui.confirm.risk.critical": {"en": "critical", "ru": "критический"},
    "ui.confirm.risk.high": {"en": "high", "ru": "высокий"},
    "ui.confirm.risk.medium": {"en": "medium", "ru": "средний"},
    "ui.confirm.risk.low": {"en": "low", "ru": "низкий"},
    "ui.confirm.risk.safe": {"en": "minimal", "ru": "минимальный"},
    "ui.confirm.mode": {"en": "mode {mode}", "ru": "режим {mode}"},
    # Explorer.
    "ui.explorer.no_project": {"en": "no active project", "ru": "нет активного проекта"},
    "ui.explorer.search_placeholder": {"en": "Search project…", "ru": "Поиск по проекту…"},
    "ui.explorer.search_aria": {"en": "Search project", "ru": "Поиск по проекту"},
    "ui.explorer.searching": {"en": "searching…", "ru": "поиск…"},
    "ui.explorer.found": {"en": "Found: {n}", "ru": "Найдено: {n}"},
    "ui.explorer.not_open": {"en": "No project open", "ru": "Проект не открыт"},
    "ui.explorer.choose_folder": {
        "en": "Choose a folder so the agent can read and edit files.",
        "ru": "Выберите папку, чтобы агент мог читать и изменять файлы.",
    },
    "ui.explorer.reading": {"en": "Reading files…", "ru": "Читаю файлы…"},
    "ui.explorer.empty_folder": {"en": "Empty folder", "ru": "Пустая папка"},
    # Git panel.
    "ui.git.unavailable": {"en": "Git unavailable", "ru": "Git недоступен"},
    "ui.git.unavailable_note": {
        "en": "The Git panel appears when a project folder is selected.",
        "ru": "Git-панель появится, когда будет выбрана папка проекта.",
    },
    "ui.git.not_repo": {"en": "Folder is not a git repository", "ru": "Папка не является git-репозиторием"},
    "ui.git.not_repo_note": {
        "en": "Axiom shows branch, changes and history only for git projects.",
        "ru": "Axiom показывает ветку, изменения и историю только для проектов под git.",
    },
    "ui.git.clean": {"en": "clean", "ru": "чисто"},
    "ui.git.changes": {"en": "{n} changed", "ru": "{n} изм."},
    "ui.git.snapshot": {"en": "Create snapshot", "ru": "Создать снимок"},
    "ui.git.rollback": {"en": "Rollback to snapshot", "ru": "Откат к снимку"},
    "ui.git.rollback_confirm": {
        "en": "Roll back the working tree to the last snapshot? Unsaved changes will be lost.",
        "ru": "Откатить рабочее дерево к последнему снимку? Несохранённые изменения будут потеряны.",
    },
    "ui.git.rollback_action": {"en": "Rollback", "ru": "Откатить"},
    "ui.git.working_clean": {"en": "Working tree clean", "ru": "Рабочее дерево чистое"},
    "ui.git.modified": {"en": "Modified", "ru": "Изменённые"},
    "ui.git.added": {"en": "Added", "ru": "Новые"},
    "ui.git.untracked": {"en": "Untracked", "ru": "Не отслеживаются"},
    "ui.git.deleted": {"en": "Deleted", "ru": "Удалённые"},
    "ui.git.other": {"en": "Other", "ru": "Другие"},
    "ui.git.history": {"en": "History", "ru": "История"},
    "ui.git.letter.M": {"en": "modified", "ru": "изменён"},
    "ui.git.letter.A": {"en": "new (staged)", "ru": "новый (в индексе)"},
    "ui.git.letter.untracked": {"en": "untracked", "ru": "не отслеживается"},
    "ui.git.letter.D": {"en": "deleted", "ru": "удалён"},
    "ui.git.letter.R": {"en": "renamed", "ru": "переименован"},
    "ui.git.letter.C": {"en": "copied", "ru": "скопирован"},
    "ui.git.letter.U": {"en": "merge conflict", "ru": "конфликт слияния"},
    # Terminal panel.
    "ui.terminal.off": {"en": "off", "ru": "выключен"},
    "ui.terminal.rerun": {"en": "Repeat command", "ru": "Повторить команду"},
    "ui.terminal.no_output": {"en": "(no output)", "ru": "(no output)"},
    "ui.terminal.exit_code": {"en": "code {n}", "ru": "код {n}"},
    "ui.terminal.confirm": {"en": "Run command?", "ru": "Выполнить команду?"},
    "ui.terminal.run": {"en": "Run", "ru": "Выполнить"},
    "ui.terminal.empty": {
        "en": "pytest · npm run dev · git status — commands run in the project folder",
        "ru": "pytest · npm run dev · git status — команды выполняются в папке проекта",
    },
    "ui.terminal.placeholder": {"en": "command…", "ru": "команда…"},
    "ui.terminal.placeholder_disabled": {"en": "terminal disabled in settings", "ru": "терминал отключён в настройках"},
    # Documents panel.
    "ui.documents.open_project": {
        "en": "Open a project to work with documents",
        "ru": "Откройте проект, чтобы работать с документами",
    },
    "ui.documents.title": {"en": "Documents", "ru": "Документы"},
    "ui.documents.new_doc": {"en": "New document", "ru": "Новый документ"},
    "ui.documents.none": {
        "en": "No documents yet — create the first one",
        "ru": "Пока нет документов — создайте первый",
    },
    "ui.documents.preview": {"en": "Preview", "ru": "Предпросмотр"},
    "ui.documents.download_md": {"en": "Download .md", "ru": "Скачать .md"},
    "ui.documents.saving": {"en": "Saving…", "ru": "Сохранение…"},
    "ui.documents.placeholder": {"en": "# Heading — write Markdown…", "ru": "# Заголовок — пишите Markdown…"},
    # Project selector.
    "ui.project.title": {"en": "Projects", "ru": "Проекты"},
    "ui.project.global_title": {"en": "Global chat — no project open", "ru": "Глобальный чат — проект не открыт"},
    "ui.project.no_folder": {"en": "No project folder", "ru": "Без папки проекта"},
    "ui.project.pin": {"en": "Pin project", "ru": "Прикрепить проект"},
    "ui.project.unpin": {"en": "Unpin project", "ru": "Открепить проект"},
    "ui.project.remove_list": {"en": "Remove project from list", "ru": "Удалить проект из списка"},
    "ui.project.pinned": {"en": "Pinned", "ru": "Прикрепленные"},
    "ui.project.recent": {"en": "Recent", "ru": "Недавние"},
    "ui.project.global_hint": {
        "en": "Chat without a project: file tools are disabled",
        "ru": "Общаться без проекта: файловые инструменты отключены",
    },
    "ui.project.open": {"en": "Open project…", "ru": "Открыть проект…"},
    "ui.project.remove_title": {"en": "Remove project from list?", "ru": "Удалить проект из списка?"},
    "ui.project.remove_body": {
        "en": (
            "The project will disappear from the selector list. Files on disk are not deleted, and the open "
            "project stays active until you switch away. You can add it back with “Open project…”."
        ),
        "ru": (
            "Проект исчезнет из списка селектора. Файлы на диске не удаляются, а открытый проект останется "
            "активным, пока вы не переключитесь сами. Вернуть его в список можно кнопкой «Открыть проект…»."
        ),
    },
    "ui.project.dismiss": {"en": "Dismiss", "ru": "Отказаться"},
    "ui.project.remove_action": {"en": "Remove from list", "ru": "Удалить из списка"},
    # Model selector.
    "ui.model.switch": {"en": "switch model", "ru": "сменить модель"},
    "ui.model.choose": {"en": "Choose model", "ru": "Выбрать модель"},
    "ui.model.none": {"en": "No model selected", "ru": "Модель не выбрана"},
    "ui.model.refresh": {"en": "Refresh list from Ollama", "ru": "Обновить список из Ollama"},
    "ui.model.close": {"en": "Close (Esc)", "ru": "Закрыть (Esc)"},
    "ui.model.empty": {
        "en": (
            "No models yet. Install with `ollama pull qwen3:8b` or connect an API provider — the list updates "
            "automatically."
        ),
        "ru": (
            "Моделей пока нет. Установите через `ollama pull qwen3:8b` или подключите API-провайдера — список "
            "подтянется автоматически."
        ),
    },
    "ui.model.ready": {"en": "ready", "ru": "готова"},
    "ui.model.cap_missing": {
        "en": "{label}: Ollama does not report support",
        "ru": "{label}: Ollama не сообщает поддержку",
    },
    "ui.model.foot": {
        "en": "Data: Ollama /api/tags · /api/ps · Esc to close",
        "ru": "Данные: Ollama /api/tags · /api/ps · Esc закрыть",
    },
    "ui.model.select_failed": {
        "en": "Could not select {provider}/{name}. Check the provider, endpoint and API key.",
        "ru": "Не удалось выбрать {provider}/{name}. Проверьте провайдера, endpoint и API-ключ.",
    },
    "ui.model.desc.reasoning": {"en": "Reasoning model", "ru": "Reasoning-модель"},
    "ui.model.desc.tools": {"en": "Tool-capable model", "ru": "Модель с инструментами"},
    "ui.model.desc.vision": {"en": "Vision model", "ru": "Vision-модель"},
    "ui.model.desc.general": {"en": "General model", "ru": "Обычная модель"},
    "ui.model.desc.unknown": {"en": "Capabilities unknown", "ru": "Возможности неизвестны"},
    # Boot screen.
    "ui.boot.ready": {"en": "System ready", "ru": "Система готова"},
    "ui.boot.starting": {"en": "Starting AXIOM…", "ru": "Запуск AXIOM…"},
    "ui.boot.init": {"en": "System initialization · {done}/{total}", "ru": "Инициализация системы · {done}/{total}"},
    "ui.boot.progress": {"en": "Loading progress", "ru": "Прогресс загрузки"},
    "ui.boot.stopped": {"en": "Startup stopped", "ru": "Запуск остановлен"},
    "ui.boot.causes": {"en": "Likely causes", "ru": "Вероятные причины"},
    "ui.boot.cause1": {
        "en": "Ollama is not running — run ollama serve",
        "ru": "Ollama не запущена — выполните ollama serve",
    },
    "ui.boot.cause2": {"en": "wrong API address in settings", "ru": "неверный адрес API в настройках"},
    "ui.boot.cause3": {
        "en": "port 11434 is busy or the connection was refused",
        "ru": "порт 11434 занят или соединение отклонено",
    },
    "ui.boot.retry": {"en": "Retry", "ru": "Повторить"},
    "ui.boot.restart_core": {"en": "Restart core", "ru": "Перезапустить ядро"},
    "ui.boot.step.ui": {"en": "Initializing interface", "ru": "Инициализация интерфейса"},
    "ui.boot.step.detect": {"en": "Finding Ollama", "ru": "Поиск Ollama"},
    "ui.boot.step.connect": {"en": "Connecting to Ollama", "ru": "Подключение к Ollama"},
    "ui.boot.step.models": {"en": "Reading installed models", "ru": "Чтение установленных моделей"},
    "ui.boot.step.select": {"en": "Selecting active model", "ru": "Выбор активной модели"},
    "ui.boot.step.workspace": {"en": "Preparing workspace", "ru": "Подготовка рабочего пространства"},
    "ui.boot.done": {"en": "done", "ru": "готово"},
    "ui.boot.connected": {"en": "connection established", "ru": "соединение установлено"},
    "ui.boot.external_api": {"en": "external API mode", "ru": "режим внешнего API"},
    "ui.boot.external_provider": {"en": "external provider: {id}", "ru": "внешний provider: {id}"},
    "ui.boot.no_project": {"en": "no project", "ru": "без проекта"},
    "ui.boot.no_model": {"en": "no model selected", "ru": "модель не выбрана"},
    "ui.boot.no_models": {"en": "no models yet", "ru": "моделей пока нет"},
    "ui.boot.no_data": {"en": "no data — will retry", "ru": "нет данных — повторим позже"},
    "ui.boot.models_count.one": {"en": "{n} model", "ru": "{n} модель"},
    "ui.boot.models_count.few": {"en": "{n} models", "ru": "{n} модели"},
    "ui.boot.models_count.many": {"en": "{n} models", "ru": "{n} моделей"},
    "ui.documents.empty": {"en": "*Empty*", "ru": "*Пусто*"},
    # Settings modal — navigation + section meta.
    "ui.settings.close": {"en": "Close settings", "ru": "Закрыть настройки"},
    "ui.settings.close_title": {"en": "Close (Esc)", "ru": "Закрыть (Esc)"},
    "ui.settings.nav_aria": {"en": "Settings sections", "ru": "Разделы настроек"},
    "ui.settings.search_placeholder": {"en": "Find section", "ru": "Найти раздел"},
    "ui.settings.search_aria": {"en": "Find settings section", "ru": "Найти раздел настроек"},
    "ui.settings.restart_core": {"en": "Restart core", "ru": "Перезапустить ядро"},
    "ui.settings.save_hint.dirty": {"en": "Unsaved changes · Ctrl+S", "ru": "Есть несохранённые изменения · Ctrl+S"},
    "ui.settings.save_hint.immediate": {
        "en": "Actions in this section apply immediately",
        "ru": "Действия в этом разделе применяются сразу",
    },
    "ui.settings.save_hint.saved": {"en": "All changes saved", "ru": "Все изменения сохранены"},
    "ui.settings.nav.general": {"en": "General", "ru": "Общие"},
    "ui.settings.nav.appearance": {"en": "Appearance", "ru": "Вид"},
    "ui.settings.nav.models": {"en": "Models", "ru": "Модели"},
    "ui.settings.nav.providers": {"en": "Providers", "ru": "Провайдеры"},
    "ui.settings.nav.plugins": {"en": "Plugins", "ru": "Плагины"},
    "ui.settings.nav.mcp": {"en": "MCP", "ru": "MCP"},
    "ui.settings.nav.skills": {"en": "Skills", "ru": "Навыки"},
    "ui.settings.nav.memory": {"en": "Memory", "ru": "Память"},
    "ui.settings.nav.knowledge": {"en": "Knowledge", "ru": "Знания"},
    "ui.settings.nav.chat": {"en": "Chat", "ru": "Чат"},
    "ui.settings.nav.tools": {"en": "Tools", "ru": "Инструменты"},
    "ui.settings.nav.shortcuts": {"en": "Shortcuts", "ru": "Горячие клавиши"},
    "ui.settings.nav.about": {"en": "About", "ru": "О программе"},
    "ui.settings.group.workspace": {"en": "Workspace", "ru": "Рабочее пространство"},
    "ui.settings.group.ai": {"en": "AI & Connections", "ru": "AI и подключения"},
    "ui.settings.group.data": {"en": "Data", "ru": "Данные"},
    "ui.settings.group.ext": {"en": "Extensions", "ru": "Расширения"},
    "ui.settings.group.system": {"en": "System", "ru": "Система"},
    "ui.settings.desc.general": {
        "en": "History, system prompt and basic AXIOM behavior.",
        "ru": "История, системный промпт и базовое поведение AXIOM.",
    },
    "ui.settings.desc.appearance": {
        "en": "Theme, accent, UI density and animations.",
        "ru": "Тема, акцент, плотность интерфейса и анимации.",
    },
    "ui.settings.desc.chat": {
        "en": "How AXIOM renders and accompanies the response stream.",
        "ru": "Как AXIOM отображает и сопровождает поток ответа.",
    },
    "ui.settings.desc.shortcuts": {
        "en": "Quick commands for navigation and working with the conversation.",
        "ru": "Быстрые команды для навигации и работы с диалогом.",
    },
    "ui.settings.desc.models": {
        "en": "Ollama endpoint, reasoning and generation parameters.",
        "ru": "Ollama endpoint, reasoning и параметры генерации.",
    },
    "ui.settings.desc.providers": {
        "en": "Connections to local models and external APIs.",
        "ru": "Подключения к локальным моделям и внешним API.",
    },
    "ui.settings.desc.tools": {
        "en": "Web search, files, terminal and permission modes.",
        "ru": "Web search, файлы, terminal и режимы разрешений.",
    },
    "ui.settings.desc.memory": {
        "en": "Saved facts and preferences you can edit.",
        "ru": "Сохранённые факты и предпочтения, доступные для редактирования.",
    },
    "ui.settings.desc.knowledge": {
        "en": "Document collections and cited local search.",
        "ru": "Коллекции документов и цитируемый локальный поиск.",
    },
    "ui.settings.desc.plugins": {
        "en": "Install, trust and manage AXIOM extension code.",
        "ru": "Установка, доверие и управление кодом расширений AXIOM.",
    },
    "ui.settings.desc.mcp": {
        "en": "External MCP servers: connect, status and tool testing.",
        "ru": "Внешние MCP-серверы: подключение, статус и проверка инструментов.",
    },
    "ui.settings.desc.skills": {
        "en": "Reusable stack instructions and their task applicability.",
        "ru": "Переиспользуемые инструкции по стеку и их применимость к задаче.",
    },
    "ui.settings.desc.about": {
        "en": "AXIOM's local architecture and security information.",
        "ru": "Локальная архитектура AXIOM и сведения о безопасности.",
    },
    # Settings — General.
    "ui.settings.grp.language": {"en": "Interface language", "ru": "Язык интерфейса"},
    "ui.settings.lang.ru": {"en": "Russian", "ru": "Русский"},
    "ui.settings.lang.en": {"en": "English", "ru": "English"},
    "ui.settings.grp.history": {"en": "History and storage", "ru": "История и хранение"},
    "ui.settings.save_history": {"en": "Save history", "ru": "Сохранять историю"},
    "ui.settings.save_history_hint": {
        "en": "Conversations are stored locally in ~/.axiom",
        "ru": "Разговоры хранятся локально в ~/.axiom",
    },
    "ui.settings.history_limit": {"en": "History limit", "ru": "Лимит истории"},
    "ui.settings.history_limit_hint": {
        "en": "How many recent conversations to keep",
        "ru": "Сколько последних разговоров хранить",
    },
    "ui.settings.grp.behavior": {"en": "Assistant behavior", "ru": "Поведение ассистента"},
    "ui.settings.temperature_hint": {
        "en": "Empty — the model's default value",
        "ru": "Пусто — значение модели по умолчанию",
    },
    "ui.settings.system_prompt": {"en": "System prompt", "ru": "Системный промпт"},
    "ui.settings.system_prompt_hint": {
        "en": "Empty — the built-in AXIOM prompt",
        "ru": "Пусто — встроенный промпт AXIOM",
    },
    "ui.settings.default_placeholder": {"en": "default", "ru": "по умолчанию"},
    "ui.settings.auto_placeholder": {"en": "auto", "ru": "auto"},
    # Settings — Models.
    "ui.settings.grp.ollama": {"en": "Ollama connection", "ru": "Подключение к Ollama"},
    "ui.settings.ollama_url_hint": {"en": "Current connection: {url}", "ru": "Текущее соединение: {url}"},
    "ui.settings.grp.reasoning": {"en": "Reasoning and generation", "ru": "Рассуждение и генерация"},
    "ui.settings.think": {"en": "Think mode", "ru": "Think-режим"},
    "ui.settings.think_hint": {
        "en": "Reasoning level: auto — the core decides per request",
        "ru": "Уровень рассуждений: авто — решает ядро по запросу",
    },
    "ui.settings.think.auto": {"en": "Auto", "ru": "Авто"},
    "ui.settings.think.on": {"en": "Always", "ru": "Всегда"},
    "ui.settings.think.low": {"en": "Low", "ru": "Низкий"},
    "ui.settings.think.medium": {"en": "Medium", "ru": "Средний"},
    "ui.settings.think.high": {"en": "High", "ru": "Высокий"},
    "ui.settings.think.max": {"en": "Maximum", "ru": "Максимум"},
    "ui.settings.thinking_mode": {"en": "Thinking mode", "ru": "Режим мышления"},
    "ui.settings.thinking_mode_hint": {
        "en": "Reasoning depth preset when Think = Auto",
        "ru": "Пресет глубины reasoning, когда Think = Авто",
    },
    "ui.settings.thinking_mode.auto": {"en": "Auto (per request)", "ru": "Авто (по запросу)"},
    "ui.settings.thinking_mode.fast": {"en": "Fast", "ru": "Быстрый"},
    "ui.settings.thinking_mode.normal": {"en": "Normal", "ru": "Обычный"},
    "ui.settings.thinking_mode.deep": {"en": "Deep", "ru": "Глубокий"},
    "ui.settings.grp.memory_limits": {"en": "Memory and limits", "ru": "Память и лимиты"},
    "ui.settings.warmup": {"en": "Model warmup", "ru": "Прогрев модели"},
    "ui.settings.warmup_hint": {
        "en": "Load the model into memory right after start",
        "ru": "Загрузить модель в память сразу после старта",
    },
    "ui.settings.keep_alive": {"en": "Keep model in memory", "ru": "Держать модель в памяти"},
    "ui.settings.keep_alive_hint": {
        "en": "Ollama keep_alive, e.g. 30m or 1h",
        "ru": "Ollama keep_alive, например 30m или 1h",
    },
    "ui.settings.num_ctx": {"en": "Context window", "ru": "Контекстное окно"},
    "ui.settings.num_ctx_hint": {
        "en": "Empty — the model default (num_ctx)",
        "ru": "Пусто — по умолчанию модели (num_ctx)",
    },
    "ui.settings.num_predict": {"en": "Max response", "ru": "Максимум ответа"},
    "ui.settings.num_predict_hint": {
        "en": "Generation token limit (num_predict), empty — auto",
        "ru": "Лимит токенов генерации (num_predict), пусто — авто",
    },
    "ui.settings.core": {"en": "AXIOM core", "ru": "Ядро AXIOM"},
    "ui.settings.core_hint": {
        "en": "Restart the Python core and re-probe Ollama",
        "ru": "Перезапуск Python-ядра и повторная проверка Ollama",
    },
    "ui.settings.restart": {"en": "Restart", "ru": "Перезапустить"},
    # Settings — Chat.
    "ui.settings.grp.response": {"en": "Response rendering", "ru": "Отображение ответа"},
    "ui.settings.markdown_hint": {
        "en": "Render answers as Markdown with code highlighting",
        "ru": "Рендеринг ответов в Markdown с подсветкой кода",
    },
    "ui.settings.show_reasoning": {"en": "Show reasoning", "ru": "Показывать reasoning"},
    "ui.settings.show_reasoning_hint": {
        "en": "Show the model's thinking blocks when present",
        "ru": "Отображать thinking-блоки модели, когда они есть",
    },
    "ui.settings.reasoning_expanded": {"en": "Expand reasoning", "ru": "Раскрывать reasoning"},
    "ui.settings.reasoning_expanded_hint": {
        "en": "Thinking blocks expanded by default",
        "ru": "Thinking-блоки развёрнуты по умолчанию",
    },
    "ui.settings.auto_scroll": {"en": "Auto-scroll", "ru": "Автоскролл"},
    "ui.settings.auto_scroll_hint": {"en": "Follow the generation stream", "ru": "Следить за потоком генерации"},
    "ui.settings.grp.context": {"en": "Context and metrics", "ru": "Контекст и метрики"},
    "ui.settings.show_metrics": {"en": "Response metrics", "ru": "Метрики ответа"},
    "ui.settings.show_metrics_hint": {
        "en": "Time, tokens, speed after generation",
        "ru": "Время, токены, скорость после генерации",
    },
    "ui.settings.show_context": {"en": "Context indicator", "ru": "Индикатор контекста"},
    "ui.settings.show_context_hint": {
        "en": "How full the model's context window is",
        "ru": "Заполнение контекстного окна модели",
    },
    "ui.settings.context_messages": {"en": "Messages in context", "ru": "Сообщений в контексте"},
    "ui.settings.context_messages_hint": {
        "en": "How many recent messages to send to the model",
        "ru": "Сколько последних сообщений отправлять модели",
    },
    # Settings — Tools.
    "ui.settings.grp.web": {"en": "Web search", "ru": "Поиск в интернете"},
    "ui.settings.web_search": {"en": "Web search", "ru": "Веб-поиск"},
    "ui.settings.web_search_hint": {
        "en": "Web search tool (needs network; the rest is local)",
        "ru": "Инструмент поиска в интернете (требует сеть, остальное — локально)",
    },
    "ui.settings.search_provider": {"en": "Search engine", "ru": "Движок поиска"},
    "ui.settings.search_provider_hint": {
        "en": "Auto — resilient chain; you can pin one engine",
        "ru": "Auto — устойчивая цепочка; можно закрепить один движок",
    },
    "ui.settings.search_test": {"en": "Search test", "ru": "Проверка поиска"},
    "ui.settings.search_test_hint": {
        "en": "A real request: engine, latency and results or error",
        "ru": "Реальный запрос: движок, задержка и результаты или ошибка",
    },
    "ui.settings.search_query_aria": {"en": "Web search test query", "ru": "Запрос для проверки веб-поиска"},
    "ui.settings.query_placeholder": {"en": "query", "ru": "запрос"},
    "ui.settings.testing": {"en": "Testing…", "ru": "Проверка…"},
    "ui.settings.test": {"en": "Test", "ru": "Проверить"},
    "ui.settings.results": {"en": "results", "ru": "результатов"},
    "ui.settings.untitled": {"en": "(untitled)", "ru": "(без названия)"},
    "ui.settings.grp.access": {"en": "Access and permissions", "ru": "Доступ и разрешения"},
    "ui.settings.project_files": {"en": "Project files", "ru": "Файлы проекта"},
    "ui.settings.project_files_hint": {
        "en": "Allow the model to read and edit files in this folder: list_files, read_file, write_file, edit_file",
        "ru": "Разрешить модели читать и редактировать файлы этой папки: list_files, read_file, write_file, edit_file",
    },
    "ui.settings.permission_mode": {"en": "Permission mode", "ru": "Режим разрешений"},
    "ui.settings.permission_mode_hint": {
        "en": "plan · edit · auto · full (over ask/auto)",
        "ru": "plan · edit · auto · full (поверх ask/auto)",
    },
    "ui.settings.auto.plan": {"en": "Plan — read only", "ru": "Plan — только чтение"},
    "ui.settings.auto.edit": {
        "en": "Edit — project edits, commands ask",
        "ru": "Edit — правки в проекте, команды спрашивать",
    },
    "ui.settings.auto.auto": {
        "en": "Auto — safe automatically, risky asks",
        "ru": "Auto — безопасное само, рискованное спросить",
    },
    "ui.settings.auto.full": {
        "en": "Full — everything automatic except dangerous (careful)",
        "ru": "Full — всё само, кроме опасного (осторожно)",
    },
    "ui.settings.access_mode": {"en": "AI access", "ru": "Доступ AI"},
    "ui.settings.access_mode_hint": {
        "en": "read_only — read only · workspace — inside the project · full — whole PC (careful)",
        "ru": "read_only — только чтение · workspace — внутри проекта · full — весь ПК (осторожно)",
    },
    "ui.settings.access.read_only": {"en": "Read only", "ru": "Только чтение"},
    "ui.settings.access.workspace": {"en": "Project (workspace)", "ru": "Проект (workspace)"},
    "ui.settings.access.full": {"en": "Full access", "ru": "Полный доступ"},
    "ui.settings.terminal_ai": {"en": "AI terminal", "ru": "Терминал AI"},
    "ui.settings.terminal_ai_hint": {
        "en": "Allow the model to run commands in the project folder",
        "ru": "Разрешить модели выполнять команды в папке проекта",
    },
    "ui.settings.grp.search_limits": {"en": "Web search limits", "ru": "Лимиты веб-поиска"},
    "ui.settings.sources": {"en": "Sources per query", "ru": "Источников на запрос"},
    "ui.settings.sources_hint": {"en": "How many results search returns", "ru": "Сколько результатов возвращает поиск"},
    "ui.settings.read_sources": {"en": "Read sources", "ru": "Читать источники"},
    "ui.settings.read_sources_hint": {
        "en": "How many pages to load fully for an answer",
        "ru": "Сколько страниц загружать целиком для ответа",
    },
    "ui.settings.search_timeout": {"en": "Search timeout, s", "ru": "Таймаут поиска, с"},
    "ui.settings.search_timeout_hint": {
        "en": "Limit for waiting on search providers",
        "ru": "Лимит ожидания поисковых провайдеров",
    },
    # Settings — Appearance.
    "ui.settings.grp.color": {"en": "Color and appearance", "ru": "Цвет и оформление"},
    "ui.settings.theme_aria": {"en": "Theme", "ru": "Тема"},
    "ui.settings.accent": {"en": "Accent", "ru": "Акцент"},
    "ui.settings.accent_hint_shared": {
        "en": "Shared verified color for Desktop and TUI",
        "ru": "Общий проверенный цвет для Desktop и TUI",
    },
    "ui.settings.accent_hint_own": {
        "en": "This theme has its own accent — the choice applies to AXIOM Dark, Graphite and Light",
        "ru": "У этой темы собственный акцент — выбор применяется к AXIOM Dark, Graphite и Light",
    },
    "ui.settings.accent_aria": {"en": "Accent", "ru": "Акцент"},
    "ui.settings.panel_hover": {"en": "Panel highlight", "ru": "Подсветка панелей"},
    "ui.settings.panel_hover_hint": {
        "en": "Highlight panel rows and buttons on hover",
        "ru": "Выделять строки и кнопки панели при наведении",
    },
    "ui.settings.grp.motion": {"en": "Motion and sound", "ru": "Движение и звук"},
    "ui.settings.animations": {"en": "Animations", "ru": "Анимации"},
    "ui.settings.animations_hint": {"en": "Smooth UI transitions", "ru": "Плавные переходы интерфейса"},
    "ui.settings.ui_sounds": {"en": "Quiet UI sounds", "ru": "Тихие UI-звуки"},
    "ui.settings.ui_sounds_hint": {
        "en": "Off by default. Applies immediately, desktop UI only. No sound while typing.",
        "ru": "Выключены по умолчанию. Применяется сразу, только в desktop UI. Без звука при вводе текста.",
    },
    "ui.settings.test_sounds": {"en": "Test sounds", "ru": "Проверить звуки"},
    "ui.settings.test_sounds_hint": {
        "en": "Answer ready, error, permission request and stop each sound different.",
        "ru": "Ответ готов, ошибка, запрос разрешения и остановка звучат по-разному.",
    },
    "ui.settings.play": {"en": "Play: {label}", "ru": "Проиграть: {label}"},
    "ui.settings.enable_sounds": {"en": "Enable UI sounds first", "ru": "Сначала включите UI-звуки"},
    "ui.settings.sound.complete": {"en": "Answer ready", "ru": "Ответ готов"},
    "ui.settings.sound.error": {"en": "Error", "ru": "Ошибка"},
    "ui.settings.sound.permission": {"en": "Permission request", "ru": "Запрос разрешения"},
    "ui.settings.sound.stopped": {"en": "Stopped", "ru": "Остановлено"},
    "ui.settings.grp.density": {"en": "Density and panels", "ru": "Плотность и панели"},
    "ui.settings.density": {"en": "Density", "ru": "Плотность"},
    "ui.settings.density_hint": {
        "en": "Interface size: compact, standard or enlarged",
        "ru": "Размер интерфейса: компактный, стандартный или увеличенный",
    },
    "ui.settings.density.compact": {"en": "Compact", "ru": "Компактный"},
    "ui.settings.density.comfortable": {"en": "Standard", "ru": "Стандартный"},
    "ui.settings.density.spacious": {"en": "Enlarged", "ru": "Увеличенный"},
    "ui.settings.font_size": {"en": "Font size, px", "ru": "Размер шрифта, px"},
    "ui.settings.sidebar_open": {"en": "Sidebar open", "ru": "Боковая панель открыта"},
    "ui.settings.sidebar_width": {"en": "Panel width, px", "ru": "Ширина панели, px"},
    "ui.settings.accent.garnet": {"en": "Garnet", "ru": "Гранатовый"},
    "ui.settings.accent.blue": {"en": "Blue", "ru": "Синий"},
    "ui.settings.accent.teal": {"en": "Teal", "ru": "Бирюзовый"},
    "ui.settings.accent.violet": {"en": "Violet", "ru": "Фиолетовый"},
    "ui.settings.accent.slate": {"en": "Slate", "ru": "Серый"},
    "ui.settings.accent.rose": {"en": "Rose", "ru": "Розовый"},
    "ui.settings.accent.amber": {"en": "Amber", "ru": "Янтарный"},
    # Settings — Memory.
    "ui.settings.memory.title": {"en": "Memory", "ru": "Память"},
    "ui.settings.memory.desc": {
        "en": (
            "Facts and preferences AXIOM remembers between sessions. The model reads and writes memory only "
            "through tools, and everything saved here can be edited or deleted manually."
        ),
        "ru": (
            "Факты и предпочтения, которые AXIOM помнит между запусками. Модель читает и пишет память только через "
            "инструменты, а всё, что здесь сохранено, можно изменить или удалить вручную."
        ),
    },
    "ui.settings.memory.placeholder": {
        "en": "E.g. tests in this project run via pytest",
        "ru": "Например: в этом проекте тесты запускаются через pytest",
    },
    "ui.settings.memory.cat.normal": {"en": "regular fact", "ru": "обычный факт"},
    "ui.settings.memory.cat.sensitive": {"en": "personal preference", "ru": "личное предпочтение"},
    "ui.settings.memory.scope.global": {"en": "global", "ru": "глобально"},
    "ui.settings.memory.scope.project": {"en": "in project", "ru": "в проекте"},
    "ui.settings.memory.remember": {"en": "Remember", "ru": "Запомнить"},
    "ui.settings.memory.banned_hint": {
        "en": "The “banned” category cannot be written: such entries never reach disk.",
        "ru": "Категория «запрещённая» недоступна для записи: такие записи никогда не попадают на диск.",
    },
    "ui.settings.memory.empty": {
        "en": "Memory is empty. Add a fact manually or ask the model to remember something in the chat.",
        "ru": "Память пуста. Добавьте факт вручную или попросите модель запомнить что-то в диалоге.",
    },
    "ui.settings.memory.badge.project": {"en": "project", "ru": "проект"},
    "ui.settings.memory.badge.preference": {"en": "preference", "ru": "предпочтение"},
    "ui.settings.memory.badge.fact": {"en": "fact", "ru": "факт"},
    "ui.settings.memory.delete_aria": {
        "en": "Delete memory entry: {content}",
        "ru": "Удалить запись памяти: {content}",
    },
    # Settings — Knowledge.
    "ui.settings.knowledge.title": {"en": "Knowledge base", "ru": "База знаний"},
    "ui.settings.knowledge.desc": {
        "en": (
            "Local folders and documents are indexed into SQLite/FTS5 (BM25 works fully offline). Ollama "
            "embeddings are an optional re-ranking layer: when unavailable, the status honestly says so. The model "
            "only receives cited fragments."
        ),
        "ru": (
            "Локальные папки и документы индексируются в SQLite/FTS5 (BM25 работает полностью офлайн). Эмбеддинги "
            "Ollama — необязательный слой переранжирования: когда они недоступны, статус честно показывает это. "
            "Модель получает только цитируемые фрагменты."
        ),
    },
    "ui.settings.knowledge.name_placeholder": {"en": "Collection name (e.g. docs)", "ru": "Имя коллекции (напр. docs)"},
    "ui.settings.knowledge.path_placeholder": {"en": "Path to a folder or file…", "ru": "Путь к папке или файлу…"},
    "ui.settings.knowledge.index": {"en": "Index", "ru": "Индексировать"},
    "ui.settings.knowledge.hint": {
        "en": "Re-indexing reads only changed files; secrets (.env, keys) never enter the index.",
        "ru": (
            "Повторная индексация читает только изменённые файлы; секреты (.env, ключи) никогда не попадают в "
            "индекс."
        ),
    },
    "ui.settings.knowledge.empty": {
        "en": (
            "No collections yet. Specify a folder above — after indexing the model can search it via "
            "knowledge_search."
        ),
        "ru": (
            "Коллекций пока нет. Укажите папку выше — после индексации модель сможет искать по ней через "
            "инструмент knowledge_search."
        ),
    },
    "ui.settings.knowledge.files": {"en": "files", "ru": "файлов"},
    "ui.settings.knowledge.chunks": {"en": "chunks", "ru": "фрагментов"},
    "ui.settings.knowledge.embeddings": {"en": "embeddings: {v}", "ru": "эмбеддинги: {v}"},
    "ui.settings.knowledge.reindex": {"en": "Reindex", "ru": "Переиндексировать"},
    "ui.settings.knowledge.search_placeholder": {
        "en": "Knowledge base search query…",
        "ru": "Поисковый запрос по базе знаний…",
    },
    "ui.settings.knowledge.no_hits": {
        "en": "No fragments found for the query.",
        "ru": "Фрагментов по запросу не найдено.",
    },
    # Settings — Plugins confirmations.
    "ui.settings.plugins.trust_title": {"en": "Confirm plugin trust", "ru": "Подтвердить доверие к плагину"},
    "ui.settings.plugins.from_folder": {"en": "Plugin from the selected folder", "ru": "Плагин из выбранной папки"},
    "ui.settings.plugins.declared_tools": {"en": "Declared tools: {tools}", "ru": "Объявленные инструменты: {tools}"},
    "ui.settings.plugins.capabilities": {"en": "Manifest capabilities: {caps}", "ru": "Возможности манифеста: {caps}"},
    "ui.settings.plugins.ui_scopes": {
        "en": "Declared UI scopes (not enforced as Python limits): {scopes}",
        "ru": "Заявленные UI scopes (не применяются как ограничения Python): {scopes}",
    },
    "ui.settings.plugins.import_warning": {
        "en": (
            "After import, Python code may act with the user's and AXIOM process's permissions: read and modify "
            "accessible files, access the network, environment variables and run processes. AXIOM does not isolate "
            "plugin code."
        ),
        "ru": (
            "После импорта Python-код может действовать с правами пользователя и процесса AXIOM: читать и изменять "
            "доступные файлы, обращаться к сети, переменным окружения и запускать процессы. AXIOM не изолирует код "
            "плагина."
        ),
    },
    "ui.settings.plugins.run_confirm": {
        "en": "Confirm running this code. The permission persists while the plugin is enabled.",
        "ru": "Подтвердите запуск этого кода. Разрешение сохраняется, пока плагин включён.",
    },
    "ui.settings.plugins.install_confirm": {
        "en": (
            "Confirmation only allows installation. The plugin stays disabled; running it needs a separate "
            "confirmation."
        ),
        "ru": (
            "Подтверждение разрешает только установку. Плагин останется выключенным; запуск потребует отдельного "
            "подтверждения."
        ),
    },
    "ui.settings.plugins.trust_run": {"en": "Trust and run", "ru": "Доверять и запустить"},
    "ui.settings.plugins.confirm_install": {"en": "Confirm install", "ru": "Подтвердить установку"},
    "ui.settings.plugins.remove_title": {"en": "Remove plugin?", "ru": "Удалить плагин?"},
    "ui.settings.plugins.remove_body": {
        "en": (
            "The plugin will be removed from AXIOM. Its tools and extensions become unavailable. Reinstalling is "
            "required to use it again."
        ),
        "ru": (
            "Плагин будет удалён из AXIOM. Его инструменты и расширения станут недоступны. Для повторного "
            "использования потребуется установка."
        ),
    },
    "ui.settings.plugins.remove_plugin": {"en": "Remove plugin", "ru": "Удалить плагин"},
    # Settings — About.
    "ui.settings.about.active_model": {"en": "Active model", "ru": "Активная модель"},
    "ui.settings.about.not_selected": {"en": "not selected", "ru": "не выбрана"},
    "ui.settings.about.project": {"en": "Project", "ru": "Проект"},
    "ui.settings.about.not_chosen": {"en": "not selected", "ru": "не выбран"},
    "ui.settings.about.ai_access": {"en": "AI access", "ru": "Доступ AI"},
    "ui.settings.about.providers": {"en": "Providers", "ru": "Провайдеры"},
    "ui.settings.about.plugins": {"en": "Plugins", "ru": "Плагины"},
    "ui.settings.about.history": {"en": "History", "ru": "История"},
    "ui.settings.about.copied": {"en": "Copied", "ru": "Скопировано"},
    "ui.settings.about.copy_details": {"en": "Copy details", "ru": "Скопировать сведения"},
    "ui.settings.about.tagline": {
        "en": (
            "A local AI coding agent and desktop IDE: chat with models, project files, terminal, Git and web "
            "search in one window."
        ),
        "ru": (
            "Локальный AI coding agent и desktop IDE: чат с моделями, файлы проекта, терминал, Git и веб-поиск в "
            "одном окне."
        ),
    },
    "ui.settings.about.current_config": {"en": "Current configuration", "ru": "Текущая конфигурация"},
    "ui.settings.about.what": {"en": "What AXIOM can do", "ru": "Что умеет AXIOM"},
    "ui.settings.about.architecture": {"en": "Architecture", "ru": "Архитектура"},
    "ui.settings.about.privacy": {"en": "Privacy and security", "ru": "Приватность и безопасность"},
    "ui.settings.about.data_where": {"en": "Where data is stored", "ru": "Где хранятся данные"},
    "ui.settings.about.foot": {
        "en": "© 2026 BaToN41cK · distributed under the MIT license",
        "ru": "© 2026 BaToN41cK · распространяется по лицензии MIT",
    },
    "ui.settings.about.arch.scheme": {"en": "Architecture diagram", "ru": "Схема архитектуры"},
    "ui.settings.about.local_models": {"en": "local models", "ru": "локальные модели"},
    "ui.settings.about.cloud_models": {"en": "cloud models", "ru": "облачные модели"},
    "ui.settings.about.project_desc": {"en": "files · terminal · Git", "ru": "файлы · терминал · Git"},
    "ui.settings.about.feature.chat.title": {"en": "Chat and models", "ru": "Чат и модели"},
    "ui.settings.about.feature.chat.text": {
        "en": "Ollama and external APIs through one streaming runtime, reasoning and metrics.",
        "ru": "Ollama и внешние API через единый streaming runtime, reasoning и метрики.",
    },
    "ui.settings.about.feature.project.title": {"en": "Project work", "ru": "Работа с проектом"},
    "ui.settings.about.feature.project.text": {
        "en": "Search, read and edit files strictly inside the selected workspace folder.",
        "ru": "Поиск, чтение и правка файлов строго внутри выбранной рабочей папки.",
    },
    "ui.settings.about.feature.terminal.title": {"en": "Terminal and Git", "ru": "Терминал и Git"},
    "ui.settings.about.feature.terminal.text": {
        "en": "Commands, builds, tests and Git — with output right in the answer stream.",
        "ru": "Команды, сборка, тесты и Git — с выводом прямо в ленте ответа.",
    },
    "ui.settings.about.feature.agents.title": {"en": "Agents", "ru": "Агенты"},
    "ui.settings.about.feature.agents.text": {
        "en": "Analyst, coder, debugger, tester and reviewer in one trajectory.",
        "ru": "Analyst, coder, debugger, tester и reviewer в одной траектории.",
    },
    "ui.settings.about.feature.plugins.title": {"en": "Plugins", "ru": "Плагины"},
    "ui.settings.about.feature.plugins.text": {
        "en": "An extension catalog with documentation, permissions and trust.",
        "ru": "Каталог расширений с документацией, разрешениями и доверием.",
    },
    "ui.settings.about.feature.control.title": {"en": "Control", "ru": "Контроль"},
    "ui.settings.about.feature.control.text": {
        "en": "Tool calls, timeline, permissions and the stop reason are always visible.",
        "ru": "Tool calls, timeline, permissions и причина остановки всегда видны.",
    },
    "ui.settings.about.privacy.local": {
        "en": "API keys, history and memory are stored locally on this computer.",
        "ru": "API-ключи, история и память хранятся локально на этом компьютере.",
    },
    "ui.settings.about.privacy.auto": {
        "en": "auto_approve_all mode allows tools without asking — enable it only for a trusted project.",
        "ru": (
            "Режим auto_approve_all разрешает инструменты без вопросов — включайте его только для доверенного "
            "проекта."
        ),
    },
    "ui.settings.about.privacy.plugins": {
        "en": "Plugin code is not isolated: install extensions only from trusted sources.",
        "ru": "Код плагинов не изолирован: устанавливайте расширения только из надёжных источников.",
    },
    # Shared live/state labels (MessageList + OverlayPanel).
    "ui.state.idle": {"en": "Idle", "ru": "Ожидание"},
    "ui.state.completed": {"en": "Completed", "ru": "Завершено"},
    "ui.live.connecting": {"en": "Connecting", "ru": "Подключение"},
    "ui.live.loading": {"en": "Loading model", "ru": "Загружает модель"},
    "ui.live.thinking": {"en": "Thinking", "ru": "Размышляет"},
    "ui.live.tool_call": {"en": "Tool", "ru": "Инструмент"},
    "ui.live.searching": {"en": "Web search", "ru": "Веб-поиск"},
    "ui.live.receiving": {"en": "Generating", "ru": "Генерация"},
    "ui.live.cancelled": {"en": "Stopped", "ru": "Остановлено"},
    "ui.live.error": {"en": "Error", "ru": "Ошибка"},
    "ui.live.ready": {"en": "Ready", "ru": "Готов"},
    # Code block.
    "ui.code.copy": {"en": "Copy", "ru": "Копировать"},
    "ui.code.copy_code": {"en": "Copy code", "ru": "Скопировать код"},
    "ui.code.copied": {"en": "Copied", "ru": "Скопировано"},
    # Artifact view.
    "ui.artifact.type.table": {"en": "Table", "ru": "Таблица"},
    "ui.artifact.type.comparison": {"en": "Comparison", "ru": "Сравнение"},
    "ui.artifact.type.checklist": {"en": "Checklist", "ru": "Чек-лист"},
    "ui.artifact.type.mermaid": {"en": "Diagram", "ru": "Диаграмма"},
    "ui.artifact.type.chart": {"en": "Chart", "ru": "График"},
    "ui.artifact.download_md": {"en": "Download Markdown", "ru": "Скачать Markdown"},
    "ui.artifact.download_csv": {"en": "Download CSV", "ru": "Скачать CSV"},
    "ui.artifact.download_svg": {"en": "Download SVG", "ru": "Скачать SVG"},
    "ui.artifact.download_png": {"en": "Download PNG", "ru": "Скачать PNG"},
    # Diff review.
    "ui.diff.none": {"en": "No changes to review.", "ru": "Нет изменений для просмотра."},
    "ui.diff.aria": {"en": "Review agent changes", "ru": "Просмотр изменений агента"},
    "ui.diff.files_aria": {"en": "Changed files", "ru": "Изменённые файлы"},
    "ui.diff.file": {
        "en": "File {i} / {n} · snapshot of agent changes",
        "ru": "Файл {i} / {n} · снимок изменений агента",
    },
    "ui.diff.prev_file": {"en": "Previous file", "ru": "Предыдущий файл"},
    "ui.diff.next_file": {"en": "Next file", "ru": "Следующий файл"},
    "ui.diff.copied": {"en": "Diff copied", "ru": "Diff скопирован"},
    "ui.diff.copy_failed": {
        "en": "Could not copy the diff. Check clipboard access.",
        "ru": "Не удалось скопировать diff. Проверьте доступ к буферу обмена.",
    },
    "ui.diff.open_file": {"en": "Open file", "ru": "Открыть файл"},
    "ui.diff.open_aria": {"en": "Open {path}", "ru": "Открыть {path}"},
    "ui.diff.copy_diff": {"en": "Copy diff", "ru": "Копировать diff"},
    "ui.diff.incomplete": {
        "en": "Incomplete diff: counts cover only the received lines.",
        "ru": "Неполный diff: счётчики относятся только к полученным строкам.",
    },
    "ui.diff.hunk": {
        "en": "Hunk {i} / {n} · before / after line numbers",
        "ru": "Фрагмент {i} / {n} · номера до / после",
    },
    "ui.diff.prev_hunk": {"en": "Previous hunk", "ru": "Предыдущий фрагмент"},
    "ui.diff.next_hunk": {"en": "Next hunk", "ru": "Следующий фрагмент"},
    "ui.diff.line_before": {"en": "Line before", "ru": "Строка до"},
    "ui.diff.line_after": {"en": "Line after", "ru": "Строка после"},
    "ui.diff.hidden": {
        "en": "Hidden lines: {n}. The full received diff is available via copy.",
        "ru": "Скрыто строк: {n}. Полный полученный diff доступен через копирование.",
    },
    "ui.diff.unavailable": {"en": "Line diff unavailable.", "ru": "Построчный diff недоступен."},
    # Message list.
    "ui.chat.welcome": {"en": "How can Axiom help?", "ru": "Чем Axiom может помочь?"},
    "ui.chat.find_placeholder": {"en": "Find in conversation…", "ru": "Найти в разговоре…"},
    "ui.chat.no_matches": {"en": "no matches", "ru": "нет совпадений"},
    "ui.chat.find_prev": {"en": "Previous (Shift+Enter)", "ru": "Предыдущее (Shift+Enter)"},
    "ui.chat.find_next": {"en": "Next (Enter)", "ru": "Следующее (Enter)"},
    "ui.chat.close_find": {"en": "Close search (Esc)", "ru": "Закрыть поиск (Esc)"},
    "ui.chat.global_title": {
        "en": "File and terminal tools are disabled",
        "ru": "Файловые и терминальные инструменты отключены",
    },
    "ui.chat.global_note": {
        "en": "Global chat — no project active, file tools are disabled",
        "ru": "Глобальный чат — проект не активен, инструменты файлов выключены",
    },
    "ui.chat.suggest_search": {"en": "Sends with forced web search", "ru": "Отправит с принудительным веб-поиском"},
    "ui.chat.suggest_send": {"en": "Send this prompt", "ru": "Отправить этот запрос"},
    "ui.chat.suggestion.1": {"en": "What can you do?", "ru": "Что ты умеешь?"},
    "ui.chat.suggestion.2": {
        "en": "Write a Python function with error handling",
        "ru": "Напиши на Python функцию с обработкой ошибок",
    },
    "ui.chat.suggestion.3": {
        "en": "Review this code and suggest improvements",
        "ru": "Разбери этот код и предложи улучшения",
    },
    "ui.chat.suggestion.4": {
        "en": "What is the latest stable Python version?",
        "ru": "Какая сейчас последняя стабильная версия Python?",
    },
    "ui.chat.edit_title": {"en": "Edit and resend", "ru": "Изменить и отправить заново"},
    "ui.chat.edit": {"en": "Edit", "ru": "Изменить"},
    "ui.chat.quote_prompt": {"en": "Quote into prompt", "ru": "Цитировать в промпт"},
    "ui.chat.quote": {"en": "Quote", "ru": "Цитировать"},
    "ui.chat.editing": {"en": "Editing message", "ru": "Редактирование сообщения"},
    "ui.chat.editing_note": {
        "en": "the answer below will be regenerated",
        "ru": "ответ ниже будет сгенерирован заново",
    },
    "ui.chat.edit_hint": {"en": "Ctrl+Enter — send · Esc — cancel", "ru": "Ctrl+Enter — отправить · Esc — отмена"},
    "ui.chat.resend": {"en": "Resend", "ru": "Отправить заново"},
    "ui.chat.copy_answer": {"en": "Copy answer", "ru": "Копировать ответ"},
    "ui.chat.continue_title": {
        "en": "Continue generation from where it stopped",
        "ru": "Продолжить генерацию с места остановки",
    },
    "ui.chat.continue": {"en": "Continue generation", "ru": "Продолжить генерацию"},
    "ui.chat.stopped": {"en": "Generation stopped", "ru": "Генерация остановлена"},
    "ui.chat.stop_title": {"en": "Stop (Esc)", "ru": "Остановить (Esc)"},
    "ui.chat.tool_round_limit": {
        "en": "Agent stopped after the tool round limit",
        "ru": "Агент остановился после лимита tool rounds",
    },
    "ui.chat.gen_error": {"en": "Generation finished with an error", "ru": "Генерация завершена с ошибкой"},
    "ui.chat.load": {"en": "load {n}s", "ru": "загрузка {n}s"},
    "ui.chat.think_collapse": {"en": "Collapse reasoning", "ru": "Свернуть размышления"},
    "ui.chat.think_show": {"en": "Show reasoning", "ru": "Показать размышления"},
    "ui.chat.thinking": {"en": "Thinking", "ru": "Размышляет"},
    "ui.chat.thinking_process": {"en": "Reasoning process", "ru": "Процесс размышления"},
    # Overlay panel.
    "ui.overlay.title.help": {"en": "Help", "ru": "Справка"},
    "ui.overlay.title.status": {"en": "AXIOM status", "ru": "Состояние AXIOM"},
    "ui.overlay.title.tools": {"en": "Agent tools", "ru": "Инструменты агента"},
    "ui.overlay.title.context": {"en": "Context", "ru": "Контекст"},
    "ui.overlay.refresh": {"en": "Refresh data", "ru": "Обновить данные"},
    "ui.overlay.close": {"en": "Close (Esc)", "ru": "Закрыть (Esc)"},
    "ui.overlay.reading_status": {"en": "Reading core state…", "ru": "Читаю состояние ядра…"},
    "ui.overlay.ollama_version": {"en": "Ollama version", "ru": "Версия Ollama"},
    "ui.overlay.unavailable": {"en": "unavailable", "ru": "недоступна"},
    "ui.overlay.state": {"en": "State", "ru": "Состояние"},
    "ui.overlay.generation": {"en": "Generation", "ru": "Генерация"},
    "ui.overlay.running": {"en": "running", "ru": "выполняется"},
    "ui.overlay.not_running": {"en": "not running", "ru": "не выполняется"},
    "ui.overlay.history_count": {"en": "Conversations in history", "ru": "Разговоров в истории"},
    "ui.overlay.config": {"en": "Configuration", "ru": "Конфигурация"},
    "ui.overlay.tokens_out": {"en": "Tokens (last answer)", "ru": "Токенов (последний ответ)"},
    "ui.overlay.tokens_in": {"en": "Prompt tokens", "ru": "Токенов промпта"},
    "ui.overlay.speed": {"en": "Speed", "ru": "Скорость"},
    "ui.overlay.duration": {"en": "Duration", "ru": "Длительность"},
    "ui.overlay.current_model": {"en": "Current model", "ru": "Текущая модель"},
    "ui.overlay.no_tools": {
        "en": "does not report tool support — calls through it are unavailable, but web search can always be forced.",
        "ru": (
            "не сообщает о поддержке инструментов — вызовы через неё недоступны, но веб-поиск всегда можно "
            "запустить принудительно."
        ),
    },
    "ui.overlay.reading_tools": {"en": "Reading agent tools…", "ru": "Читаю инструменты агента…"},
    "ui.overlay.tools_none": {"en": "the agent reports none", "ru": "агент не сообщает ни об одном"},
    "ui.overlay.context_window": {"en": "Context window", "ru": "Окно контекста"},
    "ui.overlay.tokens": {"en": "tokens", "ru": "токенов"},
    "ui.overlay.model_no_report": {"en": "the model does not report", "ru": "модель не сообщает"},
    "ui.overlay.used_prompt": {"en": "Used (prompt)", "ru": "Использовано (промпт)"},
    "ui.overlay.messages": {"en": "Messages", "ru": "Сообщений"},
    "ui.overlay.files_images": {"en": "Files/images", "ru": "Файлов/изображений"},
    "ui.overlay.tool_calls": {"en": "Tool calls", "ru": "Вызовов инструментов"},
    "ui.overlay.sources": {"en": "Search sources", "ru": "Источников поиска"},
    "ui.overlay.ctx_note": {
        "en": "Exact token consumption appears after the first generation — AXIOM never invents numbers.",
        "ru": "Точное потребление токенов появится после первой генерации — AXIOM не выдумывает цифры.",
    },
    "ui.overlay.model_size": {"en": "Model size", "ru": "Размер модели"},
    "ui.overlay.parameters": {"en": "Parameters", "ru": "Параметры"},
    "ui.overlay.quantization": {"en": "Quantization", "ru": "Квантование"},
    # Task panel.
    "ui.task.aria": {"en": "Tasks", "ru": "Задачи"},
    "ui.task.panel": {"en": "Taskbook", "ru": "Задачник"},
    "ui.task.refresh": {"en": "Refresh tasks", "ru": "Обновить задачи"},
    "ui.task.goal_aria": {"en": "Task goal", "ru": "Цель задачи"},
    "ui.task.goal_placeholder": {
        "en": "Describe the task (e.g. «Fix the form validation bug and add tests»)…",
        "ru": "Опишите задачу (например: «Исправить ошибку валидации формы и добавить тесты»)...",
    },
    "ui.task.plan_title": {
        "en": "The AI will form a step-by-step plan in the taskbook that you can edit before running",
        "ru": "ИИ сформирует пошаговый план действий в задачнике, который можно отредактировать перед запуском",
    },
    "ui.task.plan": {"en": "Plan the task", "ru": "Спланировать задачу"},
    "ui.task.run_title": {
        "en": "Plan and start executing right away (Ctrl+Enter)",
        "ru": "Спланировать и сразу приступить к выполнению (Ctrl+Enter)",
    },
    "ui.task.run": {"en": "Run", "ru": "Выполнить"},
    "ui.task.none": {"en": "No tasks yet", "ru": "Задач пока нет"},
    "ui.task.none_sub": {
        "en": (
            "Write a goal above: the AI breaks it into concrete steps, gives a checklist, then implements each "
            "step in order and checks it off."
        ),
        "ru": (
            "Напишите цель выше: ИИ декомпозирует её на конкретные шаги, выдаст чеклист, после чего "
            "последовательно реализует каждый шаг и отметит галочкой."
        ),
    },
    "ui.task.review_recovery": {"en": "Review requires recovery", "ru": "Ревью требует восстановления"},
    "ui.task.open_execution": {"en": "Open execution →", "ru": "Открыть выполнение →"},
    # Task execution.
    "ui.taskexec.state.pending": {"en": "Ready to start", "ru": "Готова к запуску"},
    "ui.taskexec.state.analyzing": {"en": "Analyzing project", "ru": "Анализ проекта"},
    "ui.taskexec.state.planning": {"en": "Composing plan", "ru": "Составление плана"},
    "ui.taskexec.state.executing": {"en": "Running", "ru": "Выполнение"},
    "ui.taskexec.state.verifying": {"en": "Checking result", "ru": "Проверка результата"},
    "ui.taskexec.state.waiting_for_permission": {"en": "Waiting for approval", "ru": "Ожидает разрешения"},
    "ui.taskexec.state.waiting_for_user": {"en": "Needs a decision", "ru": "Требуется решение"},
    "ui.taskexec.state.completed": {"en": "Completed", "ru": "Завершена"},
    "ui.taskexec.state.failed": {"en": "Error", "ru": "Ошибка"},
    "ui.taskexec.state.cancelled": {"en": "Stopped", "ru": "Остановлена"},
    "ui.taskexec.budget.system": {"en": "System", "ru": "Система"},
    "ui.taskexec.budget.project": {"en": "Project", "ru": "Проект"},
    "ui.taskexec.budget.task": {"en": "Task", "ru": "Задача"},
    "ui.taskexec.budget.files": {"en": "Files", "ru": "Файлы"},
    "ui.taskexec.budget.tool_results": {"en": "Tool results", "ru": "Результаты инструментов"},
    "ui.taskexec.budget.conversation": {"en": "Conversation", "ru": "Диалог"},
    "ui.taskexec.aria": {"en": "Task execution", "ru": "Выполнение задачи"},
    "ui.taskexec.back": {"en": "Back to chat", "ru": "Вернуться в чат"},
    "ui.taskexec.chat": {"en": "Chat", "ru": "Чат"},
    "ui.taskexec.loading": {"en": "Starting task…", "ru": "Запускаю задачу…"},
    "ui.taskexec.now": {"en": "Now running", "ru": "Сейчас выполняется"},
    "ui.taskexec.tool_wait": {"en": "Waiting for approval", "ru": "Ожидается разрешение"},
    "ui.taskexec.tool_active": {"en": "Active tool", "ru": "Активный инструмент"},
    "ui.taskexec.tool_interrupted": {"en": "Interrupted tool", "ru": "Прерванный инструмент"},
    "ui.taskexec.tool": {"en": "tool", "ru": "инструмент"},
    "ui.taskexec.plan": {"en": "Execution plan", "ru": "План выполнения"},
    "ui.taskexec.plan_empty": {
        "en": "The plan appears after the task is analyzed.",
        "ru": "План появится после анализа задачи.",
    },
    "ui.taskexec.changed_files": {"en": "Changed files", "ru": "Изменённые файлы"},
    "ui.taskexec.diff": {"en": "Diff of changes ({n})", "ru": "Diff изменений ({n})"},
    "ui.taskexec.accepted": {"en": "Changes accepted", "ru": "Изменения приняты"},
    "ui.taskexec.rejected": {"en": "Changes rejected", "ru": "Изменения отклонены"},
    "ui.taskexec.review_pending": {
        "en": "Review becomes available after completion",
        "ru": "Ревью станет доступно после завершения",
    },
    "ui.taskexec.budget": {"en": "Context budget", "ru": "Бюджет контекста"},
    "ui.taskexec.commands": {"en": "Real commands", "ru": "Реальные команды"},
    "ui.taskexec.no_output": {"en": "No output yet", "ru": "Вывод пока не получен"},
    "ui.taskexec.checks": {"en": "Checks", "ru": "Проверки"},
    "ui.taskexec.error": {"en": "Execution error", "ru": "Ошибка выполнения"},
    "ui.taskexec.ready_review": {"en": "Result is ready for review", "ru": "Результат готов к ревью"},
    "ui.taskexec.stop": {"en": "Stop execution", "ru": "Остановить выполнение"},
    "ui.taskexec.details": {
        "en": "Details, review and task management",
        "ru": "Подробности, ревью и управление задачей",
    },
    # Task card.
    "ui.taskcard.state.pending": {"en": "Plan ready to run", "ru": "План готов к исполнению"},
    "ui.taskcard.state.analyzing": {"en": "Analyzing project…", "ru": "Анализ проекта…"},
    "ui.taskcard.state.planning": {"en": "Forming plan…", "ru": "Формирование плана…"},
    "ui.taskcard.state.executing": {"en": "Running steps…", "ru": "Выполнение шагов…"},
    "ui.taskcard.state.verifying": {"en": "Checking results…", "ru": "Проверка результатов…"},
    "ui.taskcard.state.waiting_for_permission": {"en": "Waiting for approval", "ru": "Ожидает разрешения"},
    "ui.taskcard.state.waiting_for_user": {"en": "Needs a decision", "ru": "Требуется решение"},
    "ui.taskcard.state.completed": {"en": "Completed successfully", "ru": "Завершена успешно"},
    "ui.taskcard.state.failed": {"en": "Execution error", "ru": "Ошибка выполнения"},
    "ui.taskcard.state.cancelled": {"en": "Stopped", "ru": "Остановлена"},
    "ui.taskcard.open_execution": {
        "en": "Open execution on the main screen",
        "ru": "Открыть выполнение на главном экране",
    },
    "ui.taskcard.delete": {"en": "Delete task", "ru": "Удалить задачу"},
    "ui.taskcard.permission": {"en": "Permission request", "ru": "Запрос разрешения"},
    "ui.taskcard.active_tool": {"en": "Active tool", "ru": "Активный инструмент"},
    "ui.taskcard.steps": {"en": "{done} of {total} steps ({pct}%)", "ru": "{done} из {total} шагов ({pct}%)"},
    "ui.taskcard.plan": {"en": "Execution plan:", "ru": "План выполнения:"},
    "ui.taskcard.step_done": {"en": "Step completed (click to undo)", "ru": "Шаг выполнен (клик — отменить)"},
    "ui.taskcard.step_toggle": {"en": "Click to mark complete", "ru": "Клик — пометить выполненным"},
    "ui.taskcard.step_edit_hint": {"en": "Click the pencil to edit", "ru": "Кликните на карандаш для редактирования"},
    "ui.taskcard.step_result": {"en": "Step result", "ru": "Результат шага"},
    "ui.taskcard.step_edit": {"en": "Edit step wording", "ru": "Редактировать формулировку шага"},
    "ui.taskcard.step_delete": {"en": "Remove step from plan", "ru": "Удалить шаг из плана"},
    "ui.taskcard.step_placeholder": {
        "en": "E.g. Add input validation…",
        "ru": "Например: Добавить проверку входных данных...",
    },
    "ui.taskcard.add": {"en": "Add", "ru": "Добавить"},
    "ui.taskcard.add_step": {"en": "Add a step to the plan", "ru": "Добавить шаг в план"},
    "ui.taskcard.no_plan": {
        "en": "The execution plan has not been formed yet.",
        "ru": "План выполнения ещё не сформирован.",
    },
    "ui.taskcard.changed_files": {"en": "Changed files ({n}):", "ru": "Изменённые файлы ({n}):"},
    "ui.taskcard.review": {
        "en": "Review changes ({n} files) · {status}",
        "ru": "Ревью изменений ({n} файлов) · {status}",
    },
    "ui.taskcard.accepted": {"en": "accepted", "ru": "принято"},
    "ui.taskcard.rejected": {"en": "rejected", "ru": "отклонено"},
    "ui.taskcard.pending": {"en": "awaiting decision", "ru": "ожидает решения"},
    "ui.taskcard.commands": {"en": "Task commands ({n})", "ru": "Команды задачи ({n})"},
    "ui.taskcard.processes": {"en": "Child processes ({n})", "ru": "Дочерние процессы ({n})"},
    "ui.taskcard.errors": {"en": "Execution errors ({n})", "ru": "Ошибки выполнения ({n})"},
    "ui.taskcard.checks": {"en": "Check results ({n})", "ru": "Результаты проверки ({n})"},
    "ui.taskcard.check_passed": {"en": "Check passed", "ru": "Проверка пройдена"},
    "ui.taskcard.check_failed": {"en": "Check failed", "ru": "Проверка не пройдена"},
    "ui.taskcard.reason": {"en": "Reason: {error}", "ru": "Причина: {error}"},
    "ui.taskcard.stop": {"en": "Stop", "ru": "Остановить"},
    "ui.taskcard.completed_review_pending": {
        "en": "Check passed · result ready for review",
        "ru": "Проверка пройдена · результат готов к ревью",
    },
    "ui.taskcard.rerun": {"en": "Run again", "ru": "Запустить повторно"},
    "ui.taskcard.repeat": {"en": "Repeat", "ru": "Повторить"},
    "ui.taskcard.acknowledge": {
        "en": "I confirm the file state after the interruption",
        "ru": "Подтверждаю состояние файлов после прерывания",
    },
    "ui.taskcard.start": {"en": "Start implementing", "ru": "Приступить к реализации"},
    "ui.taskcard.continue": {"en": "Continue execution", "ru": "Продолжить выполнение"},
    # Task resume.
    "ui.taskresume.text": {
        "en": "Completed steps saved: {completed}. Continuation starts from the unfinished step.",
        "ru": "Сохранено выполненных шагов: {completed}. Продолжение начнётся с незавершённого шага.",
    },
    "ui.taskresume.acknowledge": {
        "en": "I checked the files after stopping. The unfinished step may repeat some actions.",
        "ru": "Я проверил файлы после остановки. Незавершённый шаг может повторить часть действий.",
    },
    "ui.taskresume.resuming": {"en": "Resuming…", "ru": "Возобновление…"},
    "ui.taskresume.continue": {"en": "Continue execution", "ru": "Продолжить выполнение"},
    # Task delete.
    "ui.taskdelete.title": {"en": "Delete task?", "ru": "Удалить задачу?"},
    "ui.taskdelete.body": {
        "en": (
            "The plan, step results, commands and checks will be removed from the taskbook. Project files that "
            "were changed are not affected."
        ),
        "ru": (
            "План, результаты шагов, команды и проверки будут удалены из задачника. Изменённые файлы проекта не "
            "изменятся."
        ),
    },
    "ui.taskdelete.aria": {"en": "Delete task", "ru": "Удалить задачу"},
    # Task review actions.
    "ui.taskreview.not_saved": {
        "en": "Decision not saved. Check the error message and file state.",
        "ru": "Решение не сохранено. Проверьте сообщение об ошибке и состояние файлов.",
    },
    "ui.taskreview.failed": {
        "en": "Could not perform the review. Check the file state before retrying.",
        "ru": "Не удалось выполнить ревью. Проверьте состояние файлов перед повтором.",
    },
    "ui.taskreview.recover_incomplete": {
        "en": "Recovery not complete. Check conflicting files and refresh the tasks.",
        "ru": "Восстановление не завершено. Проверьте конфликтующие файлы и обновите задачи.",
    },
    "ui.taskreview.recover_failed": {
        "en": "Could not finish recovery. Do not delete files without checking.",
        "ru": "Не удалось завершить восстановление. Файлы не следует удалять без проверки.",
    },
    "ui.taskreview.interrupted": {"en": "Review interrupted · {reason}", "ru": "Ревью прервано · {reason}"},
    "ui.taskreview.recovery_required": {"en": "manual recovery needed", "ru": "нужно ручное восстановление"},
    "ui.taskreview.unfinished_journal": {"en": "an unfinished journal exists", "ru": "есть незавершённый журнал"},
    "ui.taskreview.journal_default": {
        "en": "An unfinished review journal was found. Do not decide until the file state is checked.",
        "ru": "Обнаружен незавершённый журнал ревью. Не принимайте решение, пока состояние файлов не проверено.",
    },
    "ui.taskreview.paths": {"en": "Paths to check:", "ru": "Пути, требующие проверки:"},
    "ui.taskreview.parent_changed": {
        "en": (
            "The parent directory or project root changed. Restore the original directory after checking its "
            "contents; do not delete saved copies until recovery completes."
        ),
        "ru": (
            "Изменился родительский каталог или корень проекта. Верните исходный каталог после проверки его "
            "содержимого; не удаляйте сохранённые копии до завершения восстановления."
        ),
    },
    "ui.taskreview.conflicts": {
        "en": (
            "Save conflicting files outside their current paths after manual checking. A retry does not overwrite "
            "other people's changes; do not delete saved copies until recovery succeeds."
        ),
        "ru": (
            "Сохраните конфликтующие файлы вне их текущих путей после ручной проверки. Повторная попытка не "
            "перезаписывает чужие изменения; сохранённые копии не удаляйте до успешного завершения."
        ),
    },
    "ui.taskreview.retry_recovery": {"en": "Retry safe recovery", "ru": "Повторить безопасное восстановление"},
    "ui.taskreview.accept": {"en": "Accept", "ru": "Принять"},
    "ui.taskreview.reject": {"en": "Reject", "ru": "Отклонить"},
    "ui.taskreview.confirm_aria": {"en": "File restore confirmation", "ru": "Подтверждение восстановления файлов"},
    "ui.taskreview.reject_title": {"en": "Reject changes?", "ru": "Отклонить изменения?"},
    "ui.taskreview.reject_body": {
        "en": (
            "AXIOM will restore saved files to before the task and delete files it created. If later manual edits "
            "are detected, the restore is blocked."
        ),
        "ru": (
            "AXIOM восстановит сохранённые файлы до задачи и удалит созданные ею файлы. Если обнаружены "
            "последующие ручные правки, восстановление будет заблокировано."
        ),
    },
    "ui.taskreview.scope": {
        "en": "Project: {scope} · saved paths: {n}",
        "ru": "Проект: {scope} · сохранённых путей: {n}",
    },
    "ui.taskreview.no_scope": {"en": "unspecified", "ru": "не указан"},
    "ui.taskreview.restore_reject": {"en": "Restore and reject", "ru": "Восстановить и отклонить"},
    # Providers panel.
    "ui.prov.loading": {"en": "Loading providers…", "ru": "Загрузка провайдеров…"},
    "ui.prov.none": {"en": "Providers not found.", "ru": "Провайдеры не найдены."},
    "ui.prov.active_model": {"en": "Active model", "ru": "Активная модель"},
    "ui.prov.no_model": {
        "en": "not selected — the default model is used",
        "ru": "не выбрана — используется модель по умолчанию",
    },
    "ui.prov.connected": {"en": "{n} of {total} connected", "ru": "{n} из {total} подключено"},
    "ui.prov.search": {"en": "Find provider", "ru": "Найти провайдера"},
    "ui.prov.list_aria": {"en": "Providers", "ru": "Провайдеры"},
    "ui.prov.status.connected": {"en": "Connected", "ru": "Подключён"},
    "ui.prov.status.local": {"en": "Local", "ru": "Локальный"},
    "ui.prov.status.need_key": {"en": "Key required", "ru": "Нужен ключ"},
    "ui.prov.connection": {"en": "Connection", "ru": "Подключение"},
    "ui.prov.get_key": {"en": "Get key", "ru": "Получить ключ"},
    "ui.prov.api_key": {"en": "API key", "ru": "API-ключ"},
    "ui.prov.key_saved": {"en": "•••••••••••• saved — leave empty", "ru": "•••••••••••• сохранён — оставьте пустым"},
    "ui.prov.key_placeholder": {"en": "Paste the key, e.g. sk-…", "ru": "Вставьте ключ, например sk-…"},
    "ui.prov.hide_key": {"en": "Hide key", "ru": "Скрыть ключ"},
    "ui.prov.show_key": {"en": "Show key", "ru": "Показать ключ"},
    "ui.prov.no_key": {
        "en": "No key needed — AXIOM connects to the server on this computer.",
        "ru": "Ключ не нужен — AXIOM подключится к серверу на этом компьютере.",
    },
    "ui.prov.server": {"en": "Server address", "ru": "Адрес сервера"},
    "ui.prov.not_set": {"en": "not set", "ru": "не задан"},
    "ui.prov.base_required": {"en": "Base URL — required", "ru": "Base URL — обязательно"},
    "ui.prov.key_local": {
        "en": "The key is stored locally. Checking refreshes the model list.",
        "ru": "Ключ хранится локально. Проверка обновит список моделей.",
    },
    "ui.prov.after_check": {
        "en": "The model list appears after checking.",
        "ru": "После проверки появится список моделей.",
    },
    "ui.prov.checking": {"en": "Checking…", "ru": "Проверяем…"},
    "ui.prov.recheck": {"en": "Check again", "ru": "Проверить снова"},
    "ui.prov.connect": {"en": "Connect", "ru": "Подключить"},
    "ui.prov.choose_model": {"en": "Choose a model", "ru": "Выберите модель"},
    "ui.prov.model_filter": {"en": "Filter models", "ru": "Фильтр моделей"},
    "ui.prov.context_window": {"en": "Context window", "ru": "Контекстное окно"},
    "ui.prov.no_filter": {"en": "No models match the filter.", "ru": "Нет моделей по фильтру."},
    "ui.prov.load_models": {
        "en": "Click «Check again» to load models.",
        "ru": "Нажмите «Проверить снова», чтобы загрузить модели.",
    },
    "ui.prov.connect_models": {
        "en": "Connect the provider — models will appear here.",
        "ru": "Подключите провайдера — модели появятся здесь.",
    },
    "ui.prov.cap.tools": {"en": "tools", "ru": "инструменты"},
    "ui.prov.cap.vision": {"en": "vision", "ru": "изображения"},
    "ui.prov.cap.reasoning": {"en": "reasoning", "ru": "рассуждения"},
    "ui.prov.cap.streaming": {"en": "streaming", "ru": "стриминг"},
    "ui.prov.cap.chat": {"en": "chat", "ru": "чат"},
    "ui.prov.cap.code": {"en": "code", "ru": "код"},
    "ui.prov.cap.json": {"en": "JSON", "ru": "JSON"},
    # MCP panel.
    "ui.mcp.hint": {
        "en": (
            "Connect an external MCP server over stdio — its tools become available to the model as "
            "mcp_<name>_<tool>."
        ),
        "ru": (
            "Подключите внешний MCP-сервер по stdio — его инструменты станут доступны модели как "
            "mcp_<имя>_<инструмент>."
        ),
    },
    "ui.mcp.name_placeholder": {"en": "Server name (e.g. filesystem)", "ru": "Имя сервера (например: filesystem)"},
    "ui.mcp.command_placeholder": {
        "en": "Command (e.g. npx -y @modelcontextprotocol/server-filesystem C:/workspace)",
        "ru": "Команда (например: npx -y @modelcontextprotocol/server-filesystem C:/workspace)",
    },
    "ui.mcp.add": {"en": "Add", "ru": "Добавить"},
    "ui.mcp.empty": {
        "en": "No MCP servers connected. Add the first one — its tools will appear for the agent.",
        "ru": "Нет подключённых MCP-серверов. Добавьте первый — его инструменты появятся у агента.",
    },
    "ui.mcp.connected": {"en": "connected", "ru": "подключён"},
    "ui.mcp.error": {"en": "error", "ru": "ошибка"},
    "ui.mcp.test_tool": {"en": "Call tool {tool} (real test)", "ru": "Вызвать инструмент {tool} (реальный тест)"},
    "ui.mcp.test_result": {"en": "Test result", "ru": "Результат теста"},
    "ui.mcp.test_error": {"en": "Test error", "ru": "Ошибка теста"},
    "ui.mcp.empty_result": {"en": "(empty result)", "ru": "(пустой результат)"},
    "ui.mcp.checking": {"en": "Checking…", "ru": "Проверка…"},
    "ui.mcp.test": {"en": "Test", "ru": "Проверить"},
    "ui.mcp.restart": {"en": "Restart", "ru": "Перезапустить"},
    # Skills panel.
    "ui.skills.source.builtin": {"en": "built-in", "ru": "встроенный"},
    "ui.skills.source.global": {"en": "global", "ru": "глобальный"},
    "ui.skills.source.project": {"en": "project", "ru": "проект"},
    "ui.skills.source.plugin": {"en": "plugin", "ru": "плагин"},
    "ui.skills.always_aria": {"en": "Always in context: {label}", "ru": "Всегда в контексте: {label}"},
    "ui.skills.triggers": {"en": "triggers: {triggers}", "ru": "триггеры: {triggers}"},
    "ui.skills.always": {"en": "always in context", "ru": "всегда в контексте"},
    "ui.skills.relevance": {"en": "by relevance", "ru": "по релевантности"},
    "ui.skills.hide": {"en": "Hide content", "ru": "Скрыть содержимое"},
    "ui.skills.show": {"en": "Show content", "ru": "Показать содержимое"},
    "ui.skills.hint": {
        "en": (
            "Skills are reusable stack instructions. Enabled ones always enter the context, the rest only by task "
            "relevance."
        ),
        "ru": (
            "Навыки — переиспользуемые инструкции по стеку. Включённые попадают в контекст всегда, остальные — "
            "только по релевантности к задаче."
        ),
    },
    "ui.skills.placeholder": {
        "en": "Describe a task — which skills fit? (e.g. fix python tests)",
        "ru": "Опишите задачу — какие навыки подойдут? (например: почини python-тесты)",
    },
    "ui.skills.suggest": {"en": "Suggest", "ru": "Подобрать"},
    "ui.skills.matches": {"en": "Matching skills", "ru": "Подходящие навыки"},
    "ui.skills.none": {"en": "No skills.", "ru": "Навыков нет."},
    # Plugins marketplace.
    "ui.plugins.title": {"en": "Extension catalog", "ru": "Каталог расширений"},
    "ui.plugins.sub": {
        "en": (
            "Extend the agent with new tools, skills and providers. Plugins install disabled and run only with "
            "your permission."
        ),
        "ru": (
            "Расширяйте агента новыми инструментами, навыками и провайдерами. Плагины устанавливаются выключенными "
            "и запускаются только с вашего разрешения."
        ),
    },
    "ui.plugins.from_folder": {"en": "From folder", "ru": "Из папки"},
    "ui.plugins.search": {"en": "Search plugins, tools, authors", "ru": "Поиск плагинов, инструментов, авторов"},
    "ui.plugins.filter.all": {"en": "All", "ru": "Все"},
    "ui.plugins.filter.installed": {"en": "Installed", "ru": "Установленные"},
    "ui.plugins.filter.enabled": {"en": "Enabled", "ru": "Включённые"},
    "ui.plugins.filter.catalog": {"en": "Catalog", "ru": "Каталог"},
    "ui.plugins.all_categories": {"en": "All categories", "ru": "Все категории"},
    "ui.plugins.not_found": {"en": "Nothing found", "ru": "Ничего не найдено"},
    "ui.plugins.none": {"en": "No plugins yet", "ru": "Плагинов пока нет"},
    "ui.plugins.not_found_hint": {
        "en": "Try changing the query or filter.",
        "ru": "Попробуйте изменить запрос или фильтр.",
    },
    "ui.plugins.none_hint": {
        "en": "Install a plugin from a folder — see docs/plugins.md.",
        "ru": "Установите плагин из папки — подробнее в docs/plugins.md.",
    },
    "ui.plugins.cap.tools": {"en": "Agent tools", "ru": "Инструменты агента"},
    "ui.plugins.cap.skills": {"en": "Skills", "ru": "Навыки"},
    "ui.plugins.cap.providers": {"en": "Model providers", "ru": "Провайдеры моделей"},
    "ui.plugins.cap.ui": {"en": "UI extensions", "ru": "Расширения интерфейса"},
    "ui.plugins.cap.hooks": {"en": "Hooks", "ru": "Хуки"},
    "ui.plugins.enabled": {"en": "Enabled", "ru": "Включён"},
    "ui.plugins.installed": {"en": "Installed", "ru": "Установлен"},
    "ui.plugins.unknown_author": {"en": "Unknown author", "ru": "Неизвестный автор"},
    "ui.plugins.custom": {"en": "Custom AXIOM plugin", "ru": "Пользовательский плагин AXIOM"},
    "ui.plugins.tools": {"en": "Tools", "ru": "Инструменты"},
    "ui.plugins.tool.one": {"en": "{n} tool", "ru": "{n} инструмент"},
    "ui.plugins.tool.few": {"en": "{n} tools", "ru": "{n} инструмента"},
    "ui.plugins.tool.many": {"en": "{n} tools", "ru": "{n} инструментов"},
    "ui.plugins.install": {"en": "Install", "ru": "Установить"},
    "ui.plugins.security_note": {
        "en": (
            "Plugin code runs with the AXIOM process permissions. The manifest and ui.scopes do not limit Python "
            "access. Enabling a plugin means agreeing to run its code in this and future sessions while it stays "
            "enabled."
        ),
        "ru": (
            "Код плагина выполняется с правами процесса AXIOM. Манифест и ui.scopes не ограничивают Python-доступ. "
            "Включение плагина означает согласие запускать его код в этой и следующих сессиях, пока плагин "
            "включён."
        ),
    },
    "ui.plugins.back": {"en": "All plugins", "ru": "Все плагины"},
    "ui.plugins.tab.overview": {"en": "Overview", "ru": "Обзор"},
    "ui.plugins.tab.docs": {"en": "Documentation", "ru": "Документация"},
    "ui.plugins.tab.panel": {"en": "Panel", "ru": "Панель"},
    "ui.plugins.tab.permissions": {"en": "Permissions", "ru": "Разрешения"},
    "ui.plugins.tab.details": {"en": "Details", "ru": "Сведения"},
    "ui.plugins.builtin": {"en": "Built-in AXIOM", "ru": "Встроенный AXIOM"},
    "ui.plugins.disable": {"en": "Disable", "ru": "Выключить"},
    "ui.plugins.enable": {"en": "Enable", "ru": "Включить"},
    "ui.plugins.remove_aria": {"en": "Remove plugin {name}", "ru": "Удалить плагин {name}"},
    "ui.plugins.tools_count": {"en": "tools", "ru": "инструментов"},
    "ui.plugins.skills_count": {"en": "skills", "ru": "навыков"},
    "ui.plugins.providers_count": {"en": "providers", "ru": "провайдеров"},
    "ui.plugins.status": {"en": "status", "ru": "статус"},
    "ui.plugins.not_installed": {"en": "not installed", "ru": "не установлен"},
    "ui.plugins.on": {"en": "On", "ru": "Вкл."},
    "ui.plugins.off": {"en": "Off", "ru": "Выкл."},
    "ui.plugins.tools_for_agent": {"en": "Tools for the agent", "ru": "Инструменты для агента"},
    "ui.plugins.skills_section": {"en": "Skills", "ru": "Навыки"},
    "ui.plugins.providers_section": {"en": "Model providers", "ru": "Провайдеры моделей"},
    "ui.plugins.how_to": {"en": "How to use", "ru": "Как использовать"},
    "ui.plugins.howto.1_installed": {"en": "The plugin is installed.", "ru": "Плагин установлен."},
    "ui.plugins.howto.1_install": {
        "en": "Click «Install» — the plugin copies into ~/.axiom/plugins/.",
        "ru": "Нажмите «Установить» — плагин скопируется в ~/.axiom/plugins/.",
    },
    "ui.plugins.howto.2": {
        "en": "Enable the plugin and confirm trust in its code.",
        "ru": "Включите плагин и подтвердите доверие к его коду.",
    },
    "ui.plugins.howto.3": {
        "en": "Ask the agent in chat — it will call the needed tool itself{example}.",
        "ru": "Попросите агента в чате — он сам вызовет нужный инструмент{example}.",
    },
    "ui.plugins.howto.3_example": {"en": ", e.g. {tool}", "ru": ", например {tool}"},
    "ui.plugins.no_docs": {"en": "No documentation", "ru": "Документации нет"},
    "ui.plugins.no_docs_hint": {
        "en": "The author did not add a README.md to the plugin folder.",
        "ru": "Автор не добавил README.md в папку плагина.",
    },
    "ui.plugins.perm_warn_title": {
        "en": "The plugin runs Python code without isolation",
        "ru": "Плагин выполняет Python-код без изоляции",
    },
    "ui.plugins.perm_warn_body": {
        "en": (
            "After enabling, the code can read and modify accessible files, access the network, environment "
            "variables and run processes with AXIOM's permissions."
        ),
        "ru": (
            "После включения код может читать и изменять доступные файлы, обращаться к сети, переменным окружения "
            "и запускать процессы с правами AXIOM."
        ),
    },
    "ui.plugins.manifest_caps": {"en": "Manifest capabilities", "ru": "Возможности из манифеста"},
    "ui.plugins.not_declared": {"en": "Not declared", "ru": "Не заявлены"},
    "ui.plugins.ui_scopes": {"en": "UI scopes (informational)", "ru": "UI scopes (информативно)"},
    "ui.plugins.id": {"en": "Identifier", "ru": "Идентификатор"},
    "ui.plugins.version": {"en": "Version", "ru": "Версия"},
    "ui.plugins.author": {"en": "Author", "ru": "Автор"},
    "ui.plugins.source": {"en": "Source", "ru": "Источник"},
    "ui.plugins.folder": {"en": "Folder", "ru": "Папка"},
    "ui.plugins.source.catalog": {"en": "AXIOM catalog", "ru": "Каталог AXIOM"},
    "ui.plugins.source.custom": {"en": "Custom", "ru": "Пользовательский"},
    "ui.plugins.category.utilities": {"en": "Utilities", "ru": "Утилиты"},
    "ui.plugins.category.productivity": {"en": "Productivity", "ru": "Продуктивность"},
    "ui.plugins.category.security": {"en": "Security", "ru": "Безопасность"},
    "ui.plugins.category.text": {"en": "Text", "ru": "Текст"},
    "ui.plugins.category.models": {"en": "Models", "ru": "Модели"},
    "ui.plugins.category.skills": {"en": "Skills", "ru": "Навыки"},
    "ui.plugins.category.tools": {"en": "Tools", "ru": "Инструменты"},
    "ui.plugins.category.extensions": {"en": "Extensions", "ru": "Расширения"},
    "ui.plugins.meta.calculator": {"en": "Calculator", "ru": "Калькулятор"},
    "ui.plugins.meta.datetime": {"en": "Date and time", "ru": "Дата и время"},
    "ui.plugins.meta.notes": {"en": "Notes", "ru": "Заметки"},
    "ui.plugins.meta.security": {"en": "Security", "ru": "Безопасность"},
    "ui.plugins.meta.texttools": {"en": "Text tools", "ru": "Текстовые инструменты"},
    # Provider brand taglines.
    "ui.prov.brand.anthropic": {
        "en": "Claude — strong at code and reasoning",
        "ru": "Claude — сильный в коде и рассуждениях",
    },
    "ui.prov.brand.openai": {"en": "GPT — versatile models", "ru": "GPT — универсальные модели"},
    "ui.prov.brand.openai_compatible": {
        "en": "Any server with the OpenAI API (/v1)",
        "ru": "Любой сервер с OpenAI API (/v1)",
    },
    "ui.prov.brand.gemini": {"en": "Gemini — long context", "ru": "Gemini — длинный контекст"},
    "ui.prov.brand.deepseek": {
        "en": "DeepSeek — inexpensive strong models",
        "ru": "DeepSeek — недорогие сильные модели",
    },
    "ui.prov.brand.xai": {"en": "Grok — fast code models", "ru": "Grok — быстрые модели для кода"},
    "ui.prov.brand.mistral": {"en": "Mistral and Codestral", "ru": "Mistral и Codestral"},
    "ui.prov.brand.qwen": {"en": "Qwen — open models by Alibaba", "ru": "Qwen — открытые модели Alibaba"},
    "ui.prov.brand.zai": {"en": "GLM — Zhipu models", "ru": "GLM — модели Zhipu"},
    "ui.prov.brand.openrouter": {"en": "Hundreds of models through one key", "ru": "Сотни моделей через один ключ"},
    "ui.prov.brand.together": {"en": "Open models in the cloud", "ru": "Открытые модели в облаке"},
    "ui.prov.brand.fireworks": {"en": "Fast inference of open models", "ru": "Быстрый инференс открытых моделей"},
    "ui.prov.brand.groq": {"en": "Ultra-fast inference on LPU", "ru": "Сверхбыстрый инференс на LPU"},
    "ui.prov.brand.cerebras": {"en": "The fastest inference", "ru": "Самый быстрый инференс"},
    "ui.prov.brand.ollama": {"en": "Local models on this computer", "ru": "Локальные модели на этом компьютере"},
    "ui.prov.brand.default": {"en": "Model provider", "ru": "Провайдер моделей"},
    # Orchestration board phases + agent status.
    "ui.orch.phase.planning": {"en": "Plan", "ru": "План"},
    "ui.orch.phase.working": {"en": "Work", "ru": "Работа"},
    "ui.orch.phase.review": {"en": "Review", "ru": "Review"},
    "ui.orch.phase.verification": {"en": "Check", "ru": "Проверка"},
    "ui.orch.phase.done": {"en": "Result", "ru": "Итог"},
    "ui.orch.status.pending": {"en": "queued", "ru": "в очереди"},
    "ui.orch.status.running": {"en": "working", "ru": "работает"},
    "ui.orch.status.done": {"en": "done", "ru": "готов"},
    "ui.orch.status.failed": {"en": "error", "ru": "ошибка"},
    "ui.orch.status.cancelled": {"en": "stopped", "ru": "остановлен"},
    "ui.orch.trace_thought": {"en": "train of thought", "ru": "ход мыслей"},
    "ui.orch.trace_details": {"en": "details", "ru": "детали"},
    "ui.orch.activity": {"en": "Activity", "ru": "Ход выполнения"},
    "ui.orch.step.one": {"en": "{n} step", "ru": "{n} шаг"},
    "ui.orch.step.few": {"en": "{n} steps", "ru": "{n} шага"},
    "ui.orch.step.many": {"en": "{n} steps", "ru": "{n} шагов"},
    "ui.orch.errors": {"en": "{n} errors", "ru": "{n} ошибок"},
    # Plugin panel host.
    "ui.plugin.panel_title": {"en": "Panel «{title}»", "ru": "Панель «{title}»"},
    "ui.plugin.reload": {"en": "Reload panel (hot reload)", "ru": "Перезагрузить панель (hot reload)"},
    "ui.plugin.panel_unavailable": {
        "en": "The plugin did not provide a UI document (ui/index.html) — the panel is unavailable.",
        "ru": "Плагин не предоставил UI-документ (ui/index.html) — панель недоступна.",
    },
    # Orchestration board extra labels.
    "ui.orch.no_verdict": {"en": "no verdict", "ru": "без вердикта"},
    "ui.orch.not_run": {"en": "not run", "ru": "не запускалась"},
    "ui.orch.title": {"en": "Orchestration", "ru": "Оркестрация"},
    "ui.orch.no_task": {"en": "no task passed", "ru": "задача не передана"},
    "ui.orch.active": {"en": "{n} active", "ru": "{n} активн."},
    "ui.orch.no_review": {"en": "no response", "ru": "ответ не получен"},
    "ui.orch.reports_title": {"en": "Agent reports", "ru": "Отчёты агентов"},
    "ui.orch.agent": {"en": "agent", "ru": "агент"},
    "ui.orch.no_report": {"en": "no report", "ru": "нет отчёта"},
    "ui.orch.tools_used": {"en": "tools: {n}", "ru": "инструментов: {n}"},
    "ui.orch.tools_ok": {"en": "ok {n}", "ru": "ok {n}"},
    "ui.orch.tools_failed": {"en": "errors {n}", "ru": "ошибок {n}"},
    "ui.orch.no_summary": {"en": "no summary", "ru": "сводка не получена"},
    "ui.orch.verdict.ok": {"en": "Done — check passed", "ru": "Готово — проверка пройдена"},
    "ui.orch.verdict.bad": {
        "en": "Reviewer has remarks or the check failed",
        "ru": "Есть замечания reviewer или проверка не прошла",
    },
    # Balance pill + payment dialog.
    "ui.pay.open_failed": {
        "en": "Could not open the browser. Scan the QR code or try again.",
        "ru": "Не удалось открыть браузер. Отсканируйте QR-код или попробуйте ещё раз.",
    },
    "ui.pay.balance_title": {
        "en": "Balance {amount} AXIOM USD-credits · AXIOM PRO",
        "ru": "Баланс {amount} AXIOM USD-кредитов · AXIOM PRO",
    },
    "ui.pay.balance_aria": {
        "en": "Balance {amount} AXIOM USD-credits. Open balance and AXIOM PRO",
        "ru": "Баланс {amount} AXIOM USD-кредитов. Открыть баланс и AXIOM PRO",
    },
    "ui.pay.balance": {"en": "Balance", "ru": "Баланс"},
    "ui.pay.signin": {"en": "Sign in", "ru": "Войти"},
    "ui.pay.pending": {"en": "Waiting for payment", "ru": "Ожидание оплаты"},
    "ui.pay.account": {"en": "Account", "ru": "Аккаунт"},
    "ui.pay.signin_axiom": {"en": "Sign in to AXIOM", "ru": "Вход в AXIOM"},
    "ui.pay.close": {"en": "Close payments", "ru": "Закрыть платежи"},
    "ui.pay.unavailable": {
        "en": "The payment server is not configured in this build of AXIOM.",
        "ru": "Платёжный сервер не настроен в этой сборке AXIOM.",
    },
    "ui.pay.server_error": {
        "en": "Could not reach the payment server.",
        "ru": "Не удалось связаться с платёжным сервером.",
    },
    "ui.pay.invalid_oauth": {"en": "Invalid OAuth link.", "ru": "Некорректная OAuth-ссылка."},
    "ui.pay.oauth_failed": {
        "en": "Provider sign-in failed. Return to AXIOM and try again.",
        "ru": "Вход через провайдера не выполнен. Вернитесь в AXIOM и попробуйте ещё раз.",
    },
    "ui.pay.oauth_timeout": {
        "en": "Sign-in timed out. Start sign-in again.",
        "ru": "Время ожидания входа истекло. Запустите вход ещё раз.",
    },
    # Auth panel.
    "ui.auth.pw.weak": {"en": "Weak", "ru": "Слабый"},
    "ui.auth.pw.medium": {"en": "Medium", "ru": "Средний"},
    "ui.auth.pw.good": {"en": "Good", "ru": "Хороший"},
    "ui.auth.pw.strong": {"en": "Strong", "ru": "Надёжный"},
    "ui.auth.stage.starting.title": {"en": "Creating a secure link", "ru": "Создаём защищённую ссылку"},
    "ui.auth.stage.starting.hint": {
        "en": "The one-time token is bound to this device",
        "ru": "Одноразовый токен привязан к этому устройству",
    },
    "ui.auth.stage.browser.title": {"en": "Opening the browser", "ru": "Открываем браузер"},
    "ui.auth.stage.browser.hint": {
        "en": "The provider page opens in the system browser",
        "ru": "Страница провайдера откроется в системном браузере",
    },
    "ui.auth.stage.waiting.title": {"en": "Waiting for confirmation", "ru": "Ожидаем подтверждение"},
    "ui.auth.stage.waiting.hint": {
        "en": "Allow access on the provider page",
        "ru": "Разрешите доступ на странице провайдера",
    },
    "ui.auth.stage.redeeming.title": {"en": "Creating the AXIOM session", "ru": "Создаём сессию AXIOM"},
    "ui.auth.stage.redeeming.hint": {
        "en": "Getting the token and loading the account",
        "ru": "Получаем токен и загружаем аккаунт",
    },
    "ui.auth.oauth_title": {"en": "Sign in with {provider}", "ru": "Вход через {provider}"},
    "ui.auth.oauth_sub": {
        "en": "Finish signing in in the browser and return to AXIOM — the window refreshes itself.",
        "ru": "Завершите вход в браузере и вернитесь в AXIOM — окно обновится само.",
    },
    "ui.auth.link_valid": {"en": "Link valid for {time} more", "ru": "Ссылка действует ещё {time}"},
    "ui.auth.reopen": {"en": "Open again", "ru": "Открыть снова"},
    "ui.auth.copy_link": {"en": "Copy link", "ru": "Скопировать ссылку"},
    "ui.auth.cancel": {"en": "Cancel", "ru": "Отменить"},
    "ui.auth.security": {
        "en": "AXIOM never sees your password for {provider}. Do not open sign-in links sent by other people.",
        "ru": "AXIOM никогда не видит ваш пароль от {provider}. Не открывайте ссылки входа, присланные другими людьми.",
    },
    "ui.auth.err.login": {
        "en": "Login: 3–48 characters — latin, digits, dot, hyphen or underscore.",
        "ru": "Логин: 3–48 символов — латиница, цифры, точка, дефис или подчёркивание.",
    },
    "ui.auth.err.pass": {
        "en": "Password must be at least 12 characters.",
        "ru": "Пароль должен содержать не менее 12 символов.",
    },
    "ui.auth.err.mismatch": {"en": "Passwords do not match.", "ru": "Пароли не совпадают."},
    "ui.auth.hero_tag": {"en": "Local AI agent and IDE.", "ru": "Локальный AI-агент и IDE."},
    "ui.auth.hero_tag2": {"en": "One account for balance and PRO.", "ru": "Один аккаунт для баланса и PRO."},
    "ui.auth.hero.balance": {"en": "AXIOM balance and PRO subscription", "ru": "Баланс AXIOM и подписка PRO"},
    "ui.auth.hero.oauth": {
        "en": "OAuth sign-in — no password handoff",
        "ru": "Вход через OAuth — без передачи паролей",
    },
    "ui.auth.hero.session": {
        "en": "Session stored only on this device",
        "ru": "Сессия хранится только на этом устройстве",
    },
    "ui.auth.hero.local": {"en": "Code and models stay local", "ru": "Код и модели остаются локальными"},
    "ui.auth.create_title": {"en": "Create account", "ru": "Создать аккаунт"},
    "ui.auth.welcome_back": {"en": "Welcome back", "ru": "С возвращением"},
    "ui.auth.create_sub": {
        "en": "A couple of minutes — balance and PRO are tied to the account.",
        "ru": "Пара минут — и баланс с PRO будут привязаны к аккаунту.",
    },
    "ui.auth.login_sub": {
        "en": "Sign in to manage balance and AXIOM PRO.",
        "ru": "Войдите, чтобы управлять балансом и AXIOM PRO.",
    },
    "ui.auth.mode_aria": {"en": "Sign-in mode", "ru": "Режим входа"},
    "ui.auth.login": {"en": "Sign in", "ru": "Вход"},
    "ui.auth.register": {"en": "Register", "ru": "Регистрация"},
    "ui.auth.continue_github": {"en": "Continue with GitHub", "ru": "Продолжить с GitHub"},
    "ui.auth.continue_google": {"en": "Continue with Google", "ru": "Продолжить с Google"},
    "ui.auth.checking": {"en": "checking", "ru": "проверка"},
    "ui.auth.not_configured": {"en": "not configured", "ru": "не настроено"},
    "ui.auth.server_note": {
        "en": (
            "The sign-in server did not answer — it may be asleep. The buttons work; the server wakes up when "
            "pressed."
        ),
        "ru": "Сервер входа не ответил — он мог «спать». Кнопки работают, сервер проснётся при нажатии.",
    },
    "ui.auth.check_again": {"en": "Check again", "ru": "Проверить снова"},
    "ui.auth.or_credentials": {"en": "or with login and password", "ru": "или по логину и паролю"},
    "ui.auth.username": {"en": "Username", "ru": "Имя пользователя"},
    "ui.auth.username_hint": {
        "en": "3–48 characters: latin, digits, «.», «-», «_»",
        "ru": "3–48 символов: латиница, цифры, «.», «-», «_»",
    },
    "ui.auth.password": {"en": "Password", "ru": "Пароль"},
    "ui.auth.password_placeholder": {"en": "at least 12 characters", "ru": "минимум 12 символов"},
    "ui.auth.hide_password": {"en": "Hide password", "ru": "Скрыть пароль"},
    "ui.auth.show_password": {"en": "Show password", "ru": "Показать пароль"},
    "ui.auth.caps": {"en": "Caps Lock is on", "ru": "Включён Caps Lock"},
    "ui.auth.repeat_password": {"en": "Repeat password", "ru": "Повторите пароль"},
    "ui.auth.save_password": {
        "en": "Save the password — recovery is not connected yet.",
        "ru": "Сохраните пароль — восстановление пока не подключено.",
    },
    "ui.auth.wait": {"en": "Please wait…", "ru": "Подождите…"},
    "ui.auth.submit_create": {"en": "Create account", "ru": "Создать аккаунт"},
    "ui.auth.submit_login": {"en": "Sign in to AXIOM", "ru": "Войти в AXIOM"},
    "ui.auth.have_account": {"en": "Already have an account? ", "ru": "Уже есть аккаунт? "},
    "ui.auth.new_here": {"en": "New to AXIOM? ", "ru": "Впервые в AXIOM? "},
    "ui.auth.signin_link": {"en": "Sign in", "ru": "Войти"},
    "ui.auth.create_link": {"en": "Create account", "ru": "Создать аккаунт"},
    # Account view.
    "ui.acct.fact.days": {"en": "30 days from the moment of payment", "ru": "30 дней с момента оплаты"},
    "ui.acct.fact.renew": {
        "en": "Renewal adds 30 days to the current end date in advance",
        "ru": "Продление заранее добавляет 30 дней к текущей дате окончания",
    },
    "ui.acct.fact.pay": {
        "en": "Card / YooMoney wallet or AXIOM-credits",
        "ru": "Оплата картой / кошельком ЮMoney или AXIOM-кредитами",
    },
    "ui.acct.fact.account": {
        "en": "One account for the desktop app and the terminal (TUI)",
        "ru": "Один аккаунт для desktop-приложения и терминала (TUI)",
    },
    "ui.acct.pro_activated": {"en": "AXIOM PRO activated", "ru": "AXIOM PRO активирован"},
    "ui.acct.balance_credited": {"en": "Balance topped up", "ru": "Баланс пополнен"},
    "ui.acct.payment_expired": {"en": "Payment expired", "ru": "Платёж истёк"},
    "ui.acct.below_minimum": {
        "en": "Received less than 100 ₽. Balance unchanged; the payment is recorded for reconciliation.",
        "ru": "Поступило меньше 100 ₽. Баланс не изменён; платёж записан для сверки.",
    },
    "ui.acct.late_payment": {
        "en": "Payment arrived after the order deadline. Contact support for reconciliation.",
        "ru": "Платёж поступил после срока заказа. Свяжитесь с поддержкой для сверки.",
    },
    "ui.acct.order_processed": {
        "en": "The order is already processed. The balance is not changed again.",
        "ru": "Заказ уже обработан. Баланс не изменён повторно.",
    },
    "ui.acct.amount_mismatch": {
        "en": "The amount does not match the order. Balance and AXIOM PRO unchanged.",
        "ru": "Сумма не совпала с заказом. Баланс и AXIOM PRO не изменены.",
    },
    "ui.acct.waiting_payment": {"en": "Waiting for payment", "ru": "Ожидание оплаты"},
    "ui.acct.session": {"en": "Session is stored on this device", "ru": "Сессия хранится на этом устройстве"},
    "ui.acct.refresh_aria": {"en": "Refresh account data", "ru": "Обновить данные аккаунта"},
    "ui.acct.logout": {"en": "Sign out", "ru": "Выйти"},
    "ui.acct.balance": {"en": "Balance", "ru": "Баланс"},
    "ui.acct.balance_unit": {
        "en": "AXIOM USD-credits · rate 100 ₽ = $1.00",
        "ru": "AXIOM USD-кредиты · курс 100 ₽ = $1.00",
    },
    "ui.acct.topup": {"en": "Top up", "ru": "Пополнить"},
    "ui.acct.subscription": {"en": "Subscription", "ru": "Подписка"},
    "ui.acct.day.one": {"en": "day", "ru": "день"},
    "ui.acct.day.few": {"en": "days", "ru": "дня"},
    "ui.acct.day.many": {"en": "days", "ru": "дней"},
    "ui.acct.left": {"en": "{unit} left", "ru": "{unit} осталось"},
    "ui.acct.until": {"en": "until {expiry}", "ru": "до {expiry}"},
    "ui.acct.not_active": {
        "en": "Subscription is not active. It turns on automatically after payment.",
        "ru": "Подписка не активна. После оплаты включится автоматически.",
    },
    "ui.acct.renew": {"en": "Renew", "ru": "Продлить"},
    "ui.acct.subscribe": {"en": "Subscribe", "ru": "Оформить"},
    "ui.acct.shortage": {"en": "Missing {amount}", "ru": "Не хватает {amount}"},
    "ui.acct.from_balance": {"en": "{amount} from balance", "ru": "{amount} с баланса"},
    "ui.acct.shortage_hint": {
        "en": "To pay from balance, {amount} is missing.",
        "ru": "Для оплаты с баланса не хватает {amount}.",
    },
    "ui.acct.quick_topup_aria": {"en": "Quick top-up amount", "ru": "Быстрая сумма пополнения"},
    "ui.acct.custom_amount": {"en": "Custom amount", "ru": "Своя сумма"},
    "ui.acct.you_pay": {"en": "You pay", "ru": "Вы платите"},
    "ui.acct.you_get": {"en": "You receive", "ru": "Получите"},
    "ui.acct.amount_range": {
        "en": "Enter an amount from 100 to 100 000 ₽ (up to kopecks).",
        "ru": "Введите сумму от 100 до 100 000 ₽ (до копеек).",
    },
    "ui.acct.topup_amount": {"en": "Top up {amount}", "ru": "Пополнить на {amount}"},
    "ui.acct.fixed_rate": {
        "en": "Fixed AXIOM rate, not a currency exchange rate.",
        "ru": "Фиксированный курс AXIOM, а не курс обмена валют.",
    },
    "ui.acct.step.created": {"en": "Order created", "ru": "Заказ создан"},
    "ui.acct.step.payment": {"en": "Payment on the YooMoney page", "ru": "Оплата на странице ЮMoney"},
    "ui.acct.step.confirmed": {"en": "Confirmed by the server", "ru": "Подтверждено сервером"},
    "ui.acct.pro_until": {"en": "Subscription active until {expiry}.", "ru": "Подписка активна до {expiry}."},
    "ui.acct.confirmed": {
        "en": "Confirmed {received} · credited {credited}.",
        "ru": "Подтверждено {received} · зачислено {credited}.",
    },
    "ui.acct.qr_aria": {"en": "QR code of the YooMoney payment page", "ru": "QR-код страницы оплаты ЮMoney"},
    "ui.acct.scan": {
        "en": "Scan the QR code with your phone or open the payment page in the browser.",
        "ru": "Отсканируйте QR-код телефоном или откройте страницу оплаты в браузере.",
    },
    "ui.acct.open_payment": {"en": "Open payment page", "ru": "Открыть страницу оплаты"},
    "ui.acct.link_copied": {"en": "Link copied", "ru": "Ссылка скопирована"},
    "ui.acct.copy_link": {"en": "Copy link", "ru": "Скопировать ссылку"},
    "ui.acct.webhook_note": {
        "en": (
            "The balance changes only after a signed YooMoney notification. Returning from the browser alone does "
            "not confirm payment."
        ),
        "ru": (
            "Баланс изменится только после подписанного уведомления ЮMoney. Возврат из браузера сам по себе оплату "
            "не подтверждает."
        ),
    },
    "ui.acct.topup_type": {"en": "Top-up", "ru": "Пополнение"},
    "ui.acct.pro_type": {"en": "AXIOM PRO", "ru": "AXIOM PRO"},
    "ui.acct.days_left": {"en": "/ {n} days", "ru": "/ {n} дней"},
    # Toasts / notifications (useAxiom).
    "ui.notify.answer_ready": {"en": "Answer ready", "ru": "Ответ готов"},
    "ui.notify.git_failed": {"en": "Git operation failed", "ru": "Операция Git не выполнена"},
    "ui.notify.commit_created": {"en": "Commit created", "ru": "Коммит создан"},
    "ui.notify.snapshot_failed": {"en": "Could not create a snapshot", "ru": "Не удалось создать снимок"},
    "ui.notify.snapshot_created": {"en": "Git snapshot created", "ru": "Снимок git создан"},
    "ui.notify.rollback_failed": {"en": "Rollback not performed", "ru": "Откат не выполнен"},
    "ui.notify.rollback_ok": {"en": "Changes rolled back to the snapshot", "ru": "Изменения откачены к снимку"},
    "ui.notify.diff_failed": {"en": "Could not get the diff", "ru": "Не удалось получить diff"},
    "ui.notify.switch_failed": {"en": "Could not switch to {branch}", "ru": "Не удалось переключиться на {branch}"},
    "ui.notify.branch": {"en": "Branch: {branch}", "ru": "Ветка: {branch}"},
    "ui.notify.ollama_unavailable": {"en": "Ollama unavailable", "ru": "Ollama недоступна"},
    "ui.notify.ollama_check": {
        "en": "Ollama unavailable — check the connection",
        "ru": "Ollama недоступна — проверьте подключение",
    },
    "ui.notify.connect_failed": {"en": "AXIOM could not connect to {url}", "ru": "AXIOM не смог подключиться к {url}"},
    "ui.notify.model_not_found": {
        "en": "Model {model} not found in Ollama — selected {fallback}",
        "ru": "Модель {model} не найдена в Ollama — выбрана {fallback}",
    },
    "ui.notify.gen_busy": {
        "en": "Generation is already running — stop it first",
        "ru": "Генерация уже идёт — сначала остановите её",
    },
    "ui.notify.gen_busy_esc": {
        "en": "Generation is already running — stop it (Esc)",
        "ru": "Генерация уже идёт — остановите её (Esc)",
    },
    "ui.notify.connect_provider": {
        "en": "Connect Ollama or an external provider",
        "ru": "Подключите Ollama или внешний provider",
    },
    "ui.notify.stopping": {"en": "Stopping…", "ru": "Останавливаю…"},
    "ui.notify.permission_stale": {
        "en": "The permission request is no longer relevant",
        "ru": "Запрос разрешения уже неактуален",
    },
    "ui.notify.nothing_regenerate": {
        "en": "Nothing to regenerate — send a message first",
        "ru": "Нечего перегенерировать — сначала отправьте сообщение",
    },
    "ui.notify.nothing_continue": {
        "en": "Nothing to continue — there is no answer in this chat yet",
        "ru": "Продолжать нечего — в этом чате ещё нет ответа",
    },
    "ui.notify.empty_message": {"en": "The message cannot be empty", "ru": "Сообщение не может быть пустым"},
    "ui.notify.no_message_edit": {"en": "No message to edit", "ru": "Нет сообщения для правки"},
    "ui.notify.conversation_not_found": {"en": "Conversation not found", "ru": "Разговор не найден"},
    "ui.notify.conversation_deleted": {"en": "Conversation deleted", "ru": "Разговор удалён"},
    "ui.notify.delete_partial": {
        "en": "Could not delete {failed} of {total} conversations",
        "ru": "Не удалось удалить {failed} из {total} разговоров",
    },
    "ui.notify.history_cleared": {"en": "History cleared — deleted {n}", "ru": "История очищена — удалено {n}"},
    "ui.notify.rename_failed": {"en": "Could not rename the conversation", "ru": "Не удалось переименовать разговор"},
    "ui.notify.renamed": {"en": "Conversation renamed", "ru": "Разговор переименован"},
    "ui.notify.pin_failed": {"en": "Could not pin the conversation", "ru": "Не удалось закрепить разговор"},
    "ui.notify.folder_failed": {
        "en": "Could not change the conversation folder",
        "ru": "Не удалось изменить папку разговора",
    },
    "ui.notify.model_unavailable": {
        "en": "Model {model} is no longer available — selected {fallback}",
        "ru": "Модель {model} больше не доступна — выбрана {fallback}",
    },
    "ui.notify.switch_busy": {
        "en": "Cannot switch model during generation — stop it (Esc)",
        "ru": "Нельзя переключить модель во время генерации — остановите её (Esc)",
    },
    "ui.notify.active_model": {"en": "Active model: {model}", "ru": "Активная модель: {model}"},
    "ui.notify.ollama_connected": {"en": "Ollama connected", "ru": "Ollama подключена"},
    "ui.notify.ollama_connected_empty": {
        "en": "Ollama connected — the model list is still empty",
        "ru": "Ollama подключена — список моделей пока пуст",
    },
    "ui.notify.review_recovered": {
        "en": "Review recovery completed; the task decision can be made again",
        "ru": "Восстановление ревью завершено; решение по задаче можно принять заново",
    },
    "ui.notify.plugin_found": {"en": "Found plugin: {name}", "ru": "Найден плагин: {name}"},
    "ui.notify.bundled_installed": {
        "en": "Built-in plugin «{name}» installed",
        "ru": "Встроенный плагин «{name}» установлен",
    },
    "ui.notify.memory_saved": {"en": "Entry saved to memory", "ru": "Запись сохранена в память"},
    "ui.notify.memory_updated": {"en": "Entry updated", "ru": "Запись обновлена"},
    "ui.notify.memory_not_found": {"en": "Entry not found", "ru": "Запись не найдена"},
    "ui.notify.memory_deleted": {"en": "Entry removed from memory", "ru": "Запись удалена из памяти"},
    "ui.notify.indexed": {
        "en": "Indexed «{name}»: {indexed} new/changed, {unchanged} unchanged",
        "ru": "Проиндексировано «{name}»: {indexed} новых/изменённых, {unchanged} без изменений",
    },
    "ui.notify.reindexed": {"en": "Collection «{name}» reindexed", "ru": "Коллекция «{name}» переиндексирована"},
    "ui.notify.collection_not_found": {"en": "Collection not found", "ru": "Коллекция не найдена"},
    "ui.notify.collection_deleted": {"en": "Collection «{name}» deleted", "ru": "Коллекция «{name}» удалена"},
    "ui.notify.plugin_status": {"en": "{name}: {status}", "ru": "{name}: {status}"},
    "ui.notify.plugin_updated": {"en": "updated", "ru": "обновлён"},
    "ui.notify.plugin_installed": {"en": "installed", "ru": "установлен"},
    "ui.notify.plugin_not_found": {"en": "Plugin «{name}» not found", "ru": "Плагин «{name}» не найден"},
    "ui.notify.plugin_enabled": {"en": "enabled", "ru": "включён"},
    "ui.notify.plugin_disabled": {"en": "disabled", "ru": "выключен"},
    "ui.notify.plugin_removed": {"en": "{name}: removed", "ru": "{name}: удалён"},
    "ui.notify.mcp_status": {"en": "MCP «{name}»: {status}", "ru": "MCP «{name}»: {status}"},
    "ui.notify.mcp_connected": {"en": "connected ({n} tools)", "ru": "подключён ({n} инструментов)"},
    "ui.notify.mcp_connect_error": {"en": "connection error", "ru": "ошибка подключения"},
    "ui.notify.mcp_not_found": {"en": "MCP «{name}» not found", "ru": "MCP «{name}» не найден"},
    "ui.notify.mcp_removed": {"en": "MCP «{name}» removed", "ru": "MCP «{name}» удалён"},
    "ui.notify.mcp_restarted": {"en": "restarted ({n} tools)", "ru": "перезапущен ({n} инструментов)"},
    "ui.notify.json_args": {
        "en": "Arguments must be a valid JSON object",
        "ru": "Аргументы должны быть валидным JSON-объектом",
    },
    "ui.notify.skill_enabled": {"en": "Skill «{id}» enabled", "ru": "Навык «{id}» включён"},
    "ui.notify.skill_disabled": {"en": "Skill «{id}» disabled", "ru": "Навык «{id}» выключен"},
    "ui.notify.route": {"en": "Route: {provider}/{model}", "ru": "Маршрут: {provider}/{model}"},
    "ui.notify.command_done": {"en": "Command «{title}» executed", "ru": "Команда «{title}» выполнена"},
    "ui.notify.command_error": {"en": "Command error: {error}", "ru": "Ошибка команды: {error}"},
    "ui.notify.command_error_plain": {"en": "not executed", "ru": "не выполнена"},
    "ui.notify.new_conversation": {"en": "New conversation", "ru": "Новый разговор"},
    "ui.notify.model_args_not_found": {
        "en": "Model «{args}» not found in Ollama or among connected providers",
        "ru": "Модель «{args}» не найдена в Ollama или среди подключённых провайдеров",
    },
    "ui.notify.orchestrate_usage": {
        "en": "Describe the task: /orchestrate <task>",
        "ru": "Опишите задачу: /orchestrate <задача>",
    },
    "ui.notify.search_usage": {"en": "Provide a query: /search <query>", "ru": "Укажите запрос: /search <запрос>"},
    "ui.notify.core_stopped": {"en": "AXIOM core stopped", "ru": "Ядро AXIOM остановлено"},
    "ui.notify.core_stopped_hint": {
        "en": "Restart the core with the button below or restart the app.",
        "ru": "Перезапустите ядро кнопкой ниже или перезапустите приложение.",
    },
    "ui.notify.restarting_core": {"en": "Restarting the AXIOM core…", "ru": "Перезапуск ядра AXIOM…"},
    "ui.notify.core_restarted": {"en": "Core restarted", "ru": "Ядро перезапущено"},
    "ui.notify.stop_gen_first": {"en": "Stop generation first", "ru": "Сначала остановите генерацию"},
    "ui.notify.stop_task_first": {"en": "Stop the task first", "ru": "Сначала остановите задачу"},
    "ui.notify.project": {"en": "Project: {name} ({kind})", "ru": "Проект: {name} ({kind})"},
    "ui.notify.project_search_failed": {
        "en": "Could not search the project",
        "ru": "Не удалось выполнить поиск по проекту",
    },
    "ui.notify.global_chat": {"en": "Global chat: no project active", "ru": "Глобальный чат: проект не активен"},
    "ui.notify.read_failed": {"en": "Could not read the file", "ru": "Не удалось прочитать файл"},
    "ui.notify.patch_failed": {"en": "Could not apply the patch", "ru": "Не удалось применить патч"},
    "ui.notify.file_updated": {"en": "File updated: {path}", "ru": "Файл обновлён: {path}"},
    "ui.notify.command_failed": {"en": "The command finished with an error", "ru": "Команда завершилась с ошибкой"},
    "ui.notify.terminal_failed": {"en": "The terminal did not start", "ru": "Терминал не запустился"},
    "ui.notify.terminal_send_failed": {
        "en": "Could not send the command to the terminal",
        "ru": "Не удалось отправить команду в терминал",
    },
    "ui.notify.access.readonly": {
        "en": "AI: read-only files, no changes and no terminal",
        "ru": "AI: только чтение файлов, без изменений и терминала",
    },
    "ui.notify.access.full": {"en": "AI: full access (careful)", "ru": "AI: полный доступ (осторожно)"},
    "ui.notify.access.workspace": {
        "en": "AI: work inside the project is allowed",
        "ru": "AI: разрешена работа внутри проекта",
    },
    # Tool activity list (ToolBits).
    "ui.toolbits.running": {"en": "running", "ru": "выполняется"},
    "ui.toolbits.done": {"en": "done", "ru": "готово"},
    "ui.toolbits.error": {"en": "error", "ru": "ошибка"},
    "ui.toolbits.cancelled": {"en": "cancelled", "ru": "отменено"},
    "ui.toolbits.sources": {"en": "Sources · {n}", "ru": "Источники · {n}"},
    # Tool call card (ui/ToolCallCard).
    "ui.toolcall.idle": {"en": "Idle", "ru": "Ожидает"},
    "ui.toolcall.queued": {"en": "Queued", "ru": "В очереди"},
    "ui.toolcall.running": {"en": "Running", "ru": "Выполняется"},
    "ui.toolcall.completed": {"en": "Done", "ru": "Готово"},
    "ui.toolcall.failed": {"en": "Error", "ru": "Ошибка"},
    "ui.toolcall.denied": {"en": "Denied", "ru": "Отклонено"},
    "ui.toolcall.cancelled": {"en": "Interrupted", "ru": "Прервано"},
    "ui.toolcall.hide_details": {"en": "Hide call details", "ru": "Скрыть детали вызова"},
    "ui.toolcall.show_details": {"en": "Show call details", "ru": "Показать детали вызова"},
    "ui.toolcall.duration": {"en": "Actual duration", "ru": "Фактическая длительность"},
    "ui.toolcall.error": {"en": "Error", "ru": "Ошибка"},
    "ui.toolcall.args": {"en": "Arguments", "ru": "Аргументы"},
    # ui/Card + ui/Input.
    "ui.card.no_data": {"en": "No data", "ru": "Нет данных"},
    "ui.input.clear_search": {"en": "Clear search", "ru": "Очистить поиск"},
    # Relative time (lib/format).
    "ui.reltime.just_now": {"en": "just now", "ru": "только что"},
    "ui.reltime.ago_min": {"en": "{n} min ago", "ru": "{n} мин назад"},
    "ui.reltime.ago_hour": {"en": "{n} h ago", "ru": "{n} ч назад"},
    "ui.reltime.ago_day": {"en": "{n} d ago", "ru": "{n} дн назад"},
    # Orchestration markdown export + fallbacks (lib/orchestration).
    "ui.orch.tool_error": {"en": "tool error", "ru": "ошибка инструмента"},
    "ui.orch.agent_failed_generic": {"en": "the agent finished with an error", "ru": "агент завершился с ошибкой"},
    "ui.orch.run_failed_generic": {
        "en": "the orchestration finished with a failure",
        "ru": "оркестрация завершилась сбоем",
    },
    "ui.orch.stopped_short": {"en": "Orchestration stopped", "ru": "Оркестрация остановлена"},
    "ui.orch.done_remarks": {"en": "Orchestration completed with remarks", "ru": "Оркестрация завершена с замечаниями"},
    "ui.orch.done_plain": {"en": "Orchestration completed", "ru": "Оркестрация завершена"},
    "ui.orch.export.mode": {"en": "Mode: `{mode}` · agents: {agents}", "ru": "Режим: `{mode}` · агенты: {agents}"},
    "ui.orch.export.error": {"en": "Error: {error}", "ru": "Ошибка: {error}"},
    "ui.orch.export.reports": {"en": "Agent reports", "ru": "Отчёты агентов"},
    "ui.orch.export.no_report": {"en": "no report", "ru": "нет отчёта"},
    "ui.orch.export.agents": {"en": "Agents", "ru": "Агенты"},
    "ui.orch.export.tools_ok": {
        "en": ", tools ok {ok}, errors {failed}",
        "ru": ", инструментов ok {ok}, ошибок {failed}",
    },
    "ui.orch.export.reviewer": {"en": "Reviewer ({verdict})", "ru": "Reviewer ({verdict})"},
    "ui.orch.export.no_review": {"en": "no response", "ru": "ответ не получен"},
    "ui.orch.export.not_run": {"en": "not run", "ru": "не запускалась"},
    "ui.orch.export.duration": {"en": "Execution time: {duration}", "ru": "Время выполнения: {duration}"},
    # Payment lib errors.
    "ui.pay.not_configured": {
        "en": "The payment server is not specified in this build of AXIOM.",
        "ru": "Платёжный сервер не указан в этой сборке AXIOM.",
    },
    "ui.pay.qr_invalid": {"en": "Invalid link for QR", "ru": "Некорректная ссылка для QR"},
    # W3.3: chat tab strip (project/model/context isolation).
    "ui.chattabs.aria": {"en": "Chat tabs", "ru": "Вкладки чата"},
    "ui.chattabs.new": {"en": "New tab", "ru": "Новая вкладка"},
    "ui.chattabs.new_title": {"en": "New chat tab (Ctrl+T)", "ru": "Новая вкладка чата (Ctrl+T)"},
    "ui.chattabs.close": {"en": "Close tab", "ru": "Закрыть вкладку"},
    "ui.chattabs.close_aria": {"en": "Close tab {title}", "ru": "Закрыть вкладку {title}"},
    "ui.chattabs.global": {"en": "Global chat", "ru": "Глобальный чат"},
    "ui.chattabs.running": {"en": "{n} background task", "ru": "{n} фоновая задача"},
    "ui.chattabs.running_few": {"en": "{n} background tasks", "ru": "{n} фоновые задачи"},
    "ui.chattabs.running_many": {"en": "{n} background tasks", "ru": "{n} фоновых задач"},
    "ui.chattabs.stop_first": {
        "en": "Stop the active generation before switching tabs",
        "ru": "Остановите активную генерацию перед переключением вкладок",
    },
    # W3.3: background knowledge indexing.
    "ui.knowledge.indexing": {"en": "Indexing {name}…", "ru": "Индексируется «{name}»…"},
    "ui.knowledge.indexing_hint": {
        "en": "Indexing runs in the background — you can keep chatting",
        "ru": "Индексация идёт в фоне — можно продолжать общаться",
    },
    "ui.knowledge.indexed": {
        "en": "«{name}» indexed: {n} new/changed, {k} unchanged",
        "ru": "«{name}» проиндексирована: {n} новых/изменённых, {k} без изменений",
    },
    "ui.knowledge.index_failed": {
        "en": "Indexing «{name}» failed: {error}",
        "ru": "Ошибка индексации «{name}»: {error}",
    },
    "ui.knowledge.index_cancelled": {
        "en": "Indexing «{name}» stopped",
        "ru": "Индексация «{name}» остановлена",
    },
    # W3.3: tray menu.
    "ui.tray.show": {"en": "Open AXIOM", "ru": "Открыть AXIOM"},
    "ui.tray.quit": {"en": "Quit AXIOM", "ru": "Выйти из AXIOM"},
    "ui.tray.running": {"en": "AXIOM — {n} task running", "ru": "AXIOM — {n} задача выполняется"},
    "ui.tray.running_few": {"en": "AXIOM — {n} tasks running", "ru": "AXIOM — {n} задачи выполняются"},
    "ui.tray.running_many": {"en": "AXIOM — {n} tasks running", "ru": "AXIOM — {n} задач выполняется"},
    "ui.tray.idle": {"en": "AXIOM", "ru": "AXIOM"},
}


def locales() -> list[str]:
    return [locale.value for locale in Locale]


def translate(key: str, locale: Locale | str = DEFAULT_LOCALE, **kwargs: Any) -> str:
    """Return the localized string for ``key``, falling back to the key itself."""
    locale_value = locale.value if isinstance(locale, Locale) else str(locale)
    entry = TRANSLATIONS.get(key)
    template = key
    if entry is not None:
        template = entry.get(locale_value) or entry.get("en") or key
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError):
        return template


__all__ = ["DEFAULT_LOCALE", "TRANSLATIONS", "Locale", "locales", "translate"]
