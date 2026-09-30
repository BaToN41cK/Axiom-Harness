import assert from "node:assert/strict";
import test from "node:test";

const source = await (await import("node:fs/promises")).readFile(new URL("./currency.ts", import.meta.url), "utf8");
const runnableSource = source
  .replaceAll(/: number/g, "")
  .replaceAll(/: string/g, "")
  .replaceAll(/export function ([^(]+)\(([^)]*)\): (string|number) \{/g, "export function $1($2) {");
const { axiomUsd, rubMinorToAxiomUsdMinor } = await import(
  `data:text/javascript,${encodeURIComponent(runnableSource)}`
);

test("AXIOM USD balance formatting", () => {
  assert.equal(axiomUsd(0), "$0.00");
  assert.equal(axiomUsd(200), "$2.00");
  assert.equal(axiomUsd(1250), "$12.50");
});

test("RUB kopecks are previewed as AXIOM USD credits", () => {
  assert.equal(axiomUsd(rubMinorToAxiomUsdMinor(10_000)), "$1.00");
  assert.equal(axiomUsd(rubMinorToAxiomUsdMinor(20_000)), "$2.00");
  assert.equal(axiomUsd(rubMinorToAxiomUsdMinor(50_000)), "$5.00");
  assert.equal(axiomUsd(rubMinorToAxiomUsdMinor(125_000)), "$12.50");
});