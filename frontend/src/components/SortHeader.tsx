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

/** A column heading you click to sort: first direction → reverse → back to the natural order. */
export function SortHeader<K extends string>({ label, sortKey, sort, onToggle, align = "left", className = "", title, as = "th" }: Props<K>) {
  const dir = sort?.key === sortKey ? sort.dir : undefined;
  const Cell = as;
  return (
    <Cell
      role={as === "div" ? "columnheader" : undefined}
      aria-sort={ariaSort(dir)}
      className={`th ${align === "right" ? "text-right" : ""} ${className}`}
      title={title}
    >
      <button
        type="button"
        onClick={() => onToggle(sortKey)}
        className={`group inline-flex items-center gap-1 uppercase hover:text-slate-800 dark:hover:text-slate-200 ${
          align === "right" ? "flex-row-reverse" : ""
        } ${dir ? "text-teal-700 dark:text-teal-300" : ""}`}
      >
        {label}
        <span aria-hidden className={`text-[0.65rem] ${dir ? "" : "opacity-0 group-hover:opacity-50"}`}>
          {dir === "desc" ? "▼" : dir === "asc" ? "▲" : "↕"}
        </span>
      </button>
    </Cell>
  );
}
