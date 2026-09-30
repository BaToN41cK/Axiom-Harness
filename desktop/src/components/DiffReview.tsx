import { useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Copy, ExternalLink } from "lucide-react";
import { parseUnifiedDiff } from "../lib/unifiedDiff";
import { highlightDiffHunks } from "../lib/diffHighlight";
import "./DiffReview.css";

export default function DiffReview({ diffs, onOpenFile }: { diffs: Record<string, string>; onOpenFile: (path: string) => void }) {
  const files = useMemo(() => Object.entries(diffs).map(([path, diff]) => ({
    path, diff, parsed: parseUnifiedDiff(diff),
  })), [diffs]);
  const [selected, setSelected] = useState("");
  const index = Math.max(0, files.findIndex((file) => file.path === selected));
  const file = files[index];
  if (!file) return <p className="task-diff-note">Нет изменений для просмотра.</p>;
  return <section className="diff-review" aria-label="Просмотр изменений агента">
    <nav className="diff-files" aria-label="Изменённые файлы">
      {files.map((item) => <button type="button" key={item.path} aria-current={item.path === file.path ? "true" : undefined}
        title={item.path} onClick={() => setSelected(item.path)}>
        <code>{item.path}</code><span className="task-diff-counts"><b className="add">+{item.parsed.add}</b><b className="del">−{item.parsed.del}</b></span>
      </button>)}
    </nav>
    <div className="diff-toolbar">
      <span>Файл {index + 1} / {files.length} · снимок изменений агента</span>
      <button type="button" aria-label="Предыдущий файл" disabled={index === 0} onClick={() => setSelected(files[index - 1].path)}><ChevronLeft size={14} /></button>
      <button type="button" aria-label="Следующий файл" disabled={index === files.length - 1} onClick={() => setSelected(files[index + 1].path)}><ChevronRight size={14} /></button>
    </div>
    <DiffFile key={file.path + file.diff} file={file} onOpenFile={() => onOpenFile(file.path)} />
  </section>;
}

function DiffFile({ file, onOpenFile }: { file: { path: string; diff: string; parsed: ReturnType<typeof parseUnifiedDiff> }; onOpenFile: () => void }) {
  const [copyState, setCopyState] = useState("");
  const [copying, setCopying] = useState(false);
  const [hunkIndex, setHunkIndex] = useState(0);
  const hunks = useRef<(HTMLDetailsElement | null)[]>([]);
  const { parsed } = file;
  const highlighted = useMemo(() => highlightDiffHunks(parsed.hunks, file.path), [parsed.hunks, file.path]);
  function navigate(index: number) {
    setHunkIndex(index);
    const target = hunks.current[index];
    if (!target) return;
    target.open = true;
    target.scrollIntoView({ block: "nearest", behavior: "auto" });
    target.querySelector("summary")?.focus({ preventScroll: true });
  }
  async function copy() {
    setCopying(true);
    try { await navigator.clipboard.writeText(file.diff); setCopyState("Diff скопирован"); }
    catch { setCopyState("Не удалось скопировать diff. Проверьте доступ к буферу обмена."); }
    finally { setCopying(false); }
  }
  return <div className="diff-file">
    <div className="diff-toolbar">
      <code title={file.path}>{file.path}</code>
      <button type="button" aria-label={`Открыть ${file.path}`} onClick={onOpenFile}><ExternalLink size={13} /> Открыть файл</button>
      <button type="button" aria-label="Скопировать diff" disabled={copying} onClick={() => void copy()}><Copy size={13} /> Копировать diff</button>
    </div>
    <span className="diff-feedback" role="status">{copyState}</span>
    {parsed.incomplete && <p className="task-diff-note">Неполный diff: счётчики относятся только к полученным строкам.</p>}
    {parsed.hunks.length > 0 ? <>
      <div className="diff-toolbar">
        <span>Фрагмент {hunkIndex + 1} / {parsed.hunks.length} · номера до / после</span>
        <button type="button" aria-label="Предыдущий фрагмент" disabled={hunkIndex === 0} onClick={() => navigate(hunkIndex - 1)}><ChevronLeft size={14} /></button>
        <button type="button" aria-label="Следующий фрагмент" disabled={hunkIndex === parsed.hunks.length - 1} onClick={() => navigate(hunkIndex + 1)}><ChevronRight size={14} /></button>
      </div>
      <div className="diff-scroll" tabIndex={0} role="region" aria-label={`Diff ${file.path}`}>
        {parsed.hunks.map((hunk, index) => <details className="diff-hunk" key={index} open ref={(node) => { hunks.current[index] = node; }}>
          <summary onFocus={() => setHunkIndex(index)}>{hunk.header}</summary>
          <div className="diff-lines">
            {hunk.lines.map((line, row) => <div className={`diff-line ${line.kind}`} key={row}>
              <span className="diff-number" aria-label="Строка до">{line.oldNumber}</span>
              <span className="diff-number" aria-label="Строка после">{line.newNumber}</span>
              <span className="diff-sign">{line.kind === "add" ? "+" : line.kind === "del" ? "−" : " "}</span>
              {highlighted[index][row] !== null
                ? <code className="diff-code" dangerouslySetInnerHTML={{ __html: highlighted[index][row] || " " }} />
                : <code>{line.text || " "}</code>}
            </div>)}
          </div>
          {hunk.omitted > 0 && <p className="task-diff-note">Скрыто строк: {hunk.omitted}. Полный полученный diff доступен через копирование.</p>}
        </details>)}
      </div>
    </> : <p className="diff-fallback">{parsed.metadata.join("\n") || "Построчный diff недоступен."}</p>}
  </div>;
}
