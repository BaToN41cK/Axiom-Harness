/**
 * AXIOM design system — the base component layer.
 *
 * Every surface in the desktop client composes from these primitives so that
 * states (hover, focus-visible, active, disabled, loading, error) and the
 * colour/spacing tokens are defined exactly once.
 */
export { Button, IconButton } from "./Button";
export type { ButtonVariant, ButtonSize } from "./Button";
export { Input, SearchInput } from "./Input";
export { Badge, StatusPill, ErrorNote } from "./Status";
export type { StatusTone, PillState } from "./Status";
export { Tabs, TabPanel } from "./Tabs";
export type { TabItem } from "./Tabs";
export { Card, CardHeader, EmptyState, Skeleton, Unknown } from "./Card";
export { Dropdown } from "./Dropdown";
export type { MenuItem } from "./Dropdown";
export { Tooltip, Kbd } from "./Tooltip";
export { Splitter } from "./Splitter";
export { ToolCallCard } from "./ToolCallCard";
export type { ToolCardState } from "./ToolCallCard";
