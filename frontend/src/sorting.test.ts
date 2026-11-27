import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { nextSort, sortRows, useSort, type SortColumns } from "./sorting";

type Row = { name: string; price: number | null };
const rows: Row[] = [
  { name: "Stock 10", price: 50 },
  { name: "stock 2", price: null },
  { name: "Alpha", price: 200 },
  { name: "Beta", price: 50 },
];
const columns: SortColumns<Row, "name" | "price"> = {
  name: { value: (r) => r.name },
  price: { value: (r) => r.price, first: "desc" },
};
const names = (rs: Row[]) => rs.map((r) => r.name);

afterEach(() => localStorage.clear());

describe("sortRows", () => {
  it("keeps the natural order when there is no sort", () => {
    expect(names(sortRows(rows, null, columns))).toEqual(names(rows));
  });

  it("sorts text naturally and ignores case", () => {
    expect(names(sortRows(rows, { key: "name", dir: "asc" }, columns))).toEqual(["Alpha", "Beta", "stock 2", "Stock 10"]);
  });

  it("sorts numbers, keeps ties in their original order, and puts empty values last both ways", () => {
    expect(names(sortRows(rows, { key: "price", dir: "desc" }, columns))).toEqual(["Alpha", "Stock 10", "Beta", "stock 2"]);
    expect(names(sortRows(rows, { key: "price", dir: "asc" }, columns))).toEqual(["Stock 10", "Beta", "Alpha", "stock 2"]);
  });

  it("does not modify the input", () => {
    const copy = [...rows];
    sortRows(rows, { key: "name", dir: "asc" }, columns);
    expect(rows).toEqual(copy);
  });
});

describe("nextSort", () => {
  it("cycles first direction -> reverse -> off, and starts over on another column", () => {
    const a = nextSort(null, "price", "desc");
    expect(a).toEqual({ key: "price", dir: "desc" });
    const b = nextSort(a, "price", "desc");
    expect(b).toEqual({ key: "price", dir: "asc" });
    expect(nextSort(b, "price", "desc")).toBeNull();
    expect(nextSort(b, "name", "asc")).toEqual({ key: "name", dir: "asc" });
  });
});

describe("useSort", () => {
  it("remembers the sort in this browser and restores it", () => {
    const first = renderHook(() => useSort("test-page", columns));
    act(() => first.result.current.toggle("price"));
    expect(first.result.current.sort).toEqual({ key: "price", dir: "desc" });
    expect(JSON.parse(localStorage.getItem("tracker.sort.test-page")!)).toEqual({ key: "price", dir: "desc" });

    const again = renderHook(() => useSort("test-page", columns));
    expect(again.result.current.sort).toEqual({ key: "price", dir: "desc" });

    act(() => again.result.current.set(null));
    expect(localStorage.getItem("tracker.sort.test-page")).toBeNull();
  });

  it("ignores stored junk or columns that no longer exist", () => {
    localStorage.setItem("tracker.sort.test-page", "{not json");
    expect(renderHook(() => useSort("test-page", columns)).result.current.sort).toBeNull();
    localStorage.setItem("tracker.sort.test-page", JSON.stringify({ key: "gone", dir: "asc" }));
    expect(renderHook(() => useSort("test-page", columns)).result.current.sort).toBeNull();
  });
});
