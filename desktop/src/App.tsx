import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Folder, GitBranch, ListChecks, Moon, PanelLeft, PanelRight, Sun, Terminal as TerminalIcon } from "lucide-react";
import BootScreen from "./components/BootScreen";
import ProjectSelector from "./components/ProjectSelector";
import OverlayPanel from "./components/OverlayPanel";
import SettingsModal from "./components/SettingsModal";
import Sidebar from "./components/Sidebar";
import MessageList from "./components/MessageList";
import Composer from "./components/Composer";
import ModelSelector from "./components/ModelSelector";
import { useAxiom } from "./hooks/useAxiom";
import Presence from "./components/Presence";
import { installSoundActivation, playUiSound } from "./lib/sound";
import { clampRightPanelWidth } from "./lib/panelSize";
import TaskExecution from "./components/TaskExecution";
import Balance from "./components/Balance";

import Explorer from "./components/Explorer";
import GitPanel from "./components/GitPanel";
import TerminalPanel from "./components/TerminalPanel";
import TaskPanel from "./components/TaskPanel";
import ConfirmDialog from "./components/ConfirmDialog";
import type { AxiomStore } from "./hooks/useAxiom";
import type { ThemePreset } from "./types";

const THEME_ORDER: ThemePreset[] = [
  "obsidian", "graphite", "rosewood", "nord", "midnight", "terminal", "solarized", "light",
];
const THEME_LABELS: Record<ThemePreset, string> = {
  obsidian: "AXIOM Dark",
  graphite: "Graphite Grey",
  rosewood: "Rose Noir",
  nord: "Nord Frost",
  midnight: "Midnight Blue",
  terminal: "Terminal Green",
  solarized: "Solarized Dark",
  light: "AXIOM Light",
};

function WorkbenchSide({ store: s }: { store: AxiomStore }) {
  const panelRef = useRef<HTMLElement>(null);
  useEffect(() => { if (panelRef.current) panelRef.current.inert = !s.rightPanelOpen; }, [s.rightPanelOpen]);
  const [tab, setTab] = useState<"files" | "terminal" | "git" | "tasks">("files");
  // A file opened from task review must be visible even from another tab.
  useEffect(() => { if (s.openFile) setTab("files"); }, [s.openFile]);
  const pickTab = (next: typeof tab) => {
    if (tab !== next) playUiSound("panel");
    setTab(next);
  };
  // Drag-to-resize of the tools panel (§8). Width lives in the store and is
  // persisted; the CSS transition is switched off while dragging (body.resizing).
  const dragging = useRef(false);
  const lastWidth = useRef(s.rightPanelWidth);
  useEffect(() => {
    const onMove = (event: MouseEvent) => {
      if (!dragging.current) return;
      const next = clampRightPanelWidth(window.innerWidth - event.clientX);
      lastWidth.current = next;
      s.setRightPanelWidth(next);
    };
    const onUp = () => {
      if (!dragging.current) return;
      dragging.current = false;
      document.body.classList.remove("resizing");
      s.commitRightPanelWidth(lastWidth.current);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [s]);
  const startDrag = () => {
    dragging.current = true;
    document.body.classList.add("resizing");
  };
  return (
    <aside
      ref={panelRef}
      className="workbench-side"
      style={{ "--side-w": `${s.rightPanelWidth}px` } as CSSProperties}
    >
      <div className="side-resizer" onMouseDown={startDrag} title="Изменить размер панели" />
      <div className="side-tabs">
        <button className={tab === "files" ? "active" : ""} onClick={() => pickTab("files")}>
          <Folder size={13} strokeWidth={1.8} />
          <span>Файлы</span>
        </button>
        <button className={tab === "terminal" ? "active" : ""} onClick={() => pickTab("terminal")}>
          <TerminalIcon size={13} strokeWidth={1.8} />
          <span>Терминал</span>
        </button>
        <button className={tab === "git" ? "active" : ""} onClick={() => pickTab("git")}>
          <GitBranch size={13} strokeWidth={1.8} />
          <span>Git</span>
        </button>
        <button className={tab === "tasks" ? "active" : ""} onClick={() => pickTab("tasks")}>
          <ListChecks size={13} strokeWidth={1.8} /><span>Задачи</span>
        </button>
      </div>
      {tab === "tasks" && (
        <TaskPanel
          tasks={s.tasks}
          busy={s.generating || s.taskRequestPending}
          onStart={s.startTask}
          onResume={s.resumeTask}
          onCancel={s.cancelTask}
          onRefresh={s.refreshTasks}
          onPlan={s.planTask}
          onCreate={s.createTask}
          onSave={s.saveTask}
          onDelete={s.deleteTask}
          onReview={s.reviewTask}
          onRecover={s.recoverReview}
          onInspect={s.setFocusedTaskId}
        />
      )}
      {tab === "files" && (
        <Explorer
          root={s.workspace?.current?.path ?? null}
          tree={s.tree}
          loading={s.treeLoading}
          gitStatus={s.gitStatus?.ok ? s.gitStatus.content : null}
          openFile={s.openFile}
          onRefresh={() => void s.loadTree()}
          onOpenFile={(p) => void s.openWorkspaceFile(p)}
          onCloseFile={() => s.setOpenFile(null)}
          search={s.projectSearch}
          onSearch={s.setProjectSearch}
          searchResults={s.projectSearchResults.hits}
          searchLoading={s.projectSearching}
          onOpenSearchHit={s.openProjectSearchHit}
        />
      )}
      {tab === "terminal" && (
        <TerminalPanel
          cwd={s.workspace?.current?.path ?? null}
          enabled={
            !!s.workspace?.current &&
            s.config?.terminal_enabled !== false &&
            s.config?.access_mode !== "read_only"
          }
          history={s.termHistory}
          pendingConfirm={s.pendingTerm}
          onRun={(c) => void s.runTerminal(c)}
          onConfirm={(ok) => void s.confirmTerminal(ok)}
        />
      )}
      {tab === "git" && (
        <GitPanel
          project={s.workspace?.current ?? null}
          status={s.gitStatus}
          log={s.gitLog}
          onRefresh={() => void s.loadGit()}
        />
      )}
    </aside>
  );
}

export default function App() {
  const s = useAxiom();
  useEffect(installSoundActivation, []);

  // Reflect the configured theme on <html>; styles.css owns the complete palette.
  // The coordinated fade is enabled only for the duration of a theme switch.
  const configuredTheme = s.config?.theme;
  const theme: ThemePreset = configuredTheme && THEME_ORDER.includes(configuredTheme)
    ? configuredTheme
    : "obsidian";
  const themeIndex = THEME_ORDER.indexOf(theme);
  const nextTheme = THEME_ORDER[(themeIndex + 1) % THEME_ORDER.length];
  useEffect(() => {
    const root = document.documentElement;
    if (root.dataset.theme) root.classList.add("theme-anim");
    root.dataset.theme = theme;
    root.dataset.accent = s.config?.accent ?? "garnet";
    root.classList.toggle("no-panel-hover", s.config?.panel_hover === false);
    const timer = window.setTimeout(() => root.classList.remove("theme-anim"), 480);
    return () => window.clearTimeout(timer);
  }, [theme, s.config?.accent, s.config?.panel_hover]);

  // Settings → General → animations off silences every transition at once.
  useEffect(() => {
    document.documentElement.classList.toggle("no-anim", s.config?.animations === false);
  }, [s.config?.animations]);

  const toasts = <div className="toast-stack" aria-live="polite" aria-atomic="false">{s.toasts.map((toast) => (
    <div key={toast.id} className={"toast toast-" + toast.kind + (toast.leaving ? " leaving" : "")}>
      {toast.text}
    </div>
  ))}</div>;

  // The boot sequence is a real screen: it shows while the probes run and
  // explains a failure instead of leaving an empty window behind.
  if (s.phase !== "ready") {
    return (
      <div className="app">
        <BootScreen
          phase={s.phase}
          steps={s.bootSteps}
          error={s.bootError}
          onRetry={() => void s.runBoot()}
          onRestartCore={() => void s.restartCore()}
          onOpenSettings={() => s.openSettings()}
        />
        <Presence open={s.settingsOpen && !!s.config}>
        {s.config && (
                   <SettingsModal
           config={s.config}
           section={s.settingsSection}
           setSection={s.setSettingsSection}
           onClose={() => s.setSettingsOpen(false)}
           onSave={s.saveConfig}
           onRestartCore={s.restartCore}
           providerRows={s.providerRows}
           providerModels={s.providerModels}
           providerLoading={s.providerLoading}
           onProviderSaveSettings={s.providerSaveSettings}
           onProviderPickModel={s.providerPickModel}
           onLoadProviders={s.loadProviders}
           pluginRows={s.pluginRows}
           pluginLoading={s.pluginLoading}
           onLoadPlugins={s.loadPlugins}
           onInstallPlugin={s.installPluginFromFolder}
           onTogglePlugin={s.togglePlugin}
           onRemovePlugin={s.removePlugin}
           bundledPlugins={s.bundledPlugins}
           onInstallBundledPlugin={s.installBundledPlugin}

           memoryRows={s.memoryRows}
           memoryLoading={s.memoryLoading}
           onLoadMemory={s.loadMemory}
           onAddMemory={s.addMemory}
           onEditMemory={s.editMemory}
           onDeleteMemory={s.deleteMemory}

           knowledgeRows={s.knowledgeRows}
           knowledgeLoading={s.knowledgeLoading}
           knowledgeHits={s.knowledgeHits}
           onLoadKnowledge={s.loadKnowledge}
           onAddKnowledge={s.addKnowledgeCollection}
           onReindexKnowledge={s.reindexKnowledge}
           onRemoveKnowledge={s.removeKnowledgeCollection}
           onSearchKnowledge={s.searchKnowledge}

           searchProviders={s.searchProviders}
           onLoadSearchProviders={s.loadSearchProviders}
           onRunSearchTest={s.runSearchTest}
           searchTestResult={s.searchTestResult}
           searchTesting={s.searchTesting}
          />
        )}
        </Presence>
        {toasts}
      </div>
    );
  }

  return (
    <div className="app">
      <Sidebar
        open={s.sidebarOpen}
        drawer={false}
        width={s.sidebarWidth}
        onWidthChange={s.setSidebarWidth}
        onWidthCommit={s.commitSidebarWidth}
        chats={s.filteredChats}
        totalChats={s.chats.length}
        activeChatId={s.activeChatId}
        search={s.chatSearch}
        onSearch={s.setChatSearch}
        onNewChat={s.newChat}
        onOpenChat={s.openChat}
        onDeleteChat={s.deleteChat}
        onRenameChat={s.renameChat}
        onDeleteAllChats={s.deleteAllChats}
        onOpenSettings={() => s.openSettings()}
        onOpenModels={() => void s.openOverlay("status")}
        onClose={() => s.toggleSidebar()}
        activeModel={s.modelDetail}
      />

      <div className="main">
        <header className="topbar">
          <button
            className="icon-btn"
            title="Панель показать, скрыть L (Ctrl+B)"
            aria-label="Панель показать, скрыть L"
            aria-pressed={s.sidebarOpen}
            onClick={() => s.toggleSidebar()}
          >
            <PanelLeft size={17} strokeWidth={1.8} />
          </button>
          <ProjectSelector
            current={s.workspace?.current ?? null}
            recent={s.workspace?.recent ?? []}
            pinned={s.workspace?.pinned ?? []}
            onOpen={s.openWorkspaceDialog}
            onSwitch={(path) => void s.switchWorkspace(path)}
            onClear={() => void s.clearWorkspace()}
            onRemove={(path) => void s.removeWorkspace(path)}
            onTogglePin={(path) => void s.toggleWorkspacePin(path)}
          />
          <div className="topbar-spacer" />
          <div className="topbar-context" title="Текущий маршрут">
            <span className="topbar-provider">{s.activeModelProvider === "ollama" ? "Ollama" : s.activeModelProvider}</span>
            <span className="topbar-model">{s.activeModel ?? "модель не выбрана"}</span>
            <span className="topbar-tools">{s.activeModelInfo?.capabilities.includes("tools") ? "Tools включены" : "Только текст"}</span>
          </div>
          <div className="access-dot" title={s.accessTitle}>{s.accessLabel}</div>
          <Balance />
          <button
            className="icon-btn"
            title={`Тема: ${THEME_LABELS[theme]} · Переключить на ${THEME_LABELS[nextTheme]}`}
            aria-label={`Тема ${THEME_LABELS[theme]}. Переключить на ${THEME_LABELS[nextTheme]}`}
            onClick={() => s.config && void s.saveConfig({ theme: nextTheme })}
          >
            {theme === "light" ? (
              <Moon size={17} strokeWidth={1.8} />
            ) : (
              <Sun size={17} strokeWidth={1.8} />
            )}
          </button>
          <button
            className="icon-btn"
            title="Панель показать, скрыть R"
            aria-label="Панель показать, скрыть R"
            aria-pressed={s.rightPanelOpen}
            onClick={s.toggleRightPanel}
          >
            <PanelRight size={17} strokeWidth={1.8} />
          </button>
        </header>

        <div className={"workbench" + (s.rightPanelOpen ? "" : " panel-closed")}>
          <div className="workbench-chat">
            {s.focusedTaskId || s.taskRequestPending ? (
              <TaskExecution
                task={s.tasks.find((task) => task.id === s.focusedTaskId) ?? null}
                store={s}
                onBack={() => s.setFocusedTaskId(null)}
              />
            ) : (
            <MessageList
              messages={s.messages}
              generating={s.generating}
              statusText={s.statusText}
              liveState={s.liveState}
              elapsedMs={s.elapsedMs}
              config={s.config}
              modelName={s.activeModel}
              modelCapabilities={s.activeModelInfo?.capabilities ?? []}
              globalChat={!s.workspace?.current}
              onEdit={s.editLastUser}
              onOpen={s.openExternal}
              onSuggestion={s.send}
              onStop={s.cancel}
              onContinue={s.continueGeneration}
            />
            )}

            {s.lastAction && (
              <div className={"last-action" + (s.lastAction.ok ? " ok" : " error")}>
                <span className="last-action-label">Последнее действие</span>
                <span className="last-action-name">{s.lastAction.name}</span>
                {s.lastAction.detail && <span className="last-action-detail">{s.lastAction.detail}</span>}
                <span className="last-action-state">{s.lastAction.ok ? "готово" : "ошибка"}</span>
              </div>
            )}
            <Composer
              generating={s.generating}
              disabled={!s.connected && !s.activeModel}
              chatId={s.activeChatId}
              draft={s.draft}
              onDraftChange={s.setDraft}
              onSend={s.send}
              onCommand={s.runCommand}
              onCancel={s.cancel}
              webSearchEnabled={s.config?.web_search_enabled ?? true}
              onToggleWebSearch={() =>
                s.config && void s.saveConfig({ web_search_enabled: !s.config.web_search_enabled })
              }
              config={s.config}
              modelName={s.activeModel}
               workspaceFiles={s.workspaceFiles}
               modelSupportsVision={s.activeModelInfo?.capabilities.includes("vision") ?? null}
              context={s.context}
              onOpenContext={() => s.openOverlay("context")}
              composerRef={s.composerRef}
              modelSelector={
                <ModelSelector
                  models={s.models}
                  active={s.activeModelInfo}
                  loading={s.modelsLoading}
                  error={s.modelsError}
                  switching={s.switchingModel}
                  disabled={!s.connected && !s.activeModel}
                  openSignal={s.modelMenuSignal}
                  onSelect={s.selectModel}
                  onRefresh={s.refreshModels}
                />
              }
            />
          </div>
          <WorkbenchSide store={s} />
        </div>
      </div>

      <ConfirmDialog pending={s.pendingPermission} onDecision={s.respondPermission} />

      <Presence open={s.settingsOpen && !!s.config}>
      {s.config && (
                 <SettingsModal
           config={s.config}
           section={s.settingsSection}
           setSection={s.setSettingsSection}
           onClose={() => s.setSettingsOpen(false)}
           onSave={s.saveConfig}
           onRestartCore={s.restartCore}
           providerRows={s.providerRows}
           providerModels={s.providerModels}
           providerLoading={s.providerLoading}
           onProviderSaveSettings={s.providerSaveSettings}
           onProviderPickModel={s.providerPickModel}
           pluginRows={s.pluginRows}
           pluginLoading={s.pluginLoading}
           onLoadPlugins={s.loadPlugins}
           onInstallPlugin={s.installPluginFromFolder}
           onTogglePlugin={s.togglePlugin}
           onRemovePlugin={s.removePlugin}
           bundledPlugins={s.bundledPlugins}
           onInstallBundledPlugin={s.installBundledPlugin}

           memoryRows={s.memoryRows}
           memoryLoading={s.memoryLoading}
           onLoadMemory={s.loadMemory}
           onAddMemory={s.addMemory}
           onEditMemory={s.editMemory}
           onDeleteMemory={s.deleteMemory}

           knowledgeRows={s.knowledgeRows}
           knowledgeLoading={s.knowledgeLoading}
           knowledgeHits={s.knowledgeHits}
           onLoadKnowledge={s.loadKnowledge}
           onAddKnowledge={s.addKnowledgeCollection}
           onReindexKnowledge={s.reindexKnowledge}
           onRemoveKnowledge={s.removeKnowledgeCollection}
           onSearchKnowledge={s.searchKnowledge}

           onLoadProviders={s.loadProviders}
           searchProviders={s.searchProviders}
           onLoadSearchProviders={s.loadSearchProviders}
           onRunSearchTest={s.runSearchTest}
           searchTestResult={s.searchTestResult}
           searchTesting={s.searchTesting}
         />
      )}

      </Presence>

      <Presence open={!!s.overlay}>
      <OverlayPanel
        overlay={s.overlay}
        onClose={() => s.setOverlay(null)}
        model={s.modelDetail}
        context={s.context}
        status={s.status}
        statusError={s.statusError}
        tools={s.tools}
        toolsError={s.toolsError}
        onReload={() => void s.loadStatus()}
        agents={s.agents}
        providers={s.providerRows}
        trajectory={s.trajectory}
      />
      </Presence>

      {toasts}
    </div>
  );
}
