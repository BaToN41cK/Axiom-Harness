export interface DiffLine {
  kind: "context" | "add" | "del" | "meta";
  text: string;
  oldNumber: number | null;
  newNumber: number | null;
}
export interface DiffHunk {
  header: string;
  lines: DiffLine[];
  omitted: number;
}

/** Parse one file's unified patch. Header-like code inside hunks is still code.
 * Bound stored rows, but count every available changed line (not unseen data).
 */
export function parseUnifiedDiff(diff: string, limit = 1500) {
  const hunks: DiffHunk[] = [];
  const metadata: string[] = [];
  let current: DiffHunk | undefined;
  let oldNumber = 0;
  let newNumber = 0;
  let oldLeft = 0;
  let newLeft = 0;
  let add = 0;
  let del = 0;
  let stored = 0;
  let incomplete = false;
  const source = diff.split(/\r?\n/);
  if (source[source.length - 1] === "") source.pop();
  for (const text of source) {
    const match = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/.exec(text);
    if (match) {
      if (oldLeft || newLeft) incomplete = true;
      oldNumber = Number(match[1]);
      newNumber = Number(match[3]);
      oldLeft = match[2] === undefined ? 1 : Number(match[2]);
      newLeft = match[4] === undefined ? 1 : Number(match[4]);
      current = { header: text, lines: [], omitted: 0 };
      hunks.push(current);
      continue;
    }
    let line: DiffLine | undefined;
    if (current && text.startsWith("\\ No newline")) {
      line = { kind: "meta", text, oldNumber: null, newNumber: null };
    } else if (current && text.startsWith("+") && newLeft > 0) {
      add++;
      newLeft--;
      line = { kind: "add", text: text.slice(1), oldNumber: null, newNumber: newNumber++ };
    } else if (current && text.startsWith("-") && oldLeft > 0) {
      del++;
      oldLeft--;
      line = { kind: "del", text: text.slice(1), oldNumber: oldNumber++, newNumber: null };
    } else if (current && text.startsWith(" ") && oldLeft > 0 && newLeft > 0) {
      oldLeft--;
      newLeft--;
      line = { kind: "context", text: text.slice(1), oldNumber: oldNumber++, newNumber: newNumber++ };
    } else {
      if (current && (oldLeft || newLeft)) incomplete = true;
      if (text.includes("diff truncated")) incomplete = true;
      if (metadata.length < 40) metadata.push(text);
    }
    if (line && current) {
      if (stored < limit) { current.lines.push(line); stored++; }
      else current.omitted++;
    }
  }
  return { hunks, metadata, add, del, incomplete: incomplete || oldLeft > 0 || newLeft > 0 };
}
