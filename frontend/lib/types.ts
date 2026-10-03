export type ChartType = "bar" | "line" | "pie" | "table" | "none";

export interface ChartSpec {
  type: ChartType;
  x?: string | null;
  y?: string | null;
  reason?: string | null;
}

export interface SchemaTable {
  columns: string[];
  primary_keys: string[];
  foreign_keys: Array<{ constrained_columns?: string[]; referred_table?: string; referred_columns?: string[] }>;
  row_count?: number | null;
}

export interface SchemaPayload {
  tables: Record<string, SchemaTable>;
  join_edges: Array<{ from_table: string; from_col: string; to_table: string; to_col: string }>;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  classification?: string;
  sql?: string | null;
  columns?: string[];
  rows?: Record<string, unknown>[];
  rowCount?: number;
  truncated?: boolean;
  chart?: ChartSpec;
  clarificationQuestions?: string[];
  selectedTables?: string[];
  validationError?: string | null;
  view?: "chart" | "table";
}

export interface ChatResponsePayload {
  conversation_id: string;
  classification: string;
  answer: string;
  sql?: string | null;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  chart: ChartSpec;
  clarification_questions: string[];
  selected_tables: string[];
  validation_error?: string | null;
}

export interface HistoryMessagePayload {
  role: "user" | "assistant";
  content: string;
  metadata?: Partial<ChatResponsePayload> | null;
}

export interface DashboardSession {
  conversation_id: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface DashboardLog {
  log_id: string;
  conversation_id?: string | null;
  request_text: string;
  classification?: string | null;
  row_count?: number | null;
  latency_ms?: number | null;
  status: string;
  error_text?: string | null;
  created_at: string;
}
