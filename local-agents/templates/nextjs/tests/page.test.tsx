import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import Home from "../src/app/page";

describe("Home page", () => {
  it("renders the project name heading", () => {
    render(<Home />);
    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
  });

  it("renders the API link", () => {
    render(<Home />);
    const apiLink = screen.getByRole("link", { name: /try the api/i });
    expect(apiLink).toHaveAttribute("href", "/api/hello");
  });

  it("renders the documentation link", () => {
    render(<Home />);
    const docsLink = screen.getByRole("link", { name: /documentation/i });
    expect(docsLink).toHaveAttribute("href", "https://nextjs.org/docs");
  });
});
