"use client";
import { useEffect, useState } from "react";
import { getDashboardLogs, getDashboardMetrics, getDashboardSessions } from "../lib/api";
import type { DashboardLog, DashboardMetrics, DashboardSession } from "../lib/types";

function when(value?: string | null) {
  return value ? new Date(value).toLocaleString() : "—";
}

export default function DashboardPanel({ onClose, onOpenSession }: { onClose: () => void; onOpenSession: (conversationId: string) => void }) {
  const [sessions, setSessions] = useState<DashboardSession[]>([]);
  const [logs, setLogs] = useState<DashboardLog[]>([]);
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true); setError("");
    try {
      const [nextSessions, nextLogs, nextMetrics] = await Promise.all([getDashboardSessions(), getDashboardLogs(), getDashboardMetrics()]);
      setSessions(nextSessions); setLogs(nextLogs); setMetrics(nextMetrics);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  }
  useEffect(() => { refresh(); }, []);

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/75 p-4 backdrop-blur-sm">
      <section className="mx-auto flex h-[90vh] max-w-6xl flex-col overflow-hidden rounded-2xl border border-slate-700 bg-slate-950 shadow-2xl">
        <header className="flex items-center gap-3 border-b border-slate-800 p-4">
          <div className="flex-1"><h2 className="font-semibold">Operations dashboard</h2><p className="text-xs text-slate-400">Persistent sessions and request audit log</p></div>
          <button onClick={refresh} className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs hover:bg-slate-800">Refresh</button>
          <button onClick={onClose} className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs hover:bg-slate-800">Close</button>
        </header>
        {loading && <p className="p-4 text-sm text-slate-400">Loading dashboard…</p>}
        {error && <p className="m-4 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-200">{error}</p>}
        {!loading && !error && <div className="flex flex-1 flex-col gap-4 overflow-auto p-4">
          {metrics && <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <Metric label="Requests" value={metrics.window_requests} detail={`latest ${metrics.window_size}`} />
            <Metric label="Failures" value={metrics.failed_requests} detail={`${(metrics.failure_rate * 100).toFixed(1)}% rate`} danger={metrics.failed_requests > 0} />
            <Metric label="Successes" value={metrics.successful_requests} detail="audited requests" />
            <Metric label="Avg latency" value={formatMs(metrics.avg_latency_ms)} detail="completed requests" />
            <Metric label="p95 latency" value={formatMs(metrics.p95_latency_ms)} detail="nearest-rank p95" />
          </section>}
          {metrics && <p className="text-xs text-slate-400">Workflow outcomes: {Object.entries(metrics.classification_counts).map(([name, count]) => `${name}: ${count}`).join(" · ") || "no requests yet"}</p>}
          <div className="grid flex-1 gap-4 overflow-auto lg:grid-cols-3">
          <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-3 lg:col-span-1">
            <h3 className="mb-2 text-sm font-semibold">Recent sessions ({sessions.length})</h3>
            <div className="space-y-2">{sessions.map((s) => <button key={s.conversation_id} onClick={() => onOpenSession(s.conversation_id)} className="w-full rounded-lg bg-slate-800/70 p-2 text-left text-xs hover:bg-slate-700">
              <p className="truncate font-mono text-sky-200">{s.conversation_id}</p><p className="mt-1 text-slate-400">{s.message_count} messages · {when(s.updated_at)}</p>
            </button>)}{!sessions.length && <p className="text-xs text-slate-500">No saved sessions yet.</p>}</div>
          </section>
          <section className="overflow-auto rounded-xl border border-slate-800 bg-slate-900/50 p-3 lg:col-span-2">
            <h3 className="mb-2 text-sm font-semibold">Recent requests ({logs.length})</h3>
            <table className="w-full text-left text-xs"><thead className="text-slate-400"><tr><th className="pb-2">Time</th><th className="pb-2">Request</th><th className="pb-2">Class</th><th className="pb-2">Rows</th><th className="pb-2">Latency</th><th className="pb-2">Status</th></tr></thead>
              <tbody>{logs.map((l) => <tr key={l.log_id} className="border-t border-slate-800"><td className="py-2 pr-2 whitespace-nowrap text-slate-400">{when(l.created_at)}</td><td className="max-w-[260px] truncate py-2 pr-2" title={l.request_text}>{l.request_text}</td><td className="py-2 pr-2">{l.classification || "—"}</td><td className="py-2 pr-2">{l.row_count ?? "—"}</td><td className="py-2 pr-2">{l.latency_ms ?? "—"}ms</td><td className={`py-2 ${l.status === "ok" ? "text-emerald-300" : "text-red-300"}`}>{l.status}</td></tr>)}</tbody>
            </table>{!logs.length && <p className="text-xs text-slate-500">No request logs yet.</p>}
          </section>
          </div>
        </div>}
      </section>
    </div>
  );
}

function formatMs(value: number | null) {
  return value === null ? "—" : `${Math.round(value)}ms`;
}

function Metric({ label, value, detail, danger = false }: { label: string; value: string | number; detail: string; danger?: boolean }) {
  return <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3">
    <p className="text-xs text-slate-400">{label}</p>
    <p className={`mt-1 text-xl font-semibold ${danger ? "text-red-300" : "text-sky-200"}`}>{value}</p>
    <p className="mt-1 text-[11px] text-slate-500">{detail}</p>
  </div>;
}
