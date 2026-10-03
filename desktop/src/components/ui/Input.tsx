import { forwardRef } from "react";
import type { InputHTMLAttributes, ReactNode } from "react";
import { Search, X } from "lucide-react";
import { IconButton } from "./Button";
import { useLocale } from "../../lib/locale";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  icon?: ReactNode;
  /** Inline validation message; renders the error state plus icon + text. */
  error?: string | null;
  /** Quiet helper line under the field. */
  hint?: string;
  label?: string;
  block?: boolean;
}

/**
 * Text input with inline validation. The error is always rendered as text next
 * to the field, never as a bare red border.
 */
export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { icon, error, hint, label, block = true, className = "", id, ...rest },
  ref,
) {
  const fieldId = id ?? rest.name ?? undefined;
  const describedBy = error ? `${fieldId}-error` : hint ? `${fieldId}-hint` : undefined;
  return (
    <div className={"ax-field" + (block ? " ax-field-block" : "") + (className ? ` ${className}` : "")}>
      {label && (
        <label className="ax-field-label" htmlFor={fieldId}>
          {label}
        </label>
      )}
      <div className={"ax-input-shell" + (error ? " is-invalid" : "")}>
        {icon && <span className="ax-input-icon">{icon}</span>}
        <input
          {...rest}
          id={fieldId}
          ref={ref}
          className="ax-input"
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
        />
      </div>
      {error ? (
        <p className="ax-field-error" id={`${fieldId}-error`} role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="ax-field-hint" id={`${fieldId}-hint`}>
          {hint}
        </p>
      ) : null}
    </div>
  );
});

interface SearchInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> {
  value: string;
  onValueChange: (value: string) => void;
  /** Accessible name; also used as the clear-button context. */
  label: string;
}

/** Search field with a leading icon and a clear button once it has content. */
export const SearchInput = forwardRef<HTMLInputElement, SearchInputProps>(function SearchInput(
  { value, onValueChange, label, className = "", ...rest },
  ref,
) {
  const { t } = useLocale();
  return (
    <div className={"ax-input-shell ax-search" + (className ? ` ${className}` : "")}>
      <span className="ax-input-icon">
        <Search size={13} strokeWidth={1.8} aria-hidden />
      </span>
      <input
        {...rest}
        ref={ref}
        className="ax-input"
        type="search"
        value={value}
        aria-label={label}
        onChange={(event) => onValueChange(event.target.value)}
      />
      {value && (
        <IconButton
          label={t("ui.input.clear_search")}
          size="sm"
          className="ax-search-clear"
          onClick={() => onValueChange("")}
        >
          <X size={12} strokeWidth={2} aria-hidden />
        </IconButton>
      )}
    </div>
  );
});
