import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Lobster Trading Agent chat", () => {
  it("does not allow an empty message to be sent", () => {
    render(<App />);

    const sendButton = screen.getByRole("button", { name: "发送消息" });
    expect(sendButton).toBeDisabled();

    fireEvent.change(screen.getByLabelText("交易问题"), {
      target: { value: "   " },
    });

    expect(sendButton).toBeDisabled();
  });

  it("shows the user message and streams the assistant reply", async () => {
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            'event: delta\ndata: {"content":"正在检查 BTC 行情"}\n\n',
          ),
        );
        controller.enqueue(
          new TextEncoder().encode('event: done\ndata: {}\n\n'),
        );
        controller.close();
      },
    });

    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(stream, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );

    render(<App />);

    fireEvent.change(screen.getByLabelText("交易问题"), {
      target: { value: "分析 BTC" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));

    expect(screen.getByText("分析 BTC")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "正在发送" })).toBeDisabled();

    await waitFor(() => {
      expect(screen.getByText("正在检查 BTC 行情")).toBeInTheDocument();
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/chat/stream",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }),
    );
    const request = vi.mocked(fetch).mock.calls[0][1];
    const requestBody = JSON.parse(String(request?.body));
    expect(requestBody).toEqual({
      message: "分析 BTC",
      session_id: expect.any(String),
    });
  });
});
