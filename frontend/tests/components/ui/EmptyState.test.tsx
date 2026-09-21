import { render, screen } from "@testing-library/react";
import { Fuel } from "lucide-react";
import { describe, expect, it } from "vitest";

import { EmptyState } from "@/components/ui/EmptyState";

describe("EmptyState", () => {
  it("renders the title", () => {
    render(<EmptyState title="No fuel logs yet" />);
    expect(screen.getByText("No fuel logs yet")).toBeInTheDocument();
  });

  it("renders the description when provided", () => {
    render(<EmptyState title="No fuel logs yet" description="Add your first entry to get started." />);
    expect(screen.getByText("Add your first entry to get started.")).toBeInTheDocument();
  });

  it("omits the description paragraph when none is provided", () => {
    const { container } = render(<EmptyState title="No fuel logs yet" />);
    expect(container.querySelectorAll("p")).toHaveLength(1);
  });

  it("renders a custom action node", () => {
    render(<EmptyState title="No fuel logs yet" action={<button>Add entry</button>} />);
    expect(screen.getByRole("button", { name: "Add entry" })).toBeInTheDocument();
  });

  it("accepts a custom icon without crashing", () => {
    render(<EmptyState title="No fuel logs yet" icon={Fuel} />);
    expect(screen.getByText("No fuel logs yet")).toBeInTheDocument();
  });
});
