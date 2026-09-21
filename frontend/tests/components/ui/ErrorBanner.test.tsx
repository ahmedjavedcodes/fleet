import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ErrorBanner } from "@/components/ui/ErrorBanner";

describe("ErrorBanner", () => {
  it("renders the given message", () => {
    render(<ErrorBanner message="Could not reach the server." />);
    expect(screen.getByText("Could not reach the server.")).toBeInTheDocument();
  });

  it("does not render a Retry button when onRetry is omitted", () => {
    render(<ErrorBanner message="Failed" />);
    expect(screen.queryByText("Retry")).not.toBeInTheDocument();
  });

  it("calls onRetry when the Retry button is clicked", async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();
    render(<ErrorBanner message="Failed" onRetry={onRetry} />);
    await user.click(screen.getByText("Retry"));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("dismisses itself when the close button is clicked", async () => {
    const user = userEvent.setup();
    render(<ErrorBanner message="Failed" />);
    expect(screen.getByText("Failed")).toBeInTheDocument();
    await user.click(screen.getByLabelText("Dismiss"));
    expect(screen.queryByText("Failed")).not.toBeInTheDocument();
  });
});
