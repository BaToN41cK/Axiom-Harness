/**
 * Parse `git status --short` into `relative path -> letter` (W3.12).
 *
 * Both columns are inspected: `XY path`, where X is the index state and Y the
 * worktree state. The most visible letter for the GUI wins (M/A/D/?). A quoted
 * or backslash path is normalised to a forward-slash workspace-relative path.
 */
export function parseGitStatus(raw: string | null | undefined): Map<string, string> {
  const map = new Map<string, string>();
  if (!raw) return map;
  for (const line of raw.split("\n")) {
    if (line.length < 4 || line.startsWith("##")) continue;
    const [x, y] = [line[0], line[1]];
    const path = line.slice(3).trim().replace(/"/g, "");
    if (!path) continue;
    const code = y !== " " ? y : x;
    map.set(path.replace(/\\/g, "/"), code === "?" ? "?" : code);
  }
  return map;
}
