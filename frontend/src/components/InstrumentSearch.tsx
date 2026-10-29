import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Instrument } from "../types";

function useDebounced<T>(value: T, ms: number) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function InstrumentSearch({
  onSelect,
  existing,
  disabled,
}: {
  onSelect: (i: Instrument) => void;
  existing: Set<string>;
  disabled?: boolean;
}) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const debounced = useDebounced(q.trim(), 200);
  const box = useRef<HTMLDivElement>(null);

  const { data = [], isFetching } = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => api.search(debounced),
    enabled: debounced.length >= 1,
    staleTime: 60_000,
  });

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const pick = (i: Instrument) => {
    if (existing.has(i.instrument_key)) return;
    onSelect(i);
    setQ("");
    setOpen(false);
  };

  return (
    <div ref={box} className="relative w-full max-w-md">
      <input
        className="input"
        placeholder="Add stock: search symbol or company (e.g. RELIANCE)"
        value={q}
        disabled={disabled}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
          setActive(0);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (!open || !data.length) return;
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((a) => Math.min(a + 1, data.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((a) => Math.max(a - 1, 0));
          } else if (e.key === "Enter") {
            e.preventDefault();
            pick(data[active]);
          } else if (e.key === "Escape") setOpen(false);
        }}
        role="combobox"
        aria-expanded={open}
        aria-controls="instrument-results"
      />
      {open && debounced && (
        <ul id="instrument-results" role="listbox" className="card absolute z-30 mt-1 max-h-80 w-full overflow-auto py-1">
          {isFetching && !data.length && <li className="px-3 py-2 text-sm text-slate-500">Searching…</li>}
          {!isFetching && !data.length && <li className="px-3 py-2 text-sm text-slate-500">No matches</li>}
          {data.map((i, idx) => {
            const added = existing.has(i.instrument_key);
            return (
              <li
                key={i.instrument_key}
                role="option"
                aria-selected={idx === active}
                aria-disabled={added}
                onMouseEnter={() => setActive(idx)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(i);
                }}
                className={`flex cursor-pointer items-center justify-between gap-3 px-3 py-2 text-sm ${
                  idx === active ? "bg-slate-100 dark:bg-slate-800" : ""
                } ${added ? "cursor-default opacity-50" : ""}`}
              >
                <span className="min-w-0">
                  <span className="font-medium">{i.trading_symbol}</span>
                  <span className="ml-2 truncate text-slate-500">{i.name}</span>
                </span>
                <span className="shrink-0 text-xs text-slate-500">{added ? "Added" : i.segment.replace("_", " ")}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
