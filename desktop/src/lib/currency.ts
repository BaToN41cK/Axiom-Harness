/** Format an integer AXIOM balance stored in USD cents. */
export function axiomUsd(minor: number): string {
  if (!Number.isSafeInteger(minor) || minor < 0) return "$0.00";
  const dollars = Math.floor(minor / 100);
  const cents = String(minor % 100).padStart(2, "0");
  return `$${dollars}.${cents}`;
}

/** Convert a RUB amount stored in kopecks to AXIOM USD cents at 100:1. */
export function rubMinorToAxiomUsdMinor(rubMinor: number): number {
  if (!Number.isSafeInteger(rubMinor) || rubMinor < 0) return 0;
  return Math.floor(rubMinor / 100);
}