import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import { Download, FileText, Plus, Save, Trash2 } from "lucide-react";
import { request } from "../bridge";
import type { ArtifactDocument, ArtifactMeta } from "../types";

/**
 * W3.17 — Documents view: a list of editable artifact documents plus a Markdown
 * editor (write + sanitized preview). Everything round-trips through the real
 * `artifact_*` bridge commands over the core `ArtifactWorkspace`.
 */
export default function DocumentsPanel({ root }: { root: string | null }) {
  const [documents, setDocuments] = useState<ArtifactMeta[]>([]);
  const [active, setActive] = useState<ArtifactDocument | null>(null);
  const [draft, setDraft] = useState("");
  const [preview, setPreview] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirtyRef = useRef(false);

  const load = useCallback(async () => {
    if (!root) return;
    setLoading(true);
    setError(null);
    try {
      const rows = await request<ArtifactMeta[]>("artifact_list", {});
      setDocuments(rows);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, [root]);

  useEffect(() => {
    setActive(null);
    setDraft("");
    void load();
  }, [load]);

  const open = async (id: string) => {
    setError(null);
    try {
      const doc = await request<ArtifactDocument>("artifact_get", { id });
      setActive(doc);
      setDraft(doc.content);
      dirtyRef.current = false;
    } catch (err) {
      setError(String(err));
    }
  };

  const save = async () => {
    if (!dirtyRef.current && active) return;
    setSaving(true);
    setError(null);
    try {
      if (active) {
        const doc = await request<ArtifactDocument>("artifact_save", { id: active.id, content: draft });
        setActive(doc);
        dirtyRef.current = false;
      } else {
        const title = draft.split("\n")[0].replace(/^#+\s*/, "").trim().slice(0, 48) || "untitled.md";
        const doc = await request<ArtifactDocument>("artifact_save", { title, content: draft });
        setActive(doc);
        dirtyRef.current = false;
      }
      void load();
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!active) return;
    try {
      await request<{ deleted: boolean }>("artifact_delete", { id: active.id });
      setActive(null);
      setDraft("");
      void load();
    } catch (err) {
      setError(String(err));
    }
  };

  const download = () => {
    if (!active) return;
    const blob = new Blob([active.content], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = active.title.endsWith(".md") ? active.title : `${active.title}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  if (!root) {
    return <div className="documents-empty"><FileText size={22} /><span>Откройте проект, чтобы работать с документами</span></div>;
  }

  return (
    <div className="documents">
      <div className="documents-head">
        <span className="documents-title">Документы</span>
        <div className="documents-actions">
          <button className="btn ghost" onClick={() => { setActive(null); setDraft(""); dirtyRef.current = false; }} title="Новый документ">
            <Plus size={13} />Новый
          </button>
          <button className="btn ghost" onClick={() => void load()} title="Обновить">Обновить</button>
        </div>
      </div>

      {error && <div className="documents-error">{error}</div>}

      {documents.length === 0 && !active && !loading ? (
        <div className="documents-empty"><FileText size={22} /><span>Пока нет документов — создайте первый</span></div>
      ) : (
        <div className="documents-list">
          {documents.map((doc) => (
            <button
              key={doc.id}
              className={"documents-row" + (active?.id === doc.id ? " active" : "")}
              onClick={() => void open(doc.id)}
            >
              <FileText size={13} />
              <span className="documents-row-title">{doc.title}</span>
              <span className="documents-row-meta">v{doc.version}</span>
            </button>
          ))}
        </div>
      )}

      <div className="documents-editor">
        <div className="documents-editor-bar">
          <span className="documents-editor-title">{active ? active.title : "Новый документ"}</span>
          <div className="documents-editor-actions">
            <button className={"btn ghost" + (preview ? " active" : "")} onClick={() => setPreview((p) => !p)}>
              Предпросмотр
            </button>
            <button className="btn ghost" disabled={!active} onClick={download} title="Скачать .md">
              <Download size={13} />Экспорт
            </button>
            <button className="btn ghost danger" disabled={!active} onClick={() => void remove()} title="Удалить">
              <Trash2 size={13} />
            </button>
            <button className="btn primary" disabled={saving || !dirtyRef.current} onClick={() => void save()} title="Сохранить">
              <Save size={13} />{saving ? "Сохранение…" : "Сохранить"}
            </button>
          </div>
        </div>
        {preview ? (
          <div className="documents-preview markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{draft || "*Пусто*"}</ReactMarkdown>
          </div>
        ) : (
          <textarea
            className="documents-textarea"
            value={draft}
            spellCheck={false}
            placeholder={"# Заголовок\n\nПишите Markdown…"}
            onChange={(e) => { setDraft(e.target.value); dirtyRef.current = true; }}
          />
        )}
      </div>
    </div>
  );
}

