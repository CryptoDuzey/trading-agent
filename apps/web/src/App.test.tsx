import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("Trading Agent chat", () => {
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
      model: "deepseek-v4-flash",
    });
  });

  it("streams the assistant reply after tool calls", async () => {
    const stream = new ReadableStream({
      start(controller) {
        const encoder = new TextEncoder();
        controller.enqueue(
          encoder.encode(
            'event: agent_event\ndata: {"type":"tool_started","run_id":"run-1","sequence":2,"step":1,"data":{"name":"get_market_quote"}}\n\n',
          ),
        );
        controller.enqueue(
          encoder.encode(
            'event: agent_event\ndata: {"type":"tool_finished","run_id":"run-1","sequence":3,"step":1,"data":{"name":"get_market_quote","ok":true}}\n\n',
          ),
        );
        controller.enqueue(
          encoder.encode('event: delta\ndata: {"content":"BTC 行情已读取"}\n\n'),
        );
        controller.enqueue(encoder.encode('event: done\ndata: {}\n\n'));
        controller.close();
      },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(stream, { status: 200 }),
    );

    render(<App />);
    fireEvent.change(screen.getByLabelText("交易问题"), {
      target: { value: "查询 BTC" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));

    expect(await screen.findByText("BTC 行情已读取")).toBeInTheDocument();
  });

  it("loads monitoring tasks and can pause an active task", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([
            {
              id: "11111111-1111-1111-1111-111111111111",
              owner_id: "owner",
              market: "spot",
              symbol: "BTCUSDT",
              condition: "price_below",
              threshold: "65000",
              status: "active",
              notification_channel: "site",
              trigger_count: 0,
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "11111111-1111-1111-1111-111111111111",
            owner_id: "owner",
            market: "spot",
            symbol: "BTCUSDT",
            condition: "price_below",
            threshold: "65000",
            status: "paused",
            notification_channel: "site",
            trigger_count: 0,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "打开任务面板" }));

    expect(await screen.findByText("BTCUSDT")).toBeInTheDocument();
    expect(screen.getByText("价格低于 65000")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "暂停 BTCUSDT" }));

    await waitFor(() => {
      expect(screen.getByText("已暂停")).toBeInTheDocument();
    });
    expect(vi.mocked(fetch).mock.calls[0][0]).toContain(
      "/api/alerts?owner_id=",
    );
    expect(vi.mocked(fetch).mock.calls[1][0]).toContain("/pause?owner_id=");
  });
});
