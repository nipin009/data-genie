"use client";
import type { ChatMessage } from "../lib/types";
import { downloadCsv } from "../lib/api";
import ClarificationCard from "./ClarificationCard";
import SqlPreview from "./SqlPreview";
import QueryDetails from "./QueryDetails";
import ChartView from "./ChartView";
import DataTable from "./DataTable";
import SchemaExplorer from "./SchemaExplorer";

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
  const badge =
    msg.classification === "ambiguous" ? "bg-amber-400/20 text-amber-200" :
    msg.classification === "unsupported" || msg.classification === "unrelated" ? "bg-red-400/20 text-red-200" :
    "bg-emerald-400/20 text-emerald-200";
  const showViz = (msg.rows?.length || 0) > 0 && msg.columns?.length;
  const showSchemaExplorer = msg.classification === "schema_request" && msg.content.startsWith("Schema for each available table:");
  return (
    <div className="flex justify-start">
      <div className="max-w-[95%] w-full rounded-2xl rounded-bl-sm border border-slate-800 bg-slate-900 px-4 py-3">
        {msg.classification && <span className={`mb-1 inline-block rounded-full px-2 py-0.5 text-[11px] ${badge}`}>{msg.classification}</span>}
        {showSchemaExplorer ? (
          <p className="text-sm leading-relaxed">Here’s the connected database schema. Search or expand a table to inspect it.</p>
        ) : <p className="whitespace-pre-wrap text-sm leading-relaxed">{msg.content}</p>}
        {showSchemaExplorer && <SchemaExplorer />}

        {msg.classification === "ambiguous" && (msg.clarificationQuestions?.length || 0) > 0 && (
          <ClarificationCard msg={msg} conversationId={conversationId} onResolved={onResolved} />
        )}

        {showViz ? (
          <>
            <div className="mt-2 flex items-center gap-2 text-xs">
              <div className="inline-flex rounded-lg border border-slate-700 p-0.5">
                {(["chart", "table"] as const).map((v) => (
                  <button key={v} onClick={() => onSwitchView(msg.id, v)}
                    className={`rounded-md px-2 py-0.5 capitalize ${msg.view === v || (!msg.view && v === "chart") ? "bg-slate-700 text-white" : "text-slate-400"}`}>
                    {v === "chart" ? `Chart (${msg.chart?.type || "table"})` : "Data table"}
                  </button>
                ))}
              </div>
              <span className="flex-1" />
              <button onClick={() => downloadCsv(msg.columns || [], msg.rows || [])} className="text-slate-400 hover:text-white">⬇ CSV</button>
            </div>
            {(msg.view || "chart") === "chart" && msg.chart?.type !== "table" && msg.chart?.type !== "none" ? (
              <ChartView chartType={msg.chart?.type || "bar"} x={msg.chart?.x} y={msg.chart?.y} columns={msg.columns || []} rows={msg.rows || []} />
            ) : null}
            {(msg.view === "table" || msg.chart?.type === "table") && (
              <DataTable columns={msg.columns || []} rows={msg.rows || []} />
            )}
            {(msg.view || "chart") === "chart" && (msg.chart?.type === "table" || !msg.chart?.type) && !(msg.view === "table") ? (
              <DataTable columns={msg.columns || []} rows={msg.rows || []} />
            ) : null}
          </>
        ) : null}

        <SqlPreview sql={msg.sql} />
        <QueryDetails tables={msg.selectedTables} chartReason={msg.chart?.reason} rowCount={msg.rowCount} truncated={msg.truncated} validationError={msg.validationError} />
      </div>
    </div>
  );
}
