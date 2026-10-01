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
  argumentHint?: string;
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
  { name: "/help", description: "Справка по командам и горячим клавишам", group: "system" },
  { name: "/new", description: "Новый чат", group: "chat" },
  { name: "/clear", description: "Очистить текущий разговор", group: "chat" },
  { name: "/history", description: "История разговоров", group: "chat" },
  { name: "/model", description: "Переключить модель", argumentHint: "[name]", group: "models" },
  { name: "/models", description: "Модели, возможности, состояние", group: "models" },
  { name: "/permissions", description: "Режим разрешений: ask, auto_approve_safe, auto_approve_all", group: "harness" },
  { name: "/profiles", description: "Системные prompt-профили", group: "harness" },
  { name: "/memory", description: "Память: факты и предпочтения (добавить/удалить)", group: "harness" },
  { name: "/knowledge", description: "База знаний: коллекции, индексация, поиск с цитатами", group: "harness" },
  { name: "/trajectory", description: "Timeline запуска, tools, tokens и timing", group: "harness" },
  { name: "/providers", description: "Провайдеры, API-ключ, Test и выбор модели", group: "harness" },
  { name: "/agents", description: "Агенты, оркестратор и назначенные модели", group: "harness" },
  { name: "/plugins", description: "Установка и управление пользовательскими плагинами", group: "harness" },
  { name: "/orchestrate", description: "Запустить задачу через ANALYST, CODER, DEBUGGER, TESTER и REVIEWER", argumentHint: "задача", group: "harness" },
  { name: "/context", description: "Контекст: токены, сообщения, файлы", group: "chat" },
  { name: "/search", description: "Веб-поиск и ответ по источникам", argumentHint: "query", group: "workspace" },
  { name: "/tools", description: "Инструменты агента", group: "workspace" },
  { name: "/status", description: "Состояние Ollama, модели и ядра", group: "system" },
  { name: "/settings", description: "Настройки AXIOM", group: "system" },
  { name: "/exit", description: "Закрыть AXIOM", group: "system" },
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

export const SHORTCUTS: { keys: string; label: string }[] = [
  { keys: "Enter", label: "Отправить сообщение" },
  { keys: "Shift+Enter", label: "Перенос строки" },
  { keys: "Ctrl+Enter", label: "Отправить с принудительным веб-поиском" },
  { keys: "/", label: "Палитра команд (в пустом поле ввода)" },
  { keys: "Esc", label: "Остановить генерацию / закрыть панель" },
  { keys: "Ctrl+N", label: "Новый чат" },
  { keys: "Ctrl+B", label: "Показать/скрыть боковую панель" },
  { keys: "Ctrl+K", label: "Поиск по истории" },
  { keys: "Ctrl+,", label: "Настройки" },
  { keys: "Ctrl+/", label: "Фокус в поле ввода" },
  { keys: "↑", label: "В пустом поле — редактировать прошлое сообщение" },
  { keys: "Ctrl+C", label: "Копировать выделенный ответ" },
];
