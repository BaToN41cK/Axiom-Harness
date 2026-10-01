/**
 * Client-side rendering + export for W3.4 structured artifacts.
 *
 * The core validates artifacts and persists them on the assistant message; this
 * module turns that validated data into the Markdown/CSV/SVG the user can copy
 * or download. SVG export also feeds the PNG rasterizer (a real canvas → PNG
 * blob, never a fabricated file).
 */

import type { Artifact, ChartArtifact } from "../types";

const SVG_WIDTH = 640;
const CHART_COLORS = ["#e63946", "#4d96ff", "#2ec46f", "#f5a623", "#b07cff"];

function escapeSvg(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function chartLabels(artifact: ChartArtifact): string[] {
  return artifact.labels.length
    ? artifact.labels
    : artifact.series[0].values.map((_, index) => String(index + 1));
}

// ------------------------------------------------------------------- Markdown

export function artifactToMarkdown(artifact: Artifact): string {
  switch (artifact.type) {
    case "table": {
      const header = `| ${artifact.columns.join(" | ")} |`;
      const separator = `| ${artifact.columns.map(() => "---").join(" | ")} |`;
      const body = artifact.rows.map((row) => `| ${row.join(" | ")} |`);
      return [header, separator, ...body].join("\n");
    }
    case "comparison": {
      const lines = ["| Aspect | Left | Right |", "|---|---|---|"];
      for (const item of artifact.items) lines.push(`| ${item.label} | ${item.left} | ${item.right} |`);
      return lines.join("\n");
    }
    case "checklist":
      return artifact.items.map((item) => `- [${item.checked ? "x" : " "}] ${item.label}`).join("\n");
    case "mermaid":
      return "```mermaid\n" + artifact.diagram.trim() + "\n```";
    case "chart": {
      const labels = chartLabels(artifact);
      const header = `| Label | ${artifact.series.map((series) => series.label).join(" | ")} |`;
      const separator = `| ${artifact.series.map(() => "---").join(" | ")} |`;
      const rows = labels.map(
        (label, index) =>
          `| ${label} | ${artifact.series.map((series) => String(series.values[index])).join(" | ")} |`,
      );
      return [header, separator, ...rows].join("\n");
    }
  }
}

// ------------------------------------------------------------------------ CSV

function csvCell(cell: string): string {
  return /[",\n]/.test(cell) ? `"${cell.replace(/"/g, '""')}"` : cell;
}

function csvRow(cells: string[]): string {
  return cells.map(csvCell).join(",");
}

export function artifactToCsv(artifact: Artifact): string {
  switch (artifact.type) {
    case "table":
      return [csvRow(artifact.columns), ...artifact.rows.map((row) => csvRow(row))].join("\n");
    case "comparison":
      return [
        "aspect,left,right",
        ...artifact.items.map((item) => csvRow([item.label, item.left, item.right])),
      ].join("\n");
    case "checklist":
      return [
        "label,checked",
        ...artifact.items.map((item) => csvRow([item.label, item.checked ? "yes" : "no"])),
      ].join("\n");
    case "chart": {
      const labels = chartLabels(artifact);
      return [
        csvRow(["label", ...artifact.series.map((series) => series.label)]),
        ...labels.map((label, index) =>
          csvRow([label, ...artifact.series.map((series) => String(series.values[index]))]),
        ),
      ].join("\n");
    }
    case "mermaid":
      throw new Error("Mermaid cannot be exported as CSV; use Markdown (.mmd) instead");
  }
}

// ------------------------------------------------------------------------- SVG

export function artifactToSvg(artifact: Artifact): string {
  switch (artifact.type) {
    case "mermaid":
      throw new Error("Mermaid diagrams need a renderer; export them to Markdown (.mmd) instead");
    case "chart":
      return chartSvg(artifact);
    case "table":
      return textSvg(artifact.title, [
        artifact.columns.join(" | "),
        "-".repeat(64),
        ...artifact.rows.map((row) => row.join(" | ")),
      ]);
    case "comparison":
      return textSvg(
        artifact.title,
        artifact.items.map((item) => `${item.label}: ${item.left}  →  ${item.right}`),
      );
    case "checklist":
      return textSvg(
        artifact.title,
        artifact.items.map((item) => `[${item.checked ? "x" : " "}] ${item.label}`),
      );
  }
}

function textSvg(title: string | null | undefined, lines: string[], lineHeight = 20): string {
  const height = 32 + lines.length * lineHeight + 16;
  const parts = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${SVG_WIDTH}" height="${height}" ` +
      `viewBox="0 0 ${SVG_WIDTH} ${height}" font-family="ui-monospace, monospace" font-size="13">`,
    `<rect width="${SVG_WIDTH}" height="${height}" fill="#0b0b0e"/>`,
  ];
  let y = 24;
  if (title) {
    parts.push(
      `<text x="16" y="${y}" fill="#e63946" font-size="15" font-weight="bold">${escapeSvg(title)}</text>`,
    );
    y += 26;
  }
  for (const line of lines) {
    parts.push(`<text x="16" y="${y}" fill="#e8e8ec">${escapeSvg(line)}</text>`);
    y += lineHeight;
  }
  parts.push("</svg>");
  return parts.join("\n");
}

function chartSvg(artifact: ChartArtifact): string {
  const labels = chartLabels(artifact);
  const maxValue =
    Math.max(...artifact.series.flatMap((series) => series.values.map((value) => Math.abs(value))), 0) || 1;
  const barX = 128;
  const barW = 400;
  const rowH = 24;
  const height = 44 + labels.length * artifact.series.length * rowH + 16;
  const parts = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${SVG_WIDTH}" height="${height}" ` +
      `viewBox="0 0 ${SVG_WIDTH} ${height}" font-family="ui-monospace, monospace" font-size="12">`,
    `<rect width="${SVG_WIDTH}" height="${height}" fill="#0b0b0e"/>`,
  ];
  let y = 24;
  if (artifact.title) {
    parts.push(
      `<text x="16" y="${y}" fill="#e63946" font-size="15" font-weight="bold">${escapeSvg(artifact.title)}</text>`,
    );
    y += 26;
  }
  labels.forEach((label, labelIndex) => {
    artifact.series.forEach((series, seriesIndex) => {
      const value = series.values[labelIndex] ?? 0;
      const width = Math.round((barW * Math.abs(value)) / maxValue);
      const color = CHART_COLORS[seriesIndex % CHART_COLORS.length];
      const shownLabel = seriesIndex === 0 ? label : "";
      parts.push(`<text x="16" y="${y + 12}" fill="#e8e8ec">${escapeSvg(shownLabel)}</text>`);
      parts.push(`<rect x="${barX}" y="${y}" width="${width}" height="14" rx="2" fill="${color}"/>`);
      parts.push(
        `<text x="${barX + width + 8}" y="${y + 12}" fill="#9aa0aa">${value} ${escapeSvg(series.label)}</text>`,
      );
      y += rowH;
    });
  });
  parts.push("</svg>");
  return parts.join("\n");
}

// ------------------------------------------------------------------------- PNG

/** Rasterize a standalone SVG string into a real PNG blob via a canvas. */
export async function svgToPng(svg: string, scale = 2): Promise<Blob> {
  const blob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  try {
    const image = new Image();
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error("SVG failed to load"));
      image.src = url;
    });
    const width = image.naturalWidth || image.width || SVG_WIDTH;
    const height = image.naturalHeight || image.height || 480;
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Canvas 2D context unavailable");
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    return await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(
        (encoded) => (encoded ? resolve(encoded) : reject(new Error("PNG encoding failed"))),
        "image/png",
      );
    });
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Trigger a client-side download of text or binary content. */
export function downloadBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function downloadText(filename: string, text: string, mime = "text/plain"): void {
  downloadBlob(filename, new Blob([text], { type: `${mime};charset=utf-8` }));
}
