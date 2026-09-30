import hljsCore from "highlight.js/lib/core";
import python from "highlight.js/lib/languages/python";
import typescript from "highlight.js/lib/languages/typescript";
import javascript from "highlight.js/lib/languages/javascript";
import rust from "highlight.js/lib/languages/rust";
import go from "highlight.js/lib/languages/go";
import java from "highlight.js/lib/languages/java";
import c from "highlight.js/lib/languages/c";
import cpp from "highlight.js/lib/languages/cpp";
import csharp from "highlight.js/lib/languages/csharp";
import ruby from "highlight.js/lib/languages/ruby";
import php from "highlight.js/lib/languages/php";
import swift from "highlight.js/lib/languages/swift";
import bash from "highlight.js/lib/languages/bash";
import powershell from "highlight.js/lib/languages/powershell";
import cssLang from "highlight.js/lib/languages/css";
import scss from "highlight.js/lib/languages/scss";
import xml from "highlight.js/lib/languages/xml";
import sql from "highlight.js/lib/languages/sql";
import json from "highlight.js/lib/languages/json";
import yaml from "highlight.js/lib/languages/yaml";
import ini from "highlight.js/lib/languages/ini";
import markdown from "highlight.js/lib/languages/markdown";
import dockerfile from "highlight.js/lib/languages/dockerfile";

// One deliberately small language registry shared by Explorer, Markdown and
// task review. Keeping it here prevents the diff viewer from creating a second
// highlight.js instance or silently supporting fewer languages than Explorer.
const LANGS = {
  python, typescript, javascript, rust, go, java, c, cpp, csharp,
  ruby, php, swift, bash, powershell, css: cssLang, scss, xml, sql,
  json, yaml, ini, markdown, dockerfile,
};
for (const [name, definition] of Object.entries(LANGS)) {
  hljsCore.registerLanguage(name, definition);
}

export const hljs = hljsCore;

const EXTENSIONS: Record<string, string> = {
  py: "python", ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
  rs: "rust", go: "go", java: "java", c: "c", h: "c", cpp: "cpp", cs: "csharp",
  rb: "ruby", php: "php", swift: "swift", sh: "bash", ps1: "powershell",
  css: "css", scss: "scss", html: "xml", htm: "xml", vue: "xml", sql: "sql",
  json: "json", jsonc: "json", yaml: "yaml", yml: "yaml", toml: "ini", ini: "ini",
  md: "markdown", mdx: "markdown", xml: "xml",
};

/** Resolve a highlight.js language from a workspace path or extension. */
export function languageForPath(pathOrExtension: string): string {
  const normalized = pathOrExtension.toLowerCase().replace(/\\/g, "/");
  const basename = normalized.split("/").pop() ?? normalized;
  if (basename === "dockerfile" || basename.startsWith("dockerfile.")) return "dockerfile";
  const extension = basename.includes(".") ? basename.split(".").pop() ?? "" : basename;
  return Object.prototype.hasOwnProperty.call(EXTENSIONS, extension) ? EXTENSIONS[extension] : "";
}

/** Highlight source as trusted highlight.js HTML; unknown/invalid code stays plain. */
export function highlightSource(source: string, pathOrExtension: string): { html: string; language: string } {
  const language = languageForPath(pathOrExtension);
  if (!language) return { html: "", language: "" };
  try {
    return { html: hljs.highlight(source, { language, ignoreIllegals: true }).value, language };
  } catch {
    return { html: "", language: "" };
  }
}

/** Split only highlight.js output, closing/reopening spans at row boundaries.
 * Source HTML is already escaped by highlight.js, never interpreted as markup.
 * This preserves multiline token state without invalid cross-row DOM nesting.
 */
export function highlightSourceLines(source: string, path: string): string[] | null {
  const { html, language } = highlightSource(source, path);
  if (!language) return null;
  const spans: string[] = [];
  return html.split("\n").map((line) => {
    const prefix = spans.join("");
    for (const match of line.matchAll(/<span\b[^>]*>|<\/span>/g)) {
      if (match[0] === "</span>") spans.pop();
      else spans.push(match[0]);
    }
    return prefix + line + "</span>".repeat(spans.length);
  });
}
