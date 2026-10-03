"use client";
import { useState } from "react";
import type { ChatMessage } from "../lib/types";
import { postClarify } from "../lib/api";

export default function ClarificationCard({ msg, conversationId, onResolved }: {
  msg: ChatMessage; conversationId: string; onResolved: (m: ChatMessage) => void;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    if (!draft.trim() || busy) return;
    setBusy(true); setErr(null);
    try {
      const r = await postClarify(conversationId, draft.trim());
      onResolved({
        id: `a-${Date.now()}`, role: "assistant", content: r.answer,
        classification: r.classification, sql: r.sql, columns: r.columns,
        rows: r.rows, rowCount: r.row_count, truncated: r.truncated, chart: r.chart,
        clarificationQuestions: r.clarification_questions, selectedTables: r.selected_tables,
        validationError: r.validation_error, view: "chart",
      });
      setDraft("");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  return (
    <div className="mt-2 rounded-xl border border-amber-400/40 bg-amber-400/10 p-3">
      <p className="text-sm font-semibold text-amber-200">Need clarification — no query was run yet</p>
      <ul className="mt-1 list-disc pl-5 text-sm text-amber-100/90">
        {(msg.clarificationQuestions || []).map((q, i) => <li key={i}>{q}</li>)}
      </ul>
      <div className="mt-2 flex gap-2">
        <input value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder="e.g. Top 5 by revenue for 2024-01-01 to 2024-12-31, grouped by month"
          className="flex-1 rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-amber-300" />
        <button onClick={submit} disabled={busy || !draft.trim()}
          className="rounded-lg bg-amber-400 px-3 py-2 text-sm font-semibold text-slate-900 disabled:opacity-50">
          {busy ? "…" : "Answer"}
        </button>
      </div>
      {err && <p className="mt-1 text-xs text-red-300">{err}</p>}
      <div className="mt-2 flex flex-wrap gap-1">
        {["Top 5 by revenue in 2024", "Last 30 days, grouped by month", "By product category"].map((s) => (
          <button key={s} onClick={() => setDraft(s)}
            className="rounded-full border border-amber-300/40 px-2 py-0.5 text-xs text-amber-100 hover:bg-amber-300/20">{s}</button>
        ))}
      </div>
    </div>
  );
}
