import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AlertForm } from "./AlertForm";

describe("AlertForm", () => {
  it("submits a rounded target and warns when the price already meets it", () => {
    const onSubmit = vi.fn();
    render(<AlertForm ltp={1502} onSubmit={onSubmit} onCancel={() => {}} />);

    const target = screen.getByLabelText(/Target price/);
    fireEvent.change(target, { target: { value: "1500.004" } });
    expect(screen.getByText(/already at or above ₹1,500/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add alert" }));
    expect(onSubmit).toHaveBeenCalledWith({
      condition: "ABOVE",
      target_price: 1500,
      trigger_mode: "ONCE",
      rearm_pct: 0.5,
      cooldown_sec: 900,
      note: null,
    });
  });

  it("does not warn for a BELOW target under the current price", () => {
    render(<AlertForm ltp={1502} onSubmit={() => {}} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText(/Alert when price is/), { target: { value: "BELOW" } });
    fireEvent.change(screen.getByLabelText(/Target price/), { target: { value: "1480" } });
    expect(screen.queryByText(/already/)).not.toBeInTheDocument();
  });

  it("shows re-arm options only for repeating alerts", () => {
    render(<AlertForm onSubmit={() => {}} onCancel={() => {}} />);
    expect(screen.queryByLabelText(/Re-arm band/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Repeat/), { target: { value: "REPEAT" } });
    expect(screen.getByLabelText(/Re-arm band/)).toBeInTheDocument();
  });
});
