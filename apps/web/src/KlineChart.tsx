import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, CandlestickChart, LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  CandlestickChart,
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  CanvasRenderer,
]);

export type Candle = {
  open_time: number;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
};

function calcRsi(closes: number[], period = 14): (number | null)[] {
  const rsi: (number | null)[] = [];
  let gainSum = 0;
  let lossSum = 0;
  for (let i = 1; i < closes.length; i++) {
    const change = closes[i] - closes[i - 1];
    const gain = Math.max(change, 0);
    const loss = Math.max(-change, 0);
    if (i <= period) {
      gainSum += gain;
      lossSum += loss;
      if (i === period) {
        gainSum /= period;
        lossSum /= period;
        rsi.push(lossSum === 0 ? 100 : 100 - 100 / (1 + gainSum / lossSum));
      } else {
        rsi.push(null);
      }
    } else {
      gainSum = (gainSum * (period - 1) + gain) / period;
      lossSum = (lossSum * (period - 1) + loss) / period;
      rsi.push(lossSum === 0 ? 100 : 100 - 100 / (1 + gainSum / lossSum));
    }
  }
  rsi.unshift(null);
  return rsi;
}

function KlineChart({ candles }: { candles: Candle[] }) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!ref.current || candles.length === 0) return;
    const chart = echarts.init(ref.current);

    const dates = candles.map((candle) =>
      new Date(candle.open_time).toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }),
    );
    const kline = candles.map((candle) => [
      Number(candle.open),
      Number(candle.close),
      Number(candle.low),
      Number(candle.high),
    ]);
    const closes = candles.map((candle) => Number(candle.close));
    const ma20 = closes.map((_, index) => {
      if (index < 19) return null;
      const window = closes.slice(index - 19, index + 1);
      return Number(
        (window.reduce((sum, value) => sum + value, 0) / 20).toFixed(4),
      );
    });
    const volumes = candles.map((candle) => ({
      value: Number(candle.volume),
      itemStyle: {
        color:
          Number(candle.close) >= Number(candle.open)
            ? "rgba(34, 197, 94, 0.6)"
            : "rgba(239, 68, 68, 0.6)",
      },
    }));
    const rsi = calcRsi(closes, 14);

    chart.setOption({
      animation: false,
      backgroundColor: "transparent",
      grid: [
        { left: 52, right: 12, top: 10, height: "48%" },
        { left: 52, right: 12, top: "62%", height: "13%" },
        { left: 52, right: 12, top: "79%", height: "15%" },
      ],
      xAxis: [
        {
          type: "category",
          data: dates,
          gridIndex: 0,
          axisLine: { lineStyle: { color: "#e5e7eb" } },
          axisLabel: { color: "#9aa2ad", fontSize: 10 },
        },
        {
          type: "category",
          data: dates,
          gridIndex: 1,
          axisLabel: { show: false },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        {
          type: "category",
          data: dates,
          gridIndex: 2,
          axisLabel: { show: false },
          axisLine: { show: false },
          axisTick: { show: false },
        },
      ],
      yAxis: [
        {
          scale: true,
          gridIndex: 0,
          axisLine: { show: false },
          axisLabel: { color: "#9aa2ad", fontSize: 10 },
          splitLine: { lineStyle: { color: "#f1f3f5" } },
        },
        {
          gridIndex: 1,
          axisLabel: { show: false },
          axisLine: { show: false },
          axisTick: { show: false },
          splitLine: { show: false },
        },
        {
          gridIndex: 2,
          min: 0,
          max: 100,
          axisLabel: { color: "#9aa2ad", fontSize: 9 },
          axisLine: { show: false },
          splitLine: { lineStyle: { color: "#f1f3f5" } },
        },
      ],
      series: [
        {
          type: "candlestick",
          data: kline,
          itemStyle: {
            color: "#22c55e",
            color0: "#ef4444",
            borderColor: "#22c55e",
            borderColor0: "#ef4444",
          },
        },
        {
          type: "line",
          data: ma20,
          showSymbol: false,
          lineStyle: { width: 1, color: "#4176e6" },
          name: "MA20",
        },
        {
          type: "bar",
          data: volumes,
          xAxisIndex: 1,
          yAxisIndex: 1,
        },
        {
          type: "line",
          data: rsi,
          showSymbol: false,
          xAxisIndex: 2,
          yAxisIndex: 2,
          lineStyle: { width: 1, color: "#b7791f" },
          name: "RSI14",
        },
      ],
    });

    const handleResize = () => chart.resize();
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      chart.dispose();
    };
  }, [candles]);

  return <div ref={ref} className="kline-chart" />;
}

export default KlineChart;
