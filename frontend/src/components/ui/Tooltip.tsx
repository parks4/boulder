import { useId, useState, type ReactNode } from "react";

interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  className?: string;
}

const _DISPLAY_UTILITIES = new Set([
  "block",
  "inline-block",
  "inline",
  "flex",
  "inline-flex",
  "grid",
  "inline-grid",
  "contents",
  "hidden",
]);

/**
 * Hover/focus tooltip that works even when `children` is a disabled button.
 *
 * Disabled buttons get `pointer-events-none` (see Button.tsx), which blocks
 * their own `title` attribute from ever showing. Wrapping the trigger in this
 * span keeps the hover/focus listeners on an always-interactive ancestor, so
 * "why is this disabled" tooltips actually appear.
 */
export function Tooltip({ content, children, className }: TooltipProps) {
  const [open, setOpen] = useState(false);
  const id = useId();

  // Default to `inline-flex` (shrink-to-fit trigger), but defer to a display
  // utility the caller passed (e.g. `className="block"` for a full-width
  // button) -- Tailwind's generated stylesheet defines `.inline-flex` after
  // `.block`, so appending "block" to the class string does NOT override a
  // hardcoded "inline-flex" of equal specificity; only omitting it does.
  const callerClasses = (className ?? "").split(/\s+/).filter(Boolean);
  const display = callerClasses.some((c) => _DISPLAY_UTILITIES.has(c))
    ? ""
    : "inline-flex";

  return (
    <span
      className={`relative ${display} ${className ?? ""}`.trim().replace(/\s+/g, " ")}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      <span aria-describedby={open ? id : undefined} className="contents">
        {children}
      </span>
      {open && (
        <span
          id={id}
          role="tooltip"
          className="absolute bottom-full left-1/2 z-30 mb-1.5 w-max max-w-xs -translate-x-1/2 rounded-md border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-lg"
        >
          {content}
        </span>
      )}
    </span>
  );
}
