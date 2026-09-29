import { forwardRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Loader2 } from "lucide-react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shows a spinner and blocks interaction without changing the layout. */
  loading?: boolean;
  /** Marks the control as carrying an error; pairs with a visible message. */
  invalid?: boolean;
  icon?: ReactNode;
  iconRight?: ReactNode;
  /** Stretches to the container width (dialog footers, side panels). */
  block?: boolean;
}

/**
 * The single button primitive. `primary` is the only accent-filled variant —
 * everything else stays neutral so the accent keeps meaning "main action".
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "secondary",
    size = "md",
    loading = false,
    invalid = false,
    icon,
    iconRight,
    block = false,
    className = "",
    disabled,
    children,
    type = "button",
    ...rest
  },
  ref,
) {
  const classes = [
    "ax-btn",
    `ax-btn-${variant}`,
    `ax-btn-${size}`,
    block ? "ax-btn-block" : "",
    loading ? "is-loading" : "",
    invalid ? "is-invalid" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <button
      {...rest}
      ref={ref}
      type={type}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      aria-invalid={invalid || undefined}
    >
      {loading ? (
        <Loader2 className="ax-spin" size={size === "sm" ? 13 : 14} strokeWidth={2} aria-hidden />
      ) : (
        icon
      )}
      {children != null && <span className="ax-btn-label">{children}</span>}
      {iconRight}
    </button>
  );
});

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Required: an icon-only control must still announce itself. */
  label: string;
  variant?: ButtonVariant;
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  /** Renders the pressed/selected state (aria-pressed is set too). */
  active?: boolean;
  children: ReactNode;
}

/** Icon-only button. `label` becomes both aria-label and the native tooltip. */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  {
    label,
    variant = "ghost",
    size = "md",
    loading = false,
    active,
    className = "",
    disabled,
    children,
    type = "button",
    title,
    ...rest
  },
  ref,
) {
  const classes = [
    "ax-icon-btn",
    `ax-icon-btn-${variant}`,
    `ax-icon-btn-${size}`,
    active ? "is-active" : "",
    loading ? "is-loading" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <button
      {...rest}
      ref={ref}
      type={type}
      className={classes}
      aria-label={label}
      title={title ?? label}
      aria-pressed={active}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
    >
      {loading ? <Loader2 className="ax-spin" size={14} strokeWidth={2} aria-hidden /> : children}
    </button>
  );
});
