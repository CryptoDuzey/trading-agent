import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

describe("Day 0 application shell", () => {
  it("shows the project name and the next learning task", async () => {
    const modulePath = "./App";

    try {
      const { default: App } = await import(/* @vite-ignore */ modulePath);
      render(<App />);
    } catch {
      expect.fail("App 组件尚未实现");
    }

    expect(
      screen.getByRole("heading", { name: "Lobster Trading Agent" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Day 1：亲手完成对话界面")).toBeInTheDocument();
  });
});

