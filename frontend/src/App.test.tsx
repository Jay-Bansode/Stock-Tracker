import { focusManager, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { ConfirmProvider } from "./components/ConfirmDialog";
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

const me = { id: 1, username: "admin", email: "admin@example.com", is_admin: true, telegram_linked: false };

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
      if (url === "/api/auth/login") {
        server.signedIn = true;
        return json(200, me);
      }
      if (!server.signedIn) return json(401, { detail: "Not signed in" });
      if (url === "/api/auth/me") return json(200, me);
      if (url === "/api/system/status") return json(200, status);
      throw new Error(`unexpected ${init?.method ?? "GET"} ${url}`);
    }),
  );
  return server;
}

function CurrentPath() {
  return <output data-testid="path">{useLocation().pathname}</output>;
}

function renderApp(path = "/settings") {
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <ConfirmProvider>
          <App />
          <CurrentPath />
        </ConfirmProvider>
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
    const dialog = screen.getByRole("alertdialog", { name: "Sign out?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByText("Not signed in")).not.toBeInTheDocument();
    // a background refresh may show the form a moment before the redirect lands
    await waitFor(() => expect(screen.getByTestId("path")).toHaveTextContent("/login"));

    // signing straight back in opens the app
    fireEvent.change(screen.getByLabelText("Username or email"), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("button", { name: "Sign out" })).toBeInTheDocument();
    // the redirect from /login runs in an effect right after that render
    await waitFor(() => expect(screen.getByTestId("path")).toHaveTextContent("/watchlists"));
  });

  it("stays signed in when sign-out is cancelled", async () => {
    const server = mockServer();
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    const dialog = screen.getByRole("alertdialog", { name: "Sign out?" });
    expect(dialog).toHaveTextContent("You're signed in as admin");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(server.signedIn).toBe(true); // no /api/auth/logout call
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
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
    expect(screen.getByTestId("path")).toHaveTextContent("/settings"); // back here after sign-in
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
