/**
 * Slash commands — the GUI mirror of `axiom.frontends.tui.widgets.commands`.
 *
 * The list is data (name, argument hint, description); the actions live in
 * `useAxiom`, where every command is wired to a real core call. Nothing here is
 * decorative: a command that is listed always does something.
 */

export interface SlashCommand {
  name: string;
  description: string;
  /** W3.8 i18n key for the description (core `ui.cmd.*` catalog). */
  descriptionKey?: string;
  argumentHint?: string;
  /** W3.8 i18n key for the argument hint (core `ui.cmd.arg.*` catalog). */
  argumentHintKey?: string;
  /** One compact glyph key from the shared command registry. */
  icon?: "chat" | "model" | "search" | "settings" | "terminal" | "plugin";
  /** Optional discoverability shortcut shown in the palette. */
  shortcut?: string;
  /** Hint shown in the palette for commands that open a panel. */
  group: "chat" | "models" | "workspace" | "system" | "harness";
  /** Set for a plugin-contributed command (W3.1) — routed to the plugin host. */
  pluginCommand?: PluginCommand;
}

/** A command declared by a plugin's ``ui`` block (W3.1). */
export interface PluginCommand {
  plugin: string;
  id: string;
  title: string;
}

export const COMMANDS: SlashCommand[] = [
  { name: "/help", description: "Справка по командам и горячим клавишам", descriptionKey: "ui.cmd.help", group: "system" },
  { name: "/new", description: "Новый чат", descriptionKey: "ui.cmd.new", group: "chat" },
  { name: "/clear", description: "Очистить текущий разговор", descriptionKey: "ui.cmd.clear", group: "chat" },
  { name: "/history", description: "История разговоров", descriptionKey: "ui.cmd.history", group: "chat" },
  { name: "/model", description: "Переключить модель", descriptionKey: "ui.cmd.model", argumentHint: "[name]", argumentHintKey: "ui.cmd.arg.name", group: "models" },
  { name: "/models", description: "Модели, возможности, состояние", descriptionKey: "ui.cmd.models", group: "models" },
  { name: "/permissions", description: "Режим разрешений: ask, auto_approve_safe, auto_approve_all", descriptionKey: "ui.cmd.permissions", group: "harness" },
  { name: "/profiles", description: "Системные prompt-профили", descriptionKey: "ui.cmd.profiles", group: "harness" },
  { name: "/memory", description: "Память: факты и предпочтения (добавить/удалить)", descriptionKey: "ui.cmd.memory", group: "harness" },
  { name: "/knowledge", description: "База знаний: коллекции, индексация, поиск с цитатами", descriptionKey: "ui.cmd.knowledge", group: "harness" },
  { name: "/trajectory", description: "Timeline запуска, tools, tokens и timing", descriptionKey: "ui.cmd.trajectory", group: "harness" },
  { name: "/providers", description: "Провайдеры, API-ключ, Test и выбор модели", descriptionKey: "ui.cmd.providers", group: "harness" },
  { name: "/agents", description: "Агенты, оркестратор и назначенные модели", descriptionKey: "ui.cmd.agents", group: "harness" },
  { name: "/plugins", description: "Установка и управление пользовательскими плагинами", descriptionKey: "ui.cmd.plugins", group: "harness" },
  { name: "/orchestrate", description: "Запустить задачу через ANALYST, CODER, DEBUGGER, TESTER и REVIEWER", descriptionKey: "ui.cmd.orchestrate", argumentHint: "задача", argumentHintKey: "ui.cmd.arg.task", group: "harness" },
  { name: "/context", description: "Контекст: токены, сообщения, файлы", descriptionKey: "ui.cmd.context", group: "chat" },
  { name: "/search", description: "Веб-поиск и ответ по источникам", descriptionKey: "ui.cmd.search", argumentHint: "query", argumentHintKey: "ui.cmd.arg.query", group: "workspace" },
  { name: "/tools", description: "Инструменты агента", descriptionKey: "ui.cmd.tools", group: "workspace" },
  { name: "/status", description: "Состояние Ollama, модели и ядра", descriptionKey: "ui.cmd.status", group: "system" },
  { name: "/settings", description: "Настройки AXIOM", descriptionKey: "ui.cmd.settings", group: "system" },
  { name: "/exit", description: "Закрыть AXIOM", descriptionKey: "ui.cmd.exit", group: "system" },
];

// ------------------------------------------------------- plugin commands (W3.1)

let pluginCommands: PluginCommand[] = [];

/** Replace the set of plugin-contributed commands (loaded from the core). */
export function setPluginCommands(commands: PluginCommand[]): void {
  pluginCommands = commands;
}

function pluginSlashCommands(): SlashCommand[] {
  return pluginCommands.map((command) => ({
    name: `/${command.id}`,
    description: command.title,
    group: "harness" as const,
    icon: "plugin" as const,
    pluginCommand: command,
  }));
}

function allCommands(): SlashCommand[] {
  return [...COMMANDS, ...pluginSlashCommands()];
}

/** Look up a plugin command by its bare id (e.g. ``hello-greet``). */
export function pluginCommandById(id: string): PluginCommand | undefined {
  return pluginCommands.find((c) => c.id === id);
}

export function matchingCommands(input: string): SlashCommand[] {
  const token = input.trim().split(" ")[0].toLowerCase();
  if (!token.startsWith("/")) return [];
  const prefix = token.slice(1);
  const all = allCommands();
  if (!prefix) return all;
  const exact = all.filter((c) => c.name.slice(1) === prefix);
  if (exact.length) return exact;
  const starts = all.filter((c) => c.name.slice(1).startsWith(prefix));
  if (starts.length) return starts;
  return all.filter((c) => c.name.slice(1).includes(prefix));
}

export function commandByName(name: string): SlashCommand | undefined {
  const clean = name.startsWith("/") ? name : `/${name}`;
  return allCommands().find((c) => c.name === clean);
}

/** Shared presentation metadata used by the Desktop palette and future adapters. */
const COMMAND_PRESENTATION: Record<string, { icon: NonNullable<SlashCommand["icon"]>; shortcut?: string }> = {
  "/new": { icon: "chat", shortcut: "Ctrl+N" },
  "/settings": { icon: "settings", shortcut: "Ctrl+," },
  "/model": { icon: "model" },
  "/models": { icon: "model" },
  "/search": { icon: "search" },
  "/tools": { icon: "terminal" },
  "/plugins": { icon: "plugin" },
};

export function commandPresentation(command: SlashCommand) {
  return COMMAND_PRESENTATION[command.name] ?? { icon: command.icon ?? "chat", shortcut: command.shortcut };
}

/** Split "/search python 3.15" into command name + rest. */
export function parseCommand(input: string): { name: string; args: string } {
  const trimmed = input.trim();
  const space = trimmed.indexOf(" ");
  if (space === -1) return { name: trimmed.toLowerCase(), args: "" };
  return { name: trimmed.slice(0, space).toLowerCase(), args: trimmed.slice(space + 1).trim() };
}

export const SHORTCUTS: { keys: string; label: string; labelKey?: string }[] = [
  { keys: "Enter", label: "Отправить сообщение", labelKey: "ui.shortcut.send" },
  { keys: "Shift+Enter", label: "Перенос строки", labelKey: "ui.shortcut.newline" },
  { keys: "Ctrl+Enter", label: "Отправить с принудительным веб-поиском", labelKey: "ui.shortcut.send_search" },
  { keys: "/", label: "Палитра команд (в пустом поле ввода)", labelKey: "ui.shortcut.palette" },
  { keys: "Esc", label: "Остановить генерацию / закрыть панель", labelKey: "ui.shortcut.stop" },
  { keys: "Ctrl+N", label: "Новый чат", labelKey: "ui.shortcut.new" },
  { keys: "Ctrl+B", label: "Показать/скрыть боковую панель", labelKey: "ui.shortcut.panel" },
  { keys: "Ctrl+K", label: "Поиск по истории", labelKey: "ui.shortcut.history_search" },
  { keys: "Ctrl+F", label: "Поиск по текущему разговору", labelKey: "ui.shortcut.chat_search" },
  { keys: "Ctrl+,", label: "Настройки", labelKey: "ui.shortcut.settings" },
  { keys: "Ctrl+/", label: "Фокус в поле ввода", labelKey: "ui.shortcut.focus_input" },
  { keys: "↑", label: "В пустом поле — редактировать прошлое сообщение", labelKey: "ui.shortcut.edit_last" },
  { keys: "Ctrl+C", label: "Копировать выделенный ответ", labelKey: "ui.shortcut.copy" },
];

/**
 * W3.8: localized views of the static tables above. `t` comes from
 * `lib/i18n` (injected to keep this module UI-framework free); plugin
 * command titles stay as-is — they are author-provided, not AXIOM chrome.
 */
export function localizedDescription(
  command: SlashCommand,
  t: (key: string) => string,
): string {
  if (command.descriptionKey) {
    const hit = t(command.descriptionKey);
    if (hit !== command.descriptionKey) return hit;
  }
  return command.description;
}

export function localizedArgumentHint(
  command: SlashCommand,
  t: (key: string) => string,
): string | undefined {
  if (command.argumentHintKey) {
    const hit = t(command.argumentHintKey);
    if (hit !== command.argumentHintKey) return hit;
  }
  return command.argumentHint;
}

export function localizedShortcutLabel(
  row: { label: string; labelKey?: string },
  t: (key: string) => string,
): string {
  if (row.labelKey) {
    const hit = t(row.labelKey);
    if (hit !== row.labelKey) return hit;
  }
  return row.label;
}
