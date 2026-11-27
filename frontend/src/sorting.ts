import { useCallback, useState } from "react";

export type SortDir = "asc" | "desc";
/** null = the page's natural order (e.g. the order stocks were added). */
export type SortState<K extends string> = { key: K; dir: SortDir } | null;

export type SortValue = string | number | null | undefined;

export interface SortColumn<T> {
  value: (row: T) => SortValue;
  /** Direction on the first click: text/dates usually "asc", amounts usually "desc". */
  first?: SortDir;
}

export type SortColumns<T, K extends string> = Record<K, SortColumn<T>>;

const collator = new Intl.Collator("en-IN", { numeric: true, sensitivity: "base" });

const isEmpty = (v: SortValue) => v === null || v === undefined || v === "" || (typeof v === "number" && Number.isNaN(v));

/** Stable sort into a new array. Empty values always go last, whichever the direction. */
export function sortRows<T, K extends string>(rows: readonly T[], sort: SortState<K>, columns: SortColumns<T, K>): T[] {
  if (!sort || !columns[sort.key]) return [...rows];
  const value = columns[sort.key].value;
  const sign = sort.dir === "asc" ? 1 : -1;
  return rows
    .map((row, index) => ({ row, index, v: value(row) }))
    .sort((a, b) => {
      const ae = isEmpty(a.v);
      const be = isEmpty(b.v);
      if (ae || be) return ae && be ? a.index - b.index : ae ? 1 : -1;
      const cmp =
        typeof a.v === "number" && typeof b.v === "number" ? a.v - b.v : collator.compare(String(a.v), String(b.v));
      return cmp ? cmp * sign : a.index - b.index;
    })
    .map((x) => x.row);
}

/** Click cycle for a column: first direction → the other → off (natural order). */
export function nextSort<K extends string>(sort: SortState<K>, key: K, first: SortDir = "asc"): SortState<K> {
  if (!sort || sort.key !== key) return { key, dir: first };
  if (sort.dir === first) return { key, dir: first === "asc" ? "desc" : "asc" };
  return null;
}

function read<K extends string>(storageKey: string, keys: readonly K[]): SortState<K> {
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { key?: unknown; dir?: unknown };
    if (keys.includes(parsed.key as K) && (parsed.dir === "asc" || parsed.dir === "desc")) {
      return { key: parsed.key as K, dir: parsed.dir };
    }
  } catch {
    /* blocked storage or bad JSON: fall back to the natural order */
  }
  return null;
}

function write<K extends string>(storageKey: string, sort: SortState<K>) {
  try {
    if (sort) localStorage.setItem(storageKey, JSON.stringify(sort));
    else localStorage.removeItem(storageKey);
  } catch {
    /* storage unavailable: the sort just isn't remembered */
  }
}

/** Sort state for one page, remembered in this browser under `tracker.sort.<page>`. */
export function useSort<T, K extends string>(page: string, columns: SortColumns<T, K>) {
  const storageKey = `tracker.sort.${page}`;
  const keys = Object.keys(columns) as K[];
  const [sort, setSortState] = useState<SortState<K>>(() => read(storageKey, keys));

  const set = useCallback(
    (next: SortState<K>) => {
      setSortState(next);
      write(storageKey, next);
    },
    [storageKey],
  );
  const toggle = (key: K) => set(nextSort(sort, key, columns[key].first));

  return { sort, set, toggle };
}
