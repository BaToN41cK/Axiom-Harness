import { useState } from "react";
import type {
  Artifact,
  ChartArtifact,
  ChecklistArtifact,
  ComparisonArtifact,
  MermaidArtifact,
  TableArtifact,
} from "../types";
import {
  artifactToCsv,
  artifactToMarkdown,
  artifactToSvg,
  downloadBlob,
  downloadText,
  svgToPng,
} from "../lib/artifacts";
import { useLocale } from "../lib/locale";

const TYPE_LABEL: Record<Artifact["type"], string> = {
  table: "ui.artifact.type.table",
  comparison: "ui.artifact.type.comparison",
  checklist: "ui.artifact.type.checklist",
  mermaid: "ui.artifact.type.mermaid",
  chart: "ui.artifact.type.chart",
};

function slugOf(artifact: Artifact): string {
  const base = (artifact.title || artifact.type).toLowerCase().replace(/[^a-z0-9а-яё]+/gi, "-");
  return base.replace(/^-+|-+$/g, "") || "artifact";
}

function TableBody({ artifact }: { artifact: TableArtifact }) {
  return (
    <table className="artifact-table">
      <thead>
        <tr>{artifact.columns.map((column, index) => <th key={index}>{column}</th>)}</tr>
      </thead>
      <tbody>
        {artifact.rows.map((row, rowIndex) => (
          <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>
        ))}
      </tbody>
    </table>
  );
}

function ComparisonBody({ artifact }: { artifact: ComparisonArtifact }) {
  return (
    <div className="artifact-compare">
      {artifact.items.map((item, index) => (
        <div className="artifact-compare-row" key={index}>
          <span className="artifact-compare-label">{item.label}</span>
          <span className="artifact-compare-cell">{item.left}</span>
          <span className="artifact-compare-cell">{item.right}</span>
        </div>
      ))}
    </div>
  );
}

function ChecklistBody({ artifact }: { artifact: ChecklistArtifact }) {
  return (
    <ul className="artifact-checklist">
      {artifact.items.map((item, index) => (
        <li key={index} className={item.checked ? "done" : ""}>
          <span className="artifact-check">{item.checked ? "✓" : ""}</span>
          {item.label}
        </li>
      ))}
    </ul>
  );
}

function MermaidBody({ artifact }: { artifact: MermaidArtifact }) {
  return <pre className="artifact-mermaid">{artifact.diagram}</pre>;
}

function ChartBody({ artifact }: { artifact: ChartArtifact }) {
  return <div className="artifact-chart" dangerouslySetInnerHTML={{ __html: artifactToSvg(artifact) }} />;
}

function renderBody(artifact: Artifact) {
  switch (artifact.type) {
    case "table":
      return <TableBody artifact={artifact} />;
    case "comparison":
      return <ComparisonBody artifact={artifact} />;
    case "checklist":
      return <ChecklistBody artifact={artifact} />;
    case "mermaid":
      return <MermaidBody artifact={artifact} />;
    case "chart":
      return <ChartBody artifact={artifact} />;
  }
}

export default function ArtifactView({ artifact }: { artifact: Artifact }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { t } = useLocale();
  const slug = slugOf(artifact);
  const canTabular = artifact.type !== "mermaid";

  async function exportPng() {
    setBusy(true);
    setError(null);
    try {
      const blob = await svgToPng(artifactToSvg(artifact));
      downloadBlob(`${slug}.png`, blob);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="artifact-card">
      <header className="artifact-head">
        <span className="artifact-kind">{t(TYPE_LABEL[artifact.type])}</span>
        {artifact.title && <span className="artifact-title">{artifact.title}</span>}
        <span className="artifact-actions">
          <button
            type="button"
            onClick={() => downloadText(`${slug}.md`, artifactToMarkdown(artifact), "text/markdown")}
            title={t("ui.artifact.download_md")}
          >
            MD
          </button>
          {canTabular && (
            <button
              type="button"
              onClick={() => downloadText(`${slug}.csv`, artifactToCsv(artifact), "text/csv")}
              title={t("ui.artifact.download_csv")}
            >
              CSV
            </button>
          )}
          {canTabular && (
            <button
              type="button"
              onClick={() => downloadText(`${slug}.svg`, artifactToSvg(artifact), "image/svg+xml")}
              title={t("ui.artifact.download_svg")}
            >
              SVG
            </button>
          )}
          {canTabular && (
            <button type="button" onClick={() => void exportPng()} disabled={busy} title={t("ui.artifact.download_png")}>
              PNG
            </button>
          )}
        </span>
      </header>
      {error && <div className="artifact-error">{error}</div>}
      <div className="artifact-body">{renderBody(artifact)}</div>
    </div>
  );
}
