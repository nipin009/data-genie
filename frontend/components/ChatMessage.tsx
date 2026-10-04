"use client";
import type { ChatMessage } from "../lib/types";
import ChartView from "./ChartView";

export default function ChatMessageView({ msg, conversationId, onResolved, onSwitchView }: {
  msg: ChatMessage; conversationId: string;
  onResolved: (m: ChatMessage) => void; onSwitchView: (id: string, v: "chart" | "table") => void;
}) {
  if (msg.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-sky-600 px-4 py-2 text-sm">{msg.content}</div>
      </div>
    );
  }
  const showChart = (msg.rows?.length || 0) > 0 && msg.columns?.length &&
    ["bar", "line", "pie"].includes(msg.chart?.type || "");
  return (
    <div className="flex justify-start">
      <div className="max-w-[94%]">
        <p className="whitespace-pre-wrap text-sm leading-7 text-slate-100">{msg.content}</p>
        {showChart && <ChartView chartType={msg.chart?.type || "bar"} x={msg.chart?.x} y={msg.chart?.y} columns={msg.columns || []} rows={msg.rows || []} />}
      </div>
    </div>
  );
}
