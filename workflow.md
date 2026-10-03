# Data Genie Query Workflow

This document describes how a user request travels through Data Genie—from the
chat interface to a grounded answer, visualization, persistent conversation
memory, and dashboard audit log.

```mermaid
flowchart TD
    U[User asks a question in Chat UI] --> API[FastAPI /api/chat or /api/chat/stream]

    API --> MEM[Load or create conversation session]
    MEM --> SESS[(datagenie_sessions)]
    MEM --> HIST[(datagenie_messages)]

    API --> CLASSIFY{Classify request}

    CLASSIFY -->|Schema request| SCHEMA[Read cached database schema]
    SCHEMA --> SCHEMA_ANSWER[Return table names, columns, or relationships]

    CLASSIFY -->|Ambiguous| CLARIFY[Ask targeted clarification]
    CLARIFY --> SAVE_PENDING[Save pending clarification in session]

    CLASSIFY -->|Unrelated / unsupported / not in schema| OFFTRACK[Return safe explanation]

    CLASSIFY -->|In-scope data question| PLAN[Build QuerySpec]
    PLAN --> RETRIEVE[Retrieve relevant tables, columns, joins, and business metrics]
    RETRIEVE --> GEN[Generate SQL with LLM or deterministic fallback]

    GEN --> SAFE{SQL safety validation}
    SAFE -->|Invalid| REPAIR[Repair SQL]
    REPAIR --> SAFE

    SAFE -->|Safe| SEMANTIC{Semantic validation}
    SEMANTIC -->|Missing metric, filter, grouping, or output| REPAIR
    SEMANTIC -->|Correct| EXEC[Execute read-only SQL]

    EXEC --> DB[(Retail analytics tables: dg_*)]
    DB --> RESULTS[Rows, columns, row count, and truncation state]

    RESULTS --> CHART[Choose visualization]
    CHART -->|Time series| LINE[Line chart]
    CHART -->|Categories| BAR[Bar or pie chart]
    CHART -->|Detailed rows| TABLE[Data table]

    RESULTS --> ANSWER[Create grounded answer]
    CHART --> RESPONSE[Final response]
    ANSWER --> RESPONSE

    SCHEMA_ANSWER --> RESPONSE
    CLARIFY --> RESPONSE
    OFFTRACK --> RESPONSE

    RESPONSE --> SAVE_HISTORY[Persist messages and response metadata]
    SAVE_HISTORY --> HIST

    RESPONSE --> AUDIT[Persist request audit log]
    AUDIT --> LOGS[(datagenie_request_logs)]

    RESPONSE --> UI[Chat UI shows answer, SQL, chart, and data table]

    LOGS --> DASH_API[Dashboard APIs]
    SESS --> DASH_API
    HIST --> DASH_API
    DASH_API --> DASH[Dashboard shows sessions and request logs]
```

## Request paths

| Request type | Handling | SQL executed? |
| --- | --- | --- |
| Schema metadata | Returns table names, columns, or foreign-key relationships from the cached schema | No |
| Ambiguous data question | Requests missing details and stores the clarification state | No |
| Unsupported or unrelated request | Gives a safe, explanatory response | No |
| Valid analytics question | Plans, generates, validates, executes, summarizes, and visualizes SQL results | Yes |

## Persistence

- `datagenie_sessions`: conversation ID, timestamps, and pending clarification state.
- `datagenie_messages`: user/assistant messages and assistant response metadata needed to restore SQL, results, and charts after a refresh.
- `datagenie_request_logs`: request text, classification, latency, row count, status, and errors shown in the Dashboard.

The operational tables use the `datagenie_` prefix instead of `dg_`, so the
Text-to-SQL workflow does not include internal memory or log records in user
analytics queries.
