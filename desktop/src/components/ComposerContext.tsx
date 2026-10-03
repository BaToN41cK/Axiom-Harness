import { useEffect, useRef, useState } from "react";
import { Check, ScrollText, Sparkles, X } from "lucide-react";
import type { RuleRow, SkillRow } from "../types";
import { useLocale } from "../lib/locale";
import Presence from "./Presence";

/**
 * Composer context chips (§6): rule files and skills attached to the next
 * request, displayed alongside the @-file chips. Selection is additive —
 * each chip is a toggle, and the chosen ids ride with the send.
 *
 * Facts only: the rows come from the core's rule discovery (W4.5) and skill
 * registry (W3.5); an empty list renders an honest empty hint, never a fake chip.
 */
interface Props {
  rules: RuleRow[];
  skills: SkillRow[];
  selectedRules: string[];
  selectedSkills: string[];
  onToggleRule: (path: string) => void;
  onToggleSkill: (id: string) => void;
  onEnsureLoaded: () => void;
}

export default function ComposerContext(props: Props) {
  const { rules, skills, selectedRules, selectedSkills, onToggleRule, onToggleSkill, onEnsureLoaded } = props;
  const { t } = useLocale();
  const [open, setOpen] = useState<"rules" | "skills" | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(null);
    };
    window.addEventListener("pointerdown", close);
    window.addEventListener("mousedown", close);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("mousedown", close);
    };
  }, [open]);

  // Directory rules attach per task automatically; the picker shows the
  // static layers (global/project) that the user can consciously pin as chips.
  const pickerRules = rules.filter((r) => r.scope === "global" || r.scope === "project");

  const section = (kind: "rules" | "skills") => {
    const isOpen = open === kind;
    const selected = kind === "rules" ? selectedRules : selectedSkills;
    const rows = kind === "rules" ? pickerRules : skills;
    const label = kind === "rules" ? t("ui.composer.ctx.rules") : t("ui.composer.ctx.skills");
    const Icon = kind === "rules" ? <ScrollText size={13} strokeWidth={1.8} /> : <Sparkles size={13} strokeWidth={1.8} />;
    return (
      <div className="ctx-picker" data-kind={kind} key={kind}>
        <button
          type="button"
          className={"chip ctx-toggle" + (selected.length > 0 ? " on" : "")}
          onClick={() => { setOpen(isOpen ? null : kind); onEnsureLoaded(); }}
          title={kind === "rules" ? t("ui.composer.ctx.rules_title") : t("ui.composer.ctx.skills_title")}
        >
          {Icon}
          <span>{label}</span>
          {selected.length > 0 && <b>{selected.length}</b>}
        </button>
        <Presence open={isOpen}>
          <div className="ctx-menu" role="listbox">
            <div className="ctx-menu-head">
              {label}
              {selected.length > 0 && <b>{selected.length}</b>}
            </div>
            {rows.length === 0 && (
              <div className="ctx-menu-empty">
                {kind === "rules" ? t("ui.composer.ctx.rules_empty") : t("ui.composer.ctx.skills_empty")}
              </div>
            )}
            {kind === "rules" && rows.map((row) => {
              const rule = row as RuleRow;
              const active = selectedRules.includes(rule.path);
              return (
                <button
                  key={rule.path}
                  role="option"
                  aria-selected={active}
                  className={"ctx-menu-item" + (active ? " active" : "")}
                  onClick={() => onToggleRule(rule.path)}
                  title={rule.path}
                >
                  {active ? <Check size={12} strokeWidth={2.4} /> : <ScrollText size={12} strokeWidth={1.8} />}
                  <span>{rule.path}</span>
                  <em>{rule.scope}</em>
                </button>
              );
            })}
            {kind === "skills" && rows.map((row) => {
              const skill = row as SkillRow;
              const active = selectedSkills.includes(skill.id);
              return (
                <button
                  key={skill.id}
                  role="option"
                  aria-selected={active}
                  className={"ctx-menu-item" + (active ? " active" : "")}
                  onClick={() => onToggleSkill(skill.id)}
                  title={skill.instructions.slice(0, 200)}
                >
                  {active ? <Check size={12} strokeWidth={2.4} /> : <Sparkles size={12} strokeWidth={1.8} />}
                  <span>{skill.label}</span>
                  <em>{skill.source}</em>
                </button>
              );
            })}
          </div>
        </Presence>
      </div>
    );
  };

  const activeRuleChips = selectedRules
    .map((path) => rules.find((r) => r.path === path))
    .filter((r): r is RuleRow => !!r);
  const activeSkillChips = selectedSkills
    .map((id) => skills.find((s) => s.id === id))
    .filter((s): s is SkillRow => !!s);

  return (
    <div className="composer-ctx" ref={rootRef}>
      {activeRuleChips.map((row) => (
        <button key={row.path} type="button" className="ctx-chip on" onClick={() => onToggleRule(row.path)} title={row.path}>
          <ScrollText size={11} strokeWidth={1.8} />
          <span>{row.path}</span>
          <X size={10} strokeWidth={2.2} />
        </button>
      ))}
      {activeSkillChips.map((row) => (
        <button key={row.id} type="button" className="ctx-chip on" onClick={() => onToggleSkill(row.id)} title={row.instructions.slice(0, 200)}>
          <Sparkles size={11} strokeWidth={1.8} />
          <span>{row.label}</span>
          <X size={10} strokeWidth={2.2} />
        </button>
      ))}
      {section("rules")}
      {section("skills")}
    </div>
  );
}
