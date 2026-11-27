import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConfirmProvider, useConfirm, type ConfirmOptions } from "./ConfirmDialog";

/** Renders a button that opens the dialog and records what the promise resolved to. */
function setup(options: ConfirmOptions = { title: "Delete it?", message: "Gone for good.", confirmLabel: "Delete", danger: true }) {
  const results: boolean[] = [];
  function Opener() {
    const confirm = useConfirm();
    return <button onClick={async () => results.push(await confirm(options))}>open</button>;
  }
  render(
    <ConfirmProvider>
      <Opener />
    </ConfirmProvider>,
  );
  const open = () => {
    fireEvent.click(screen.getByRole("button", { name: "open" }));
    return screen.getByRole("alertdialog", { name: options.title });
  };
  return { results, open };
}

const settle = () => act(async () => {}); // let the awaited promise resolve

describe("ConfirmDialog", () => {
  it("resolves true on confirm", async () => {
    const { results, open } = setup();
    const dialog = open();
    expect(dialog).toHaveTextContent("Gone for good.");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await settle();
    expect(results).toEqual([true]);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("resolves false on Cancel, Escape and a backdrop click", async () => {
    const { results, open } = setup();
    open();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await settle();
    const dialog = open();
    fireEvent.keyDown(dialog, { key: "Escape" });
    await settle();
    open();
    fireEvent.click(screen.getByTestId("confirm-backdrop"));
    await settle();
    expect(results).toEqual([false, false, false]);
  });

  it("starts on Cancel and keeps Tab inside the dialog", () => {
    const { open } = setup();
    const dialog = open();
    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(cancel).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(screen.getByRole("button", { name: "Delete" })).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(cancel).toHaveFocus();
  });
});
