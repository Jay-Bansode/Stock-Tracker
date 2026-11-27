import type { SortState } from "../sorting";

interface Props<K extends string> {
  options: { key: K; label: string; first?: "asc" | "desc" }[];
  sort: SortState<K>;
  onChange: (sort: SortState<K>) => void;
  className?: string;
  /** Label for the "no sort" choice. */
  defaultLabel?: string;
}

/** "Sort by" dropdown + direction button, for layouts without column headings (phone cards, sidebar). */
export function SortSelect<K extends string>({ options, sort, onChange, className = "", defaultLabel = "Default order" }: Props<K>) {
  const pick = (key: string) => {
    const opt = options.find((o) => o.key === key);
    onChange(opt ? { key: opt.key, dir: opt.first ?? "asc" } : null);
  };
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <label className="flex min-w-0 flex-1 items-center gap-2 text-xs text-slate-500">
        <span className="shrink-0">Sort by</span>
        <select className="input min-w-0 py-1.5" aria-label="Sort by" value={sort?.key ?? ""} onChange={(e) => pick(e.target.value)}>
          <option value="">{defaultLabel}</option>
          {options.map((o) => (
            <option key={o.key} value={o.key}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      {sort && (
        <button
          type="button"
          className="btn btn-sm shrink-0"
          aria-label={sort.dir === "asc" ? "Ascending, switch to descending" : "Descending, switch to ascending"}
          onClick={() => onChange({ key: sort.key, dir: sort.dir === "asc" ? "desc" : "asc" })}
        >
          {sort.dir === "asc" ? "▲ Asc" : "▼ Desc"}
        </button>
      )}
    </div>
  );
}

export interface SortChoice<K extends string> {
  label: string;
  sort: SortState<K>;
}

const choiceValue = <K extends string>(sort: SortState<K>) => (sort ? `${sort.key}:${sort.dir}` : "");

/**
 * Compact text-style sort control for tight spots (the watchlists sidebar): "Sort: Name A–Z ▾".
 * Each choice carries its own direction, so there's no separate Asc/Desc button.
 */
export function SortMenu<K extends string>({
  choices,
  sort,
  onChange,
  label = "Sort",
  ariaLabel = "Sort",
  className = "",
}: {
  choices: SortChoice<K>[];
  sort: SortState<K>;
  onChange: (sort: SortState<K>) => void;
  label?: string;
  ariaLabel?: string;
  className?: string;
}) {
  const current = choiceValue(sort);
  const known = choices.some((c) => choiceValue(c.sort) === current);
  return (
    <label className={`relative inline-flex shrink-0 items-center gap-1 text-xs text-slate-500 ${className}`}>
      <span>{label}:</span>
      <select
        aria-label={ariaLabel}
        className="cursor-pointer appearance-none rounded bg-transparent py-0.5 pr-4 pl-0.5 font-medium text-slate-700 outline-none hover:text-teal-700 focus-visible:ring-2 focus-visible:ring-teal-600/40 dark:text-slate-200 dark:hover:text-teal-300"
        value={known ? current : ""}
        onChange={(e) => onChange(choices.find((c) => choiceValue(c.sort) === e.target.value)?.sort ?? null)}
      >
        {choices.map((c) => (
          <option key={choiceValue(c.sort)} value={choiceValue(c.sort)} className="bg-white text-slate-900 dark:bg-slate-900 dark:text-slate-100">
            {c.label}
          </option>
        ))}
      </select>
      <svg viewBox="0 0 12 12" aria-hidden className="pointer-events-none absolute right-0 size-3 text-slate-400">
        <path d="M3 4.5l3 3 3-3" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </label>
  );
}
