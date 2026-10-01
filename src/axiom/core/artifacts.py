"""Structured answer artifacts (W3.4).

The model can emit a validated artifact — a table, a side-by-side comparison,
a checklist, a Mermaid diagram, or a simple chart — instead of an unstructured
wall of prose. Every artifact is validated before it is accepted: missing or
malformed data produces an explicit failure, never a decorative placeholder.

Artifacts render to Markdown (the universal format) and export to CSV and SVG
where a tabular/visual form exists. Mermaid has no tabular form, so it exports
as a fenced Markdown block and refuses CSV/SVG with an honest error instead of
producing a fake graphic.
"""

from __future__ import annotations

import csv
import io
from typing import Annotated, Literal
from xml.sax.saxutils import escape as _xml_escape

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, model_validator

from axiom.core.tools.base import RISK_SAFE, ToolDefinition, ToolPermission, ToolResult

_SVG_WIDTH = 640


class _Titled(BaseModel):
    """Optional short title shared by every artifact variant."""

    title: str | None = None


class TableArtifact(_Titled):
    """A Markdown table: named columns and rectangular rows."""

    type: Literal["table"] = "table"
    columns: list[str] = Field(min_length=1)
    rows: list[list[str]] = Field(min_length=1)

    @model_validator(mode="after")
    def _rows_match_columns(self) -> TableArtifact:
        width = len(self.columns)
        for index, row in enumerate(self.rows):
            if len(row) != width:
                raise ValueError(f"row {index} has {len(row)} cells but there are {width} columns")
        return self


class ComparisonItem(BaseModel):
    label: str
    left: str = ""
    right: str = ""


class ComparisonArtifact(_Titled):
    """A side-by-side comparison of two options across labeled aspects."""

    type: Literal["comparison"] = "comparison"
    items: list[ComparisonItem] = Field(min_length=1)


class ChecklistItem(BaseModel):
    label: str
    checked: bool = False


class ChecklistArtifact(_Titled):
    """A list of checkable items."""

    type: Literal["checklist"] = "checklist"
    items: list[ChecklistItem] = Field(min_length=1)


class MermaidArtifact(_Titled):
    """A Mermaid diagram supplied as raw diagram text."""

    type: Literal["mermaid"] = "mermaid"
    diagram: str = Field(min_length=1)


class ChartSeries(BaseModel):
    label: str
    values: list[float]


class ChartArtifact(_Titled):
    """A simple chart: categories plus one or more numeric series."""

    type: Literal["chart"] = "chart"
    labels: list[str] = Field(default_factory=list)
    series: list[ChartSeries] = Field(min_length=1)

    @model_validator(mode="after")
    def _series_align(self) -> ChartArtifact:
        if self.labels:
            width = len(self.labels)
            for item in self.series:
                if len(item.values) != width:
                    raise ValueError(
                        f"series '{item.label}' has {len(item.values)} values but there are {width} labels"
                    )
        else:
            widths = {len(item.values) for item in self.series}
            if len(widths) > 1:
                raise ValueError("all series must have the same number of values when labels are omitted")
        return self


Artifact = Annotated[
    TableArtifact | ComparisonArtifact | ChecklistArtifact | MermaidArtifact | ChartArtifact,
    Field(discriminator="type"),
]

_ARTIFACT_ADAPTER: TypeAdapter = TypeAdapter(Artifact)


def build_artifact(type: str, payload: dict, title: str | None = None) -> Artifact:
    """Validate a raw ``(type, payload)`` pair into a concrete artifact.

    Raises :class:`pydantic.ValidationError` when the payload is missing data
    or malformed; callers surface that as an explicit failure.
    """
    data = dict(payload or {})
    data["type"] = type
    if title:
        data["title"] = title
    return _ARTIFACT_ADAPTER.validate_python(data)


# --------------------------------------------------------------------------- render / export


def to_markdown(artifact: Artifact) -> str:
    """Render any artifact to a Markdown block (chat display and export)."""
    if isinstance(artifact, TableArtifact):
        header = "| " + " | ".join(artifact.columns) + " |"
        separator = "| " + " | ".join("---" for _ in artifact.columns) + " |"
        body = ["| " + " | ".join(row) + " |" for row in artifact.rows]
        return "\n".join([header, separator, *body])
    if isinstance(artifact, ComparisonArtifact):
        lines = ["| Aspect | Left | Right |", "|---|---|---|"]
        for item in artifact.items:
            lines.append(f"| {item.label} | {item.left} | {item.right} |")
        return "\n".join(lines)
    if isinstance(artifact, ChecklistArtifact):
        return "\n".join(f"- [{'x' if item.checked else ' '}] {item.label}" for item in artifact.items)
    if isinstance(artifact, MermaidArtifact):
        return "```mermaid\n" + artifact.diagram.strip() + "\n```"
    if isinstance(artifact, ChartArtifact):
        labels = artifact.labels or [str(i + 1) for i in range(len(artifact.series[0].values))]
        header = "| Label | " + " | ".join(item.label for item in artifact.series) + " |"
        separator = "| " + " | ".join("---" for _ in range(len(artifact.series) + 1)) + " |"
        rows = []
        for index, label in enumerate(labels):
            cells = [str(item.values[index]) for item in artifact.series]
            rows.append("| " + " | ".join([label, *cells]) + " |")
        return "\n".join([header, separator, *rows])
    raise TypeError(f"unsupported artifact: {type(artifact).__name__}")


def to_csv(artifact: Artifact) -> str:
    """Export a tabular artifact to CSV. Mermaid has no tabular form."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    if isinstance(artifact, TableArtifact):
        writer.writerow(artifact.columns)
        writer.writerows(artifact.rows)
    elif isinstance(artifact, ComparisonArtifact):
        writer.writerow(["aspect", "left", "right"])
        for item in artifact.items:
            writer.writerow([item.label, item.left, item.right])
    elif isinstance(artifact, ChecklistArtifact):
        writer.writerow(["label", "checked"])
        for item in artifact.items:
            writer.writerow([item.label, "yes" if item.checked else "no"])
    elif isinstance(artifact, ChartArtifact):
        labels = artifact.labels or [str(i + 1) for i in range(len(artifact.series[0].values))]
        writer.writerow(["label", *(item.label for item in artifact.series)])
        for index, label in enumerate(labels):
            writer.writerow([label, *(str(item.values[index]) for item in artifact.series)])
    else:
        raise ValueError("Mermaid diagrams cannot be exported as CSV; use Markdown export instead")
    return buffer.getvalue()


def to_svg(artifact: Artifact) -> str:
    """Export an artifact to a self-contained SVG document.

    Mermaid needs a layout engine, so it raises instead of fabricating a
    graphic — export Mermaid to Markdown (``.mmd``) instead.
    """
    if isinstance(artifact, MermaidArtifact):
        raise ValueError("Mermaid diagrams need a renderer; export them to Markdown (.mmd) instead")
    if isinstance(artifact, ChartArtifact):
        return _svg_chart(artifact)
    if isinstance(artifact, TableArtifact):
        lines = [" | ".join(artifact.columns)]
        lines.append("-" * 64)
        lines.extend(" | ".join(row) for row in artifact.rows)
        return _svg_text(artifact.title, lines)
    if isinstance(artifact, ComparisonArtifact):
        lines = [f"{item.label}: {item.left}  →  {item.right}" for item in artifact.items]
        return _svg_text(artifact.title, lines)
    if isinstance(artifact, ChecklistArtifact):
        lines = [f"[{'x' if item.checked else ' '}] {item.label}" for item in artifact.items]
        return _svg_text(artifact.title, lines)
    raise TypeError(f"unsupported artifact: {type(artifact).__name__}")


def _svg_text(title: str | None, lines: list[str], line_height: int = 20) -> str:
    height = 32 + len(lines) * line_height + 16
    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{_SVG_WIDTH}" '
            f'viewBox="0 0 {_SVG_WIDTH} {height}" font-family="monospace" font-size="13">'
        ),
        f'<rect width="{_SVG_WIDTH}" height="{height}" fill="#0b0b0e"/>',
    ]
    y = 24
    if title:
        parts.append(
            f'<text x="16" y="{y}" fill="#e63946" font-size="15" font-weight="bold">{_xml_escape(title)}</text>'
        )
        y += 26
    for line in lines:
        parts.append(f'<text x="16" y="{y}" fill="#e8e8ec">{_xml_escape(line)}</text>')
        y += line_height
    parts.append("</svg>")
    return "\n".join(parts)


def _svg_chart(artifact: ChartArtifact) -> str:
    labels = artifact.labels or [str(i + 1) for i in range(len(artifact.series[0].values))]
    max_value = max((value for item in artifact.series for value in item.values), default=0.0) or 1.0
    colors = ["#e63946", "#4d96ff", "#2ec46f", "#f5a623", "#b07cff"]
    bar_x = 128
    bar_w = 400
    row_h = 24
    height = 44 + len(labels) * len(artifact.series) * row_h + 16
    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{_SVG_WIDTH}" '
            f'viewBox="0 0 {_SVG_WIDTH} {height}" font-family="monospace" font-size="12">'
        ),
        f'<rect width="{_SVG_WIDTH}" height="{height}" fill="#0b0b0e"/>',
    ]
    y = 24
    if artifact.title:
        parts.append(
            f'<text x="16" y="{y}" fill="#e63946" font-size="15" '
            f'font-weight="bold">{_xml_escape(artifact.title)}</text>'
        )
        y += 26
    for label_index, label in enumerate(labels):
        for series_index, item in enumerate(artifact.series):
            value = item.values[label_index]
            width = int(bar_w * (abs(value) / max_value))
            color = colors[series_index % len(colors)]
            shown_label = label if series_index == 0 else ""
            parts.append(f'<text x="16" y="{y + 12}" fill="#e8e8ec">{_xml_escape(shown_label)}</text>')
            parts.append(f'<rect x="{bar_x}" y="{y}" width="{width}" height="14" rx="2" fill="{color}"/>')
            parts.append(
                f'<text x="{bar_x + width + 8}" y="{y + 12}" fill="#9aa0aa">{value:g} {_xml_escape(item.label)}</text>'
            )
            y += row_h
    parts.append("</svg>")
    return "\n".join(parts)


class ArtifactTools:
    """Registers ``render_artifact`` so the model can emit structured output."""

    def register(self, registry) -> None:
        registry.register(
            ToolDefinition(
                name="render_artifact",
                description=(
                    "Render a structured artifact inside the answer instead of plain prose. "
                    "Use 'table' for rows of data, 'comparison' to weigh two options, "
                    "'checklist' for steps or tasks, 'mermaid' for a diagram, and 'chart' "
                    "for a small bar chart. The payload is type-specific and validated: "
                    "missing data fails explicitly."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["table", "comparison", "checklist", "mermaid", "chart"],
                            "description": "The artifact kind to render.",
                        },
                        "title": {"type": "string", "description": "Optional short title."},
                        "payload": {
                            "type": "object",
                            "description": (
                                "Type-specific payload. table: {columns: [str], rows: [[str]]}. "
                                "comparison: {items: [{label, left, right}]}. "
                                "checklist: {items: [{label, checked?}]}. "
                                "mermaid: {diagram: str}. "
                                "chart: {labels?: [str], series: [{label, values: [number]}]}."
                            ),
                        },
                    },
                    "required": ["type", "payload"],
                },
                permission=ToolPermission.ALWAYS,
                risk=RISK_SAFE,
                max_output=4000,
            ),
            self._render,
        )

    async def _render(self, type: str, payload: dict, title: str | None = None) -> ToolResult:
        try:
            artifact = build_artifact(type, payload or {}, title)
        except ValidationError as exc:
            return ToolResult(
                name="render_artifact",
                ok=False,
                error=f"Invalid artifact: {exc}",
                data={"validation_errors": exc.errors()},
            )
        return ToolResult(
            name="render_artifact",
            ok=True,
            content=to_markdown(artifact),
            data={"artifact": artifact.model_dump()},
        )


__all__ = [
    "Artifact",
    "ArtifactTools",
    "build_artifact",
    "to_csv",
    "to_markdown",
    "to_svg",
]
