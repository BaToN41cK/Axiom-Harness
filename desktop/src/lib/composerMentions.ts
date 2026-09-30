export interface FileMention {
  file: string;
  start: number;
  end: number;
}

/** Return only @paths that exist in the real workspace index. */
export function extractFileMentions(prompt: string, workspaceFiles: string[]): FileMention[] {
  const known = new Set(workspaceFiles);
  const found: FileMention[] = [];
  const pattern = /(^|\s)@([^\s@]+)/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(prompt)) !== null) {
    const file = match[2];
    if (known.has(file)) {
      const start = match.index + match[1].length;
      found.push({ file, start, end: start + file.length + 1 });
    }
  }
  return found;
}

export function removeFileMention(prompt: string, mention: FileMention): string {
  return `${prompt.slice(0, mention.start)}${prompt.slice(mention.end).replace(/^\s+/, "")}`;
}
