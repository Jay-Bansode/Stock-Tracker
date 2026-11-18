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
      if (url === "/api/auth/me")
        return json(200, { id: 1, username: "admin", email: "admin@example.com", is_admin: true, telegram_linked: false });
      if (url === "/api/system/status") return json(200, status);
      throw new Error(`unexpected ${init?.method ?? "GET"} ${url}`);
    }),
  );
  return server;
}

function renderApp(path = "/settings") {
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
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

describe("signed-out pages", () => {
  it("links from sign-in to registration and password reset", async () => {
    mockServer().signedIn = false;
    renderApp("/login");
    fireEvent.click(await screen.findByRole("link", { name: "Create an account" }));
    expect(await screen.findByRole("button", { name: "Create account" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Sign in" }));
    fireEvent.click(await screen.findByRole("link", { name: "Forgot password?" }));
    expect(await screen.findByRole("button", { name: "Send reset link" })).toBeInTheDocument();
  });

  it("shows the new-password form for a reset link", async () => {
    mockServer().signedIn = false;
    renderApp("/reset-password?token=abc");
    expect(await screen.findByRole("button", { name: "Set new password" })).toBeInTheDocument();
  });

  it("shows the account and Telegram cards in settings", async () => {
    mockServer();
    renderApp();
    expect(await screen.findByText("admin@example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect Telegram" })).toBeInTheDocument();
  });
});
