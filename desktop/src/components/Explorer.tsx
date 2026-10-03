import { useMemo, useState } from "react";
import { highlightSource, hljs } from "../lib/syntaxHighlight";
import {
  ChevronDown,
  ChevronRight,
  FileCode2,
  FileImage,
  FileJson,
  FileText,
  Folder,
  RefreshCw,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { TreeNode } from "../types";
import CodeBlock from "./CodeBlock";
import { parseGitStatus } from "../lib/gitStatus";
import { useLocale } from "../lib/locale";

interface Props {
  root: string | null;
  tree: TreeNode[];
  loading: boolean;
  /** Raw `git status --short` output of the active project (null = no repo). */
  gitStatus: string | null;
  openFile: { path: string; content: string } | null;
  onRefresh: () => void;
  onOpenFile: (path: string) => void;
  onCloseFile: () => void;
  search: string;
  onSearch: (value: string) => void;
  searchResults: { path: string; preview: string }[];
  searchLoading: boolean;
  onOpenSearchHit: (path: string) => void;
}

const CODE_EXT = new Set([
  "ts", "tsx", "js", "jsx", "py", "rs", "go", "java", "kt", "c", "h", "cpp",
  "cs", "rb", "php", "swift", "sh", "ps1", "css", "scss", "html", "vue", "sql",
]);
const TEXT_EXT = new Set(["md", "txt", "rst", "adoc", "log", "csv"]);
const DATA_EXT = new Set(["json", "jsonc", "yaml", "yml", "toml", "ini", "env", "lock"]);
const IMG_EXT = new Set(["png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "bmp"]);

/** Small, consistent file-type glyphs (lucide) — no emoji. */
function fileIcon(name: string, dir: boolean) {
  if (dir) return <Folder size={14} strokeWidth={1.7} className="ex-icon folder" />;
  const ext = name.includes(".") ? name.split(".").pop()!.toLowerCase() : "";
  if (IMG_EXT.has(ext)) return <FileImage size={14} strokeWidth={1.7} className="ex-icon image" />;
  if (DATA_EXT.has(ext)) return <FileJson size={14} strokeWidth={1.7} className="ex-icon data" />;
  if (CODE_EXT.has(ext)) return <FileCode2 size={14} strokeWidth={1.7} className="ex-icon code" />;
  if (TEXT_EXT.has(ext)) return <FileText size={14} strokeWidth={1.7} className="ex-icon text" />;
  return <FileText size={14} strokeWidth={1.7} className="ex-icon" />;
}

/** Determine if a name looks like a Markdown file for preview. */
function isMarkdown(name: string): boolean {
  return name.toLowerCase().endsWith(".md") || name.toLowerCase().endsWith(".mdx");
}

/** File explorer of the current project (§15). Real tree from the backend. */
export default function Explorer(props: Props) {
  const { root, tree, loading, gitStatus, openFile, onRefresh, onOpenFile, onCloseFile, search, onSearch, searchResults, searchLoading, onOpenSearchHit } = props;
  const { t } = useLocale();
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const toggle = (path: string) => setCollapsed((m) => ({ ...m, [path]: !m[path] }));
  const git = useMemo(() => parseGitStatus(gitStatus), [gitStatus]);
  const renderNodes = (nodes: TreeNode[], depth: number): React.ReactNode => (
    <>
      {nodes.map((n) => {
        const rel = n.path.replace(/\\/g, "/");
        const mark = git.get(rel);
        return (
          <div key={n.path}>
            <button
              className={"ex-node" + (openFile?.path === n.path ? " active" : "")}
              style={{ paddingLeft: 6 + depth * 14 }}
              onClick={() => (n.dir ? toggle(n.path) : onOpenFile(n.path))}
              title={n.path}
            >
              <span className="ex-caret">
                {n.dir ? (
                  collapsed[n.path] ? (
                    <ChevronRight size={13} strokeWidth={2} />
                  ) : (
                    <ChevronDown size={13} strokeWidth={2} />
                  )
                ) : null}
              </span>
              {n.dir ? (
                <Folder size={13} strokeWidth={1.8} className="ex-icon folder" />
              ) : (
                fileIcon(n.name, false)
              )}
              <span className="ex-name">{n.name}</span>
              {mark && (
                <span className={"ex-git ex-git-" + mark.toLowerCase()} title={"git: " + mark}>
                  {mark}
                </span>
              )}
            </button>
            {n.dir && !collapsed[n.path] && n.children && renderNodes(n.children, depth + 1)}
          </div>
        );
      })}
    </>
  );
  return (
    <aside className="explorer">
      <div className="ex-head">
        <span className="ex-title">Explorer</span>
        <button className="icon-btn tiny" title={t("ui.common.refresh")} onClick={onRefresh}>
          <RefreshCw size={12} strokeWidth={1.8} />
        </button>
      </div>
      <div className="ex-root" title={root ?? ""}>
        {root ? (root.split(/[\\/]/).pop() ?? root) : t("ui.explorer.no_project")}
      </div>
      <div className="ex-search" aria-busy={searchLoading}>
        <input
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          placeholder={t("ui.explorer.search_placeholder")}
          disabled={!root}
          aria-label={t("ui.explorer.search_aria")}
        />
        {searchLoading && <span className="ex-search-hint">{t("ui.explorer.searching")}</span>}
      </div>
      {search && !searchLoading && searchResults.length > 0 && (
        <div className="ex-search-results">
          <div className="ex-search-title">{t("ui.explorer.found", { n: String(searchResults.length) })}</div>
          {searchResults.slice(0, 20).map((hit) => (
            <button key={hit.path} className="ex-search-hit" onClick={() => onOpenSearchHit(hit.path)}>
              <span>{hit.path}</span>
              {hit.preview && <small>{hit.preview}</small>}
            </button>
          ))}
        </div>
      )}
      {search && !searchLoading && searchResults.length === 0 && <div className="ex-empty">{t("ui.summary.no_matches")}</div>}
      <div className="ex-tree">
        {!root ? (
          <div className="ex-empty"><b>{t("ui.explorer.not_open")}</b><span>{t("ui.explorer.choose_folder")}</span></div>
        ) : loading ? (
          <div className="ex-empty">{t("ui.explorer.reading")}</div>
        ) : tree.length === 0 ? (
          <div className="ex-empty">{t("ui.explorer.empty_folder")}</div>
        ) : (
          renderNodes(tree, 0)
        )}
      </div>
      {openFile && (
        <FilePreview
          path={openFile.path}
          content={openFile.content}
          onClose={onCloseFile}
        />
      )}
    </aside>
  );
}

/** File preview with syntax highlighting and optional Markdown. */
function FilePreview({
  path,
  content,
  onClose,
}: {
  path: string;
  content: string;
  onClose: () => void;
}) {
  const { html, language: lang } = useMemo(() => highlightSource(content, path), [content, path]);
  const { t } = useLocale();
  const isMD = isMarkdown(path);

  return (
    <div className="ex-file">
      <div className="ex-file-head">
        <span className="ex-file-name">{path}</span>
        <button className="icon-btn tiny" onClick={onClose} title={t("ui.common.close")}>
          <X size={12} strokeWidth={1.8} />
        </button>
      </div>
      <div className="ex-file-body">
        {isMD ? (
          <div className="ex-markdown">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                code: ({ className, children, ...rest }) => {
                  const match = /language-(\w+)/.exec(className ?? "");
                  const lang2 = match ? match[1] : "";
                  const code = String(children ?? "").replace(/\n$/, "");
                  if (lang2) {
                    try {
                      const h = hljs.highlight(code, { language: lang2, ignoreIllegals: true });
                      return (
                        <div className="code-block">
                          <div className="code-head">
                            <span className="code-lang">{lang2}</span>
                          </div>
                          <pre>
                            <code dangerouslySetInnerHTML={{ __html: h.value }} />
                          </pre>
                        </div>
                      );
                    } catch { /* fall through to plain block */ }
                  }
                  if (!lang2 && code.includes("\n")) {
                    return (
                      <CodeBlock code={code} />
                    );
                  }
                  return <code className="md-inline" {...rest}>{children}</code>;
                },
              }}
            >
              {content}
            </ReactMarkdown>
          </div>
        ) : html ? (
          <pre className="hljs-pre">
            <code className={`hljs language-${lang}`} dangerouslySetInnerHTML={{ __html: html }} />
          </pre>
        ) : (
          <pre>{content}</pre>
        )}
      </div>
    </div>
  );
}
