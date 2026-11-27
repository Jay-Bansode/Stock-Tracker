import type { SortDir, SortState } from "../sorting";

interface Props<K extends string> {
  label: string;
  sortKey: K;
  sort: SortState<K>;
  onToggle: (key: K) => void;
  align?: "left" | "right";
  className?: string;
  title?: string;
  /** Render as a table header cell (<th>) instead of a grid cell (<div role="columnheader">). */
  as?: "th" | "div";
}

const ariaSort = (dir: SortDir | undefined) => (dir === "asc" ? "ascending" : dir === "desc" ? "descending" : "none");

/** Sort direction icon. SVG (not ▲▼↕ text) so it has a fixed box: font-fallback glyphs have
 * their own line metrics and nudged the heading text up or down. */
function SortIcon({ dir }: { dir: SortDir | undefined }) {
  return (
    <svg viewBox="0 0 12 12" aria-hidden className={`size-3 shrink-0 ${dir ? "" : "opacity-0 group-hover:opacity-60"}`}>
      {dir !== "desc" && <path d="M3 5l3-3 3 3" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />}
      {dir !== "asc" && <path d="M3 7l3 3 3-3" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />}
    </svg>
  );
}

/** A column heading you click to sort: first direction → reverse → back to the natural order. */
export function SortHeader<K extends string>({ label, sortKey, sort, onToggle, align = "left", className = "", title, as = "th" }: Props<K>) {
  const dir = sort?.key === sortKey ? sort.dir : undefined;
  const Cell = as;
  const right = align === "right";
  return (
    <Cell
      role={as === "div" ? "columnheader" : undefined}
      aria-sort={ariaSort(dir)}
      className={`th ${right ? "text-right" : ""} ${className}`}
      title={title}
    >
      {/* A block-level flex box, centred on its own height: it never sits on a text baseline,
          so every heading lines up whether or not its icon shows. */}
      <button
        type="button"
        onClick={() => onToggle(sortKey)}
        className={`group flex w-full items-center gap-1 leading-4 uppercase hover:text-slate-800 dark:hover:text-slate-200 ${
          right ? "justify-end" : ""
        } ${dir ? "text-teal-700 dark:text-teal-300" : ""}`}
      >
        {right && <SortIcon dir={dir} />}
        <span>{label}</span>
        {!right && <SortIcon dir={dir} />}
      </button>
    </Cell>
  );
}
