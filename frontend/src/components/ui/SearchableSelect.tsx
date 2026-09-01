import { useState } from "react";
import { cn } from "@/lib/cn";

export interface SearchableSelectOption {
  value: string;
  label: string;
  /** Optional heading consecutive options are grouped under (e.g. "Quick add"). */
  group?: string;
}

interface SearchableSelectProps {
  options: SearchableSelectOption[];
  /** Currently selected value, or `null` for a stateless "add" picker that
   * always shows its placeholder rather than a persistent selection. */
  value: string | null;
  onSelect: (value: string) => void;
  placeholder: string;
  disabled?: boolean;
  className?: string;
  "data-testid"?: string;
}

/** True if every character of `query` appears in `text`, in order (case-insensitive).
 * Classic "fuzzy" filter (e.g. command palettes): lets "tftl" match
 * "tube_furnace.total_length" without requiring a contiguous substring. */
function fuzzyMatch(query: string, text: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  const t = text.toLowerCase();
  let qi = 0;
  for (let i = 0; i < t.length && qi < q.length; i++) {
    if (t[i] === q[qi]) qi++;
  }
  return qi === q.length;
}

/** Groups consecutive options sharing the same `group`, preserving order. */
function groupOptions(
  options: SearchableSelectOption[],
): { group: string | undefined; options: SearchableSelectOption[] }[] {
  const sections: { group: string | undefined; options: SearchableSelectOption[] }[] = [];
  for (const option of options) {
    const last = sections.at(-1);
    if (last && last.group === option.group) last.options.push(option);
    else sections.push({ group: option.group, options: [option] });
  }
  return sections;
}

/**
 * Type-to-filter dropdown: the input itself is the trigger (Airtable-style),
 * no separate filter box next to a native `<select>`. Typing while open
 * fuzzy-filters the option list live; picking one (click or Enter) selects it.
 */
export function SearchableSelect({
  options,
  value,
  onSelect,
  placeholder,
  disabled,
  className,
  ...rest
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(0);
  const testId = rest["data-testid"];

  const filtered = options.filter((o) => fuzzyMatch(query, o.label));
  const sections = groupOptions(filtered);
  const selectedLabel = options.find((o) => o.value === value)?.label ?? "";

  const select = (option: SearchableSelectOption) => {
    onSelect(option.value);
    setOpen(false);
    setQuery("");
  };

  return (
    <div className={cn("relative", className)}>
      <input
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls={testId && `${testId}-listbox`}
        className="w-full rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground"
        placeholder={placeholder}
        disabled={disabled}
        value={open ? query : selectedLabel}
        data-testid={testId}
        onFocus={() => {
          setOpen(true);
          setQuery("");
          setHighlight(0);
        }}
        onChange={(e) => {
          setQuery(e.target.value);
          setHighlight(0);
        }}
        onBlur={() => {
          setOpen(false);
          setQuery("");
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setHighlight((h) => Math.min(h + 1, filtered.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setHighlight((h) => Math.max(h - 1, 0));
          } else if (e.key === "Enter") {
            e.preventDefault();
            const chosen = filtered[highlight];
            if (chosen) select(chosen);
          } else if (e.key === "Escape") {
            e.currentTarget.blur();
          }
        }}
      />
      {open && filtered.length > 0 && (
        <ul
          role="listbox"
          id={testId && `${testId}-listbox`}
          className="absolute z-10 mt-0.5 max-h-56 w-full overflow-auto rounded-md border border-border bg-background py-1 text-xs shadow-md"
        >
          {sections.map((section, sectionIndex) => (
            <li key={section.group ?? sectionIndex}>
              {section.group && (
                <div className="px-2 pt-1 text-[10px] font-medium text-muted-foreground">
                  {section.group}
                </div>
              )}
              <ul role="group">
                {section.options.map((option) => {
                  const index = filtered.indexOf(option);
                  return (
                    <li key={option.value} role="presentation">
                      <button
                        type="button"
                        role="option"
                        aria-selected={index === highlight}
                        data-testid={testId && `${testId}-option-${option.value}`}
                        className={cn(
                          "block w-full truncate px-2 py-1 text-left text-foreground hover:bg-accent",
                          index === highlight && "bg-accent",
                        )}
                        onMouseDown={(e) => e.preventDefault()}
                        onMouseEnter={() => setHighlight(index)}
                        onClick={() => select(option)}
                      >
                        {option.label}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
