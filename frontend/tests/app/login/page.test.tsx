import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-client";

const loginMock = vi.fn();

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ login: loginMock, logout: vi.fn(), session: null }),
}));

import LoginPage from "@/app/login/page";

beforeEach(() => {
  loginMock.mockReset();
});

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>, overrides: Partial<Record<"org" | "email" | "password", string>> = {}) {
  const { org = "acme-logistics", email = "admin@acme.com", password = "hunter2" } = overrides;
  if (org) await user.type(screen.getByLabelText("Organization slug"), org);
  if (email) await user.type(screen.getByLabelText("Email"), email);
  if (password) await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("LoginPage", () => {
  it("renders the login form fields", () => {
    render(<LoginPage />);
    expect(screen.getByLabelText("Organization slug")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });

  it("shows validation errors and never calls login when the form is empty", async () => {
    const user = userEvent.setup();
    render(<LoginPage />);
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Organization slug is required")).toBeInTheDocument();
    expect(screen.getByText("Enter a valid email address")).toBeInTheDocument();
    expect(screen.getByText("Password is required")).toBeInTheDocument();
    expect(loginMock).not.toHaveBeenCalled();
  });

  it("calls login with the entered credentials on a valid submit", async () => {
    const user = userEvent.setup();
    loginMock.mockResolvedValue(undefined);
    render(<LoginPage />);

    await fillAndSubmit(user);

    await waitFor(() =>
      expect(loginMock).toHaveBeenCalledWith({
        org_slug: "acme-logistics",
        email: "admin@acme.com",
        password: "hunter2",
      }),
    );
  });

  it("shows a generic credentials error when login rejects with 401", async () => {
    const user = userEvent.setup();
    loginMock.mockRejectedValue(new ApiError("unauthorized", "Could not validate credentials", 401));
    render(<LoginPage />);

    await fillAndSubmit(user);

    expect(await screen.findByText("Invalid organization, email, or password.")).toBeInTheDocument();
  });

  it("maps a 422 validation error onto the matching field", async () => {
    const user = userEvent.setup();
    loginMock.mockRejectedValue(
      new ApiError("validation", "Validation failed", 422, { org_slug: "Unknown organization" }),
    );
    render(<LoginPage />);

    await fillAndSubmit(user);

    expect(await screen.findByText("Unknown organization")).toBeInTheDocument();
  });

  it("shows the raw error message for an unexpected server error", async () => {
    const user = userEvent.setup();
    loginMock.mockRejectedValue(new ApiError("server", "Internal Server Error", 500));
    render(<LoginPage />);

    await fillAndSubmit(user);

    expect(await screen.findByText("Internal Server Error")).toBeInTheDocument();
  });
});
