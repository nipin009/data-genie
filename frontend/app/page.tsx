"use client";
import { useEffect, useRef, useState } from "react";
import type { ChatMessage, ChatResponsePayload, HistoryMessagePayload } from "../lib/types";
import { getHistory, postChat, postClarify, streamChat } from "../lib/api";
import ChatMessageView from "../components/ChatMessage";
import DashboardPanel from "../components/DashboardPanel";

const SUGGESTIONS = [
  "Total revenue by product category",
  "Monthly revenue trend for the last 12 months",
  "Top 5 customers by lifetime spend",
  "Show all failed payments",
  "Average product rating by category",
];
const CONVERSATION_STORAGE_KEY = "data_genie_conversation_id";

function toMsg(r: ChatResponsePayload): ChatMessage {
  return {
    id: `a-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`, role: "assistant", content: r.answer,
    classification: r.classification, sql: r.sql, columns: r.columns, rows: r.rows,
    rowCount: r.row_count, truncated: r.truncated, chart: r.chart,
    clarificationQuestions: r.clarification_questions, selectedTables: r.selected_tables,
    validationError: r.validation_error, view: "chart",
  };
}

function historyToMsg(message: HistoryMessagePayload, index: number): ChatMessage {
  const metadata = message.metadata || {};
  if (message.role === "user") return { id: `history-user-${index}`, role: "user", content: message.content };
  return {
    id: `history-assistant-${index}`, role: "assistant", content: message.content,
    classification: metadata.classification, sql: metadata.sql, columns: metadata.columns,
    rows: metadata.rows, rowCount: metadata.row_count, truncated: metadata.truncated,
    chart: metadata.chart, clarificationQuestions: metadata.clarification_questions,
    selectedTables: metadata.selected_tables, validationError: metadata.validation_error, view: "chart",
  };
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [convId, setConvId] = useState<string | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [stage, setStage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [useStream, setUseStream] = useState(true);
  const [dashboardOpen, setDashboardOpen] = useState(false);
  const [clarification, setClarification] = useState<string[]>([]);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, stage]);

  async function loadConversation(conversationId: string) {
    setError(null); setLoading(true); setStage("restoring history");
    try {
      const history = await getHistory(conversationId);
      const restored = history.map(historyToMsg);
      setMessages(restored);
      const latest = restored[restored.length - 1];
      setClarification(latest?.classification === "ambiguous" ? (latest.clarificationQuestions || []) : []);
      setConvId(conversationId);
      localStorage.setItem(CONVERSATION_STORAGE_KEY, conversationId);
      setDashboardOpen(false);
    } catch (e: unknown) {
      localStorage.removeItem(CONVERSATION_STORAGE_KEY);
      setError(e instanceof Error ? e.message : String(e));
    } finally { setLoading(false); setStage(null); }
  }

  useEffect(() => {
    const saved = localStorage.getItem(CONVERSATION_STORAGE_KEY);
    if (saved) void loadConversation(saved);
  }, []);

  async function send(text?: string) {
    const content = (text ?? input).trim();
    if (!content || loading) return;
    setError(null); setLoading(true); setStage(useStream ? "connecting" : "thinking");
    const user: ChatMessage = { id: `u-${Date.now()}`, role: "user", content };
    setMessages((m) => [...m, user]);
    setInput("");
    try {
      if (clarification.length > 0) {
        const r = await postClarify(convId || "", content);
        setMessages((m) => [...m, toMsg(r)]);
        setClarification(r.classification === "ambiguous" ? r.clarification_questions : []);
        setLoading(false); setStage(null);
      } else if (useStream) {
        streamChat(content, convId,
          (s) => setStage(s),
          (payload) => {
            if (payload.conversation_id) { setConvId(payload.conversation_id); localStorage.setItem(CONVERSATION_STORAGE_KEY, payload.conversation_id); }
            setMessages((m) => [...m, toMsg(payload)]);
            setClarification(payload.classification === "ambiguous" ? payload.clarification_questions : []);
            setLoading(false); setStage(null);
          },
          (msg) => { setError(msg); setLoading(false); setStage(null); });
        // conv id unknown until final; store optimistic — server creates if absent
      } else {
        const r = await postChat(content, convId);
        setConvId(r.conversation_id); localStorage.setItem(CONVERSATION_STORAGE_KEY, r.conversation_id);
        setMessages((m) => [...m, toMsg(r)]);
        setClarification(r.classification === "ambiguous" ? r.clarification_questions : []);
        setLoading(false); setStage(null);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setLoading(false); setStage(null);
    }
  }

  return (
    <main className="mx-auto flex h-screen max-w-3xl flex-col px-4">
      <header className="flex items-center gap-3 border-b border-slate-800 py-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-sky-500 font-bold text-slate-950">DG</div>
        <div className="flex-1">
          <h1 className="text-lg font-bold leading-tight">Data Genie — Text-to-SQL</h1>
          <p className="text-xs text-slate-400">Your data assistant</p>
        </div>
        <label className="flex items-center gap-1 text-xs text-slate-400">
          <input type="checkbox" checked={useStream} onChange={(e) => setUseStream(e.target.checked)} /> stream
        </label>
        <button onClick={() => setDashboardOpen(true)} className="rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800">Dashboard</button>
        <button onClick={() => { setMessages([]); setConvId(undefined); localStorage.removeItem(CONVERSATION_STORAGE_KEY); setError(null); }}
          className="rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800">New chat</button>
      </header>

      {messages.length === 0 && (
        <div className="my-auto pb-16">
          <h2 className="text-center text-2xl font-semibold">What would you like to know?</h2>
          <p className="mt-2 text-center text-sm text-slate-400">Ask a question about your connected business data.</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {SUGGESTIONS.map((s) => (
              <button key={s} onClick={() => send(s)} className="rounded-full border border-sky-500/40 px-3 py-1 text-xs text-sky-200 hover:bg-sky-500/20">{s}</button>
            ))}
          </div>
        </div>
      )}

      <div className="flex-1 space-y-5 overflow-y-auto py-6">
        {messages.map((m) => (
          <ChatMessageView key={m.id} msg={m} conversationId={convId || ""}
            onResolved={(nm) => setMessages((prev) => [...prev, nm])}
            onSwitchView={(id, v) => setMessages((prev) => prev.map((x) => x.id === id ? { ...x, view: v } : x))} />
        ))}
        {loading && (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-600 border-t-sky-400" />
            {stage ? `Working… (${stage})` : "Thinking…"}
          </div>
        )}
        {error && <p className="rounded-lg border border-red-500/40 bg-red-500/10 p-2 text-sm text-red-200">Error: {error}</p>}
        <div ref={bottom} />
      </div>

      {clarification.length > 0 && (
        <div className="mb-2 rounded-xl border border-amber-400/30 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
          <p className="font-medium">I need a little more detail:</p>
          <ul className="mt-1 list-disc pl-5">{clarification.map((q, i) => <li key={i}>{q}</li>)}</ul>
        </div>
      )}
      <div className="mb-3 flex gap-2 rounded-2xl border border-slate-700 bg-slate-900 p-2 focus-within:border-sky-400">
        <input value={input} onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder={clarification.length ? "Answer the clarification above…" : "Ask anything about your data…"}
          className="flex-1 bg-transparent px-3 py-2 text-sm outline-none" />
        <button onClick={() => send()} disabled={loading || !input.trim()}
          className="rounded-xl bg-sky-500 px-5 py-2.5 text-sm font-semibold text-slate-950 disabled:opacity-50">
          {loading ? "…" : "Send"}
        </button>
      </div>
      <p className="mb-2 text-center text-[11px] text-slate-500">Answers are generated from your connected data.</p>
      {dashboardOpen && <DashboardPanel onClose={() => setDashboardOpen(false)} onOpenSession={loadConversation} />}
    </main>
  );
}
