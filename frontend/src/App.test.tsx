import { focusManager, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { makeQueryClient } from "./queryClient";

const status = {
  engine: null,
  provider: "simulated",
  upstox_token_set: false,
  upstox_token_expires_on: null,
  upstox_token_days_left: null,
  channels: { TELEGRAM: false, WHATSAPP: false },
  alerts: { active: 0, triggered: 0, fired_today: 0 },
};

/** Fake backend: the session lives in `server.signedIn`, like the real httpOnly cookie. */
function mockServer() {
  const server = { signedIn: true };
  const json = (code: number, body: unknown) =>
    new Response(code === 204 ? null : JSON.stringify(body), {
      status: code,
      headers: { "Content-Type": "application/json" },
    });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/auth/logout") {
        server.signedIn = false;
        return json(204, null);
      }
      if (!server.signedIn) return json(401, { detail: "Not signed in" });
      if (url === "/api/auth/me") return json(200, { username: "admin" });
      if (url === "/api/system/status") return json(200, status);
      throw new Error(`unexpected ${init?.method ?? "GET"} ${url}`);
    }),
  );
  return server;
}

function renderApp() {
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={["/settings"]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("session handling", () => {
  it("returns to the login page after signing out", async () => {
    mockServer();
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByText("Not signed in")).not.toBeInTheDocument();
  });

  it("returns to the login page when the session expires mid-use", async () => {
    const server = mockServer();
    renderApp();
    await screen.findByText("Settings & status");
    server.signedIn = false; // cookie expired server-side
    act(() => {
      focusManager.setFocused(false);
      focusManager.setFocused(true); // refetch on focus -> the status query now gets a 401
    });
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });
});
