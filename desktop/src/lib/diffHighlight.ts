import { highlightSourceLines, languageForPath } from "./syntaxHighlight";
import type { DiffHunk } from "./unifiedDiff";

// Limit work for pathological long rows as well as the parser's row cap.
export const DIFF_HIGHLIGHT_MAX_CHARS = 100_000;

/** Highlight only the selected file's retained rows. Each side of each hunk is
 * a separate source document: deleted tokens must never affect new code.
 * Omitted context between hunks cannot be inferred; reset lexical state there.
 * Null means render the original string through React's safe text fallback.
 */
export function highlightDiffHunks(hunks: DiffHunk[], path: string): (string | null)[][] {
  let remaining = DIFF_HIGHLIGHT_MAX_CHARS;
  const supported = Boolean(languageForPath(path));
  return hunks.map((hunk) => {
    const result: (string | null)[] = hunk.lines.map(() => null);
    if (!supported) return result;
    const oldRows: number[] = [];
    const newRows: number[] = [];
    let cost = 0;
    hunk.lines.forEach((line, index) => {
      if (line.kind === "meta") return;
      if (line.kind !== "add") { oldRows.push(index); cost += line.text.length + 1; }
      if (line.kind !== "del") { newRows.push(index); cost += line.text.length + 1; }
    });
    if (cost > remaining) return result;
    remaining -= cost;
    for (const rows of [oldRows, newRows]) {
      if (!rows.length) continue;
      const html = highlightSourceLines(rows.map((row) => hunk.lines[row].text).join("\n"), path);
      if (!html || html.length !== rows.length) continue;
      // Context uses new-side tokens; removed lines use old-side tokens.
      rows.forEach((row, index) => { result[row] = html[index]; });
    }
    return result;
  });
}
