import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import App from "../src/App";
import { useCounterStore } from "../src/store/counter";

// Reset store between tests
beforeEach(() => {
  useCounterStore.setState({ count: 0 });
});

describe("App", () => {
  it("renders project name heading", () => {
    render(<App />);
    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
  });

  it("shows initial count of 0", () => {
    render(<App />);
    expect(screen.getByText("0")).toBeInTheDocument();
  });

  it("increments count on + click", () => {
    render(<App />);
    fireEvent.click(screen.getByText("+"));
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("decrements count on - click", () => {
    render(<App />);
    fireEvent.click(screen.getByText("+"));
    fireEvent.click(screen.getByText("+"));
    fireEvent.click(screen.getByText("-"));
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("resets count to 0", () => {
    render(<App />);
    fireEvent.click(screen.getByText("+"));
    fireEvent.click(screen.getByText("+"));
    fireEvent.click(screen.getByText("Reset"));
    expect(screen.getByText("0")).toBeInTheDocument();
  });
});
