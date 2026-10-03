"use client";
import { useState } from "react";

export default function SqlPreview({ sql }: { sql?: string | null }) {
  const [open, setOpen] = useState(false);
  if (!sql) return null;
  return (
    <div className="mt-2">
      <button onClick={() => setOpen(!open)} className="text-xs text-slate-400 hover:text-slate-200">
        {open ? "▾ Hide SQL" : "▸ View generated SQL"}
      </button>
      {open && (
        <pre className="mt-1 max-h-48 overflow-auto rounded-lg bg-slate-950 border border-slate-800 p-2 text-[11px] leading-relaxed text-emerald-200">
          {sql}
        </pre>
      )}
    </div>
  );
}
