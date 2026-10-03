import { useState } from "react";
import type { ReactNode } from "react";
import {
  Ban,
  Check,
  ChevronDown,
  ClipboardCheck,
  Cpu,
  FileText,
  FolderOpen,
  Globe,
  GitBranch,
  Link as LinkIcon,
  ListChecks,
  Loader2,
  Pencil,
  Search,
  ShieldCheck,
  Terminal,
  TriangleAlert,
  Workflow,
  Wrench,
  X,
} from "lucide-react";
import type {
  OrchestrationAgent,
  OrchestrationState,
  OrchestrationStep,
  OrchestrationStepKind,
} from "../types";
import { toolLabel } from "../hooks/useAxiom";
import { useLocale } from "../lib/locale";
import { plural } from "../lib/i18n";
import { formatRunTime } from "../lib/orchestration";

/** Real phase order of a run (`orchestrator.run`). */
const PHASES: { id: string; label: string }[] = [
  { id: "planning", label: "ui.orch.phase.planning" },
  { id: "working", label: "ui.orch.phase.working" },
  { id: "review", label: "ui.orch.phase.review" },
  { id: "verification", label: "ui.orch.phase.verification" },
  { id: "done", label: "ui.orch.phase.done" },
];

function phaseIndex(phase: string): number {
  const index = PHASES.findIndex((item) => item.id === phase);
  if (index >= 0) return index;
  // failed / cancelled end the run: every phase up to "Итог" is behind us.
  return PHASES.length - 1;
}

/** Icon of one real tool category — no emoji, no generic gear. */
function StepIcon({ kind }: { kind: OrchestrationStepKind }) {
  const props = { size: 13, strokeWidth: 1.8 };
  switch (kind) {
    case "read":
      return <FileText {...props} />;
    case "write":
      return <Pencil {...props} />;
    case "search":
      return <Search {...props} />;
    case "web":
      return <Globe {...props} />;
    case "fetch":
      return <LinkIcon {...props} />;
    case "terminal":
      return <Terminal {...props} />;
    case "git":
      return <GitBranch {...props} />;
    case "folder":
      return <FolderOpen {...props} />;
    case "verification":
      return <ShieldCheck {...props} />;
    default:
      return <Wrench {...props} />;
  }
}

/** Status dot of one worker — colour + glyph, never colour alone. */
function AgentStatusIcon({ status }: { status: OrchestrationAgent["status"] }) {
  if (status === "running") return <Loader2 size={12} className="spin" />;
  if (status === "done") return <Check size={12} strokeWidth={2.4} />;
  if (status === "failed") return <X size={12} strokeWidth={2.4} />;
  if (status === "cancelled") return <Ban size={12} strokeWidth={2.1} />;
  return <Loader2 size={12} />;
}

const AGENT_STATUS_LABEL: Record<OrchestrationAgent["status"], string> = {
  pending: "ui.orch.status.pending",
  running: "ui.orch.status.running",
  done: "ui.orch.status.done",
  failed: "ui.orch.status.failed",
  cancelled: "ui.orch.status.cancelled",
};

/** One worker card: model, live action, tool counters and its own last thought. */
function AgentCard({ agent, live }: { agent: OrchestrationAgent; live: boolean }) {
  const { t, locale, strings } = useLocale();
  const [open, setOpen] = useState(false);
  const identity = agent.model
    ? `${agent.provider ?? "?"} / ${agent.model}`
    : agent.provider ?? t("ui.orch.no_model");
  const trace = [agent.thought, agent.answer].filter(Boolean).join("\n\n");

  return (
    <div className={"orch-agent " + agent.status}>
      <div className="orch-agent-head">
        <span className="orch-agent-status">
          <AgentStatusIcon status={agent.status} />
        </span>
        <span className="orch-agent-name">{agent.label}</span>
        <span className="orch-agent-state">{t(AGENT_STATUS_LABEL[agent.status])}</span>
      </div>
      <div className="orch-agent-model" title={identity}>
        <Cpu size={11} strokeWidth={1.8} />
        <span>{identity}</span>
      </div>
      {agent.lastTool && (
        <div className="orch-agent-action" title={agent.lastTarget ?? ""}>
          <span>{toolLabel(agent.lastTool, locale, strings)}</span>
          {agent.lastTarget && <code>{agent.lastTarget}</code>}
        </div>
      )}
      {!agent.lastTool && agent.task && (
        <div className="orch-agent-task" title={agent.task}>
          {agent.task}
        </div>
      )}
      <div className="orch-agent-foot">
        {agent.toolsOk > 0 && (
          <span className="orch-count ok">
            <Check size={11} strokeWidth={2.4} />
            {agent.toolsOk}
          </span>
        )}
        {agent.toolsFailed > 0 && (
          <span className="orch-count bad">
            <X size={11} strokeWidth={2.4} />
            {agent.toolsFailed}
          </span>
        )}
        {trace && (
          <button className="orch-trace-toggle" onClick={() => setOpen((v) => !v)}>
            <ChevronDown size={11} strokeWidth={1.9} className={"chevron" + (open ? " open" : "")} />
            <span>{live && agent.status === "running" ? t("ui.orch.trace_thought") : t("ui.orch.trace_details")}</span>
          </button>
        )}
      </div>
      {agent.error && <div className="orch-agent-error">{agent.error}</div>}
      {open && trace && (
        <div className="orch-agent-trace">
          {agent.thought && <p className="orch-thought">{agent.thought}</p>}
          {agent.answer && <p className="orch-answer">{agent.answer}</p>}
        </div>
      )}
    </div>
  );
}


/** One tool row of the timeline: agent, action, target, state, duration. */
function ActivityRow({ step }: { step: OrchestrationStep }) {
  const { locale, strings } = useLocale();
  return (
    <li className={"orch-step " + step.state}>
      <span className="orch-step-icon">
        <StepIcon kind={step.kind} />
      </span>
      <span className="orch-step-actor">{step.actor}</span>
      <span className="orch-step-tool">{toolLabel(step.tool, locale, strings)}</span>
      {step.target && (
        <code className="orch-step-target" title={step.target}>
          {step.target}
        </code>
      )}
      <span className="orch-step-state">
        {step.state === "running" && <Loader2 size={11} className="spin" />}
        {step.state === "ok" && <Check size={11} strokeWidth={2.4} />}
        {step.state === "failed" && <X size={11} strokeWidth={2.4} />}
        {step.state === "cancelled" && <Ban size={11} strokeWidth={2.1} />}
        {step.durationMs != null && step.state !== "running" && (
          <span className="orch-step-ms">{step.durationMs} ms</span>
        )}
      </span>
      {step.detail && <div className="orch-step-detail">{step.detail}</div>}
    </li>
  );
}

/** Collapsible timeline of every real tool call of the run. */
function ActivityLog({ steps, live }: { steps: OrchestrationStep[]; live: boolean }) {
  const [open, setOpen] = useState(live);
  const { t, locale, strings } = useLocale();
  if (steps.length === 0) return null;
  const failed = steps.filter((step) => step.state === "failed").length;
  return (
    <div className="orch-activity">
      <button className="orch-activity-head" onClick={() => setOpen((v) => !v)}>
        <Workflow size={13} strokeWidth={1.8} />
        <span>{t("ui.orch.activity")}</span>
        <span className="orch-activity-meta">
          {plural("ui.orch.step", steps.length, locale, strings)}
          {failed > 0 && <span className="orch-badge bad">{t("ui.orch.errors", { n: String(failed) })}</span>}
        </span>
        <ChevronDown size={13} strokeWidth={1.8} className={"chevron" + (open ? " open" : "")} />
      </button>
      {open && (
        <ul className="orch-steps">
          {steps.map((step) => (
            <ActivityRow key={step.id} step={step} />
          ))}
        </ul>
      )}
    </div>
  );
}

function Section({
  icon,
  title,
  badge,
  tone,
  children,
}: {
  icon: ReactNode;
  title: string;
  badge?: ReactNode;
  tone?: "ok" | "bad" | "warn";
  children: ReactNode;
}) {
  return (
    <section className={"orch-section" + (tone ? " " + tone : "")}>
      <header className="orch-section-head">
        <span className="orch-section-icon">{icon}</span>
        <h4>{title}</h4>
        {badge}
      </header>
      <div className="orch-section-body">{children}</div>
    </section>
  );
}

const PHASE_TONE: Record<string, string> = {
  done: "ok",
  verification: "ok",
  failed: "bad",
  cancelled: "warn",
};

/**
 * The `/orchestrate` board: header + phase rail, worker cards, tool timeline and
 * the closing Reports / Review / Verification / Definition of Done sections.
 *
 * Everything rendered here comes from `OrchestrationState`, which is reduced
 * from the real trajectory events and the final `orchestrate` reply.
 */
export default function OrchestrationBoard({
  state,
  live,
  elapsedMs,
}: {
  state: OrchestrationState;
  live: boolean;
  elapsedMs: number;
}) {
  const duration = state.finishedAt
    ? state.durationMs ?? state.finishedAt - state.startedAt
    : elapsedMs;
  const { t } = useLocale();
  const tone = PHASE_TONE[state.phase] ?? "";
  const current = phaseIndex(state.phase);
  const running = state.agents.filter((agent) => agent.status === "running").length;
  const reports = state.reports.length > 0 ? state.reports : null;
  const failedReports = state.reports.filter((report) => report.error);

  const verificationTone = state.verification
    ? state.verification.ok === true
      ? "ok"
      : "bad"
    : undefined;
  const verificationLabel = state.verification
    ? state.verification.ok === true
      ? "PASSED"
      : state.verification.ok === false
        ? "FAILED"
        : t("ui.orch.no_verdict")
    : t("ui.orch.not_run");

  return (
    <div className={"orch-board" + (live ? " live" : "") + (tone ? " " + tone : "")}>
      <header className="orch-board-head">
        <span className="orch-board-mark">
          <Workflow size={15} strokeWidth={1.7} />
        </span>
        <div className="orch-board-title">
          <strong>{t("ui.orch.title")}</strong>
          <span className="orch-board-task" title={state.task}>
            {state.task || t("ui.orch.no_task")}
          </span>
        </div>
        <div className="orch-board-meta">
          {running > 0 && (
            <span className="orch-live-pill">
              <span className="live-dot" />
              {t("ui.orch.active", { n: String(running) })}
            </span>
          )}
          <span className="orch-time">{formatRunTime(duration)}</span>
        </div>
      </header>

      <ol className="orch-phases">
        {PHASES.map((phase, index) => (
          <li
            key={phase.id}
            className={
              "orch-phase" +
              (index < current ? " past" : "") +
              (index === current ? " current" : "") +
              (index === current && state.phase === "failed" ? " bad" : "")
            }
          >
            <span className="orch-phase-dot" />
            <span className="orch-phase-label">{t(phase.label)}</span>
          </li>
        ))}
      </ol>

      {state.error && (
        <div className="orch-error">
          <TriangleAlert size={14} strokeWidth={1.9} />
          <span>{state.error}</span>
        </div>
      )}

      {state.agents.length > 0 && (
        <div className="orch-agents">
          {state.agents.map((agent) => (
            <AgentCard key={agent.id} agent={agent} live={live} />
          ))}
        </div>
      )}

      <ActivityLog steps={state.steps} live={live} />

      {state.review && (
        <Section
          icon={<ClipboardCheck size={13} strokeWidth={1.8} />}
          title="Reviewer"
          tone={state.review.verdict === "rework" ? "bad" : "ok"}
          badge={
            <span className={"orch-badge " + (state.review.verdict === "rework" ? "bad" : "ok")}>
              {state.review.verdict === "rework" ? "REWORK" : "APPROVED"}
            </span>
          }
        >
          <p className="orch-review-text">{state.review.text || t("ui.orch.no_review")}</p>
          {state.review.issues.length > 0 && (
            <ul className="orch-list bad">
              {state.review.issues.map((issue, index) => (
                <li key={index}>{issue}</li>
              ))}
            </ul>
          )}
          {state.review.requiredChanges.length > 0 && (
            <ul className="orch-list">
              {state.review.requiredChanges.map((change, index) => (
                <li key={index}>{change}</li>
              ))}
            </ul>
          )}
        </Section>
      )}

      {reports && (
        <Section
          icon={<ListChecks size={13} strokeWidth={1.8} />}
          title={t("ui.orch.reports_title")}
          tone={failedReports.length > 0 ? "warn" : "ok"}
          badge={<span className="orch-badge">{reports.length}</span>}
        >
          <div className="orch-reports">
            {reports.map((report, index) => (
              <article
                key={`${report.agent ?? "agent"}-${index}`}
                className={"orch-report" + (report.error ? " failed" : "")}
              >
                <header>
                  <strong>{report.agent ?? t("ui.orch.agent")}</strong>
                  <span className="orch-report-model">
                    {report.provider_id ?? "?"}
                    {report.model ? ` / ${report.model}` : ""}
                  </span>
                </header>
                <p>{report.content ?? report.error ?? t("ui.orch.no_report")}</p>
                {report.tools_used != null && (
                  <footer className="orch-report-foot">
                    <span>{t("ui.orch.tools_used", { n: String(report.tools_used) })}</span>
                    {report.tools_ok != null && <span className="ok">{t("ui.orch.tools_ok", { n: String(report.tools_ok) })}</span>}
                    {report.tools_failed ? (
                      <span className="bad">{t("ui.orch.tools_failed", { n: String(report.tools_failed) })}</span>
                    ) : null}
                  </footer>
                )}
              </article>
            ))}
          </div>
        </Section>
      )}

      {state.verification && (
        <Section
          icon={<ShieldCheck size={13} strokeWidth={1.8} />}
          title="Verification"
          tone={verificationTone}
          badge={
            <span className={"orch-badge " + (verificationTone ?? "")}>{verificationLabel}</span>
          }
        >
          <p>{state.verification.summary ?? state.verification.error ?? t("ui.orch.no_summary")}</p>
        </Section>
      )}

      {state.definitionOfDone.length > 0 && (
        <Section icon={<ListChecks size={13} strokeWidth={1.8} />} title="Definition of Done">
          <ul className="orch-list">
            {state.definitionOfDone.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </Section>
      )}

      {!live && state.completed != null && (
        <div className={"orch-verdict " + (state.completed ? "ok" : "bad")}>
          {state.completed ? (
            <>
              <Check size={13} strokeWidth={2.3} />
              <span>{t("ui.orch.verdict.ok")}</span>
            </>
          ) : (
            <>
              <TriangleAlert size={13} strokeWidth={1.9} />
              <span>{t("ui.orch.verdict.bad")}</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}

