export const RIGHT_PANEL_MIN = 360;
export const RIGHT_PANEL_MAX = 680;

export function clampRightPanelWidth(width: number): number {
  return Number.isFinite(width)
    ? Math.min(RIGHT_PANEL_MAX, Math.max(RIGHT_PANEL_MIN, width))
    : RIGHT_PANEL_MIN;
}