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
  /** Hint shown in the palette for commands that open a panel. */
  group: "chat" | "models" | "workspace" | "system" | "harness";
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

export function matchingCommands(input: string): SlashCommand[] {
  const token = input.trim().split(" ")[0].toLowerCase();
  if (!token.startsWith("/")) return [];
  const prefix = token.slice(1);
  if (!prefix) return COMMANDS;
  const exact = COMMANDS.filter((c) => c.name.slice(1) === prefix);
  if (exact.length) return exact;
  const starts = COMMANDS.filter((c) => c.name.slice(1).startsWith(prefix));
  if (starts.length) return starts;
  return COMMANDS.filter((c) => c.name.slice(1).includes(prefix));
}

export function commandByName(name: string): SlashCommand | undefined {
  const clean = name.startsWith("/") ? name : `/${name}`;
  return COMMANDS.find((c) => c.name === clean);
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
