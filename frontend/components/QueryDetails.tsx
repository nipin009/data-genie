"use client";
import { useState } from "react";

export default function QueryDetails({ tables, chartReason, rowCount, truncated, validationError }: {
  tables?: string[]; chartReason?: string | null; rowCount?: number; truncated?: boolean; validationError?: string | null;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-1">
      <button onClick={() => setOpen(!open)} className="text-xs text-slate-500 hover:text-slate-300">
        {open ? "▾ Query details" : "▸ Query details"}
      </button>
      {open && (
        <dl className="mt-1 space-y-0.5 text-xs text-slate-400">
          <div><dt className="inline font-semibold">Tables: </dt><dd className="inline">{(tables || []).join(", ") || "—"}</dd></div>
          <div><dt className="inline font-semibold">Rows: </dt><dd className="inline">{rowCount}{truncated ? " (truncated at server limit)" : ""}</dd></div>
          <div><dt className="inline font-semibold">Chart choice: </dt><dd className="inline">{chartReason || "—"}</dd></div>
          {validationError && <div className="text-red-300"><dt className="inline font-semibold">Warning: </dt><dd className="inline">{validationError}</dd></div>}
        </dl>
      )}
    </div>
  );
}
