import type { ChatResponsePayload, DashboardLog, DashboardSession, HistoryMessagePayload, SchemaPayload } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8001";
const API_KEY = process.env.NEXT_PUBLIC_DATA_GENIE_API_KEY;
const headers = (): Record<string, string> => ({ "Content-Type": "application/json", ...(API_KEY ? { "X-API-Key": API_KEY } : {}) });
const authHeaders = (): Record<string, string> => (API_KEY ? { "X-API-Key": API_KEY } : {});

export async function postChat(message: string, conversationId?: string): Promise<ChatResponsePayload> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ message, conversation_id: conversationId }),
  });
  if (!res.ok) throw new Error(`Chat failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function postClarify(conversationId: string, answers: string): Promise<ChatResponsePayload> {
  const res = await fetch(`${API_BASE}/api/clarify`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ conversation_id: conversationId, answers }),
  });
  if (!res.ok) throw new Error(`Clarify failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function getDashboardSessions(): Promise<DashboardSession[]> {
  const res = await fetch(`${API_BASE}/api/dashboard/sessions`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Could not load sessions: ${res.status}`);
  return (await res.json()).sessions || [];
}

export async function getDashboardLogs(): Promise<DashboardLog[]> {
  const res = await fetch(`${API_BASE}/api/dashboard/logs`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Could not load logs: ${res.status}`);
  return (await res.json()).logs || [];
}

export async function getHistory(conversationId: string): Promise<HistoryMessagePayload[]> {
  const res = await fetch(`${API_BASE}/api/history/${encodeURIComponent(conversationId)}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Could not load chat history: ${res.status}`);
  return (await res.json()).messages || [];
}

export async function getSchema(): Promise<SchemaPayload> {
  const res = await fetch(`${API_BASE}/api/schema`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Could not load schema: ${res.status}`);
  return res.json();
}

/** SSE streaming variant: calls onStatus(stage) then onDone(payload). */
export function streamChat(
  message: string,
  conversationId: string | undefined,
  onStatus: (stage: string) => void,
  onDone: (payload: ChatResponsePayload) => void,
  onError: (msg: string) => void
) {
  fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ message, conversation_id: conversationId }),
  }).then(async (res) => {
    if (!res.ok || !res.body) throw new Error(`Stream failed: ${res.status}`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() || "";
      for (const part of parts) {
        const m = part.match(/event:\s*(\w+)\s*\ndata:\s*([\s\S]*)/);
        if (!m) continue;
        const [, evt, data] = m;
        try {
          const json = JSON.parse(data);
          if (evt === "status") onStatus(json.stage);
          else if (evt === "final") onDone(json as ChatResponsePayload);
          else if (evt === "error") onError(json.message || "stream error");
        } catch { /* ignore partial */ }
      }
    }
  }).catch((e) => onError(String(e)));
}

export function downloadCsv(columns: string[], rows: Record<string, unknown>[]) {
  const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const csv = [columns.join(","), ...rows.map((r) => columns.map((c) => esc(r[c])).join(","))].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "results.csv";
  a.click();
  URL.revokeObjectURL(url);
}
