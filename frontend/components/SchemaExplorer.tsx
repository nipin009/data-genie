"use client";

import { useEffect, useMemo, useState } from "react";
import { getSchema } from "../lib/api";
import type { SchemaPayload } from "../lib/types";

function pretty(name: string) {
  return name.replace(/^dg_/, "").replaceAll("_", " ");
}

export default function SchemaExplorer() {
  const [schema, setSchema] = useState<SchemaPayload | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSchema().then((data) => {
      setSchema(data);
      setOpen(new Set(Object.keys(data.tables).slice(0, 1)));
    }).catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load schema."));
  }, []);

  const tables = useMemo(() => {
    if (!schema) return [];
    const term = query.trim().toLowerCase();
    return Object.entries(schema.tables).filter(([name, table]) =>
      !term || name.toLowerCase().includes(term) || table.columns.some((column) => column.toLowerCase().includes(term))
    );
  }, [schema, query]);

  function toggle(name: string) {
    setOpen((current) => {
      const next = new Set(current);
      next.has(name) ? next.delete(name) : next.add(name);
      return next;
    });
  }

  if (error) return <p className="mt-2 text-xs text-red-300">{error}</p>;
  if (!schema) return <p className="mt-2 text-xs text-slate-400">Loading interactive schema…</p>;

  return (
    <section className="mt-3 overflow-hidden rounded-xl border border-sky-500/25 bg-slate-950/50">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 px-3 py-2">
        <div className="mr-auto text-xs font-semibold text-sky-200">{tables.length} tables · click a table to inspect columns</div>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search tables or columns"
          className="w-48 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs outline-none focus:border-sky-400" />
      </div>
      <div className="max-h-[430px] overflow-y-auto p-2">
        {tables.map(([name, table]) => {
          const expanded = open.has(name);
          const relations = schema.join_edges.filter((edge) => edge.from_table === name || edge.to_table === name);
          return (
            <div key={name} className="mb-2 rounded-lg border border-slate-800 bg-slate-900/70">
              <button onClick={() => toggle(name)} className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-slate-800/70">
                <span className="text-xs text-sky-300">{expanded ? "▼" : "▶"}</span>
                <span className="font-mono text-sm text-slate-100">{name}</span>
                <span className="ml-auto text-xs text-slate-400">{table.columns.length} columns</span>
              </button>
              {expanded && (
                <div className="border-t border-slate-800 px-3 py-3">
                  <p className="mb-2 text-xs text-slate-400">{pretty(name)} · primary key: <span className="font-mono text-amber-200">{table.primary_keys.join(", ") || "—"}</span></p>
                  <div className="flex flex-wrap gap-1.5">
                    {table.columns.map((column) => (
                      <span key={column} className={`rounded-md border px-2 py-1 font-mono text-[11px] ${table.primary_keys.includes(column) ? "border-amber-400/40 bg-amber-400/10 text-amber-100" : "border-slate-700 bg-slate-800 text-slate-300"}`}>
                        {column}
                      </span>
                    ))}
                  </div>
                  {relations.length > 0 && <div className="mt-3 border-t border-slate-800 pt-2 text-[11px] text-slate-400">
                    <span className="mr-2 font-semibold text-slate-300">Relationships:</span>
                    {relations.map((edge) => <span key={`${edge.from_table}.${edge.from_col}.${edge.to_table}`} className="mr-2 inline-block font-mono">{edge.from_table}.{edge.from_col} → {edge.to_table}.{edge.to_col}</span>)}
                  </div>}
                </div>
              )}
            </div>
          );
        })}
        {tables.length === 0 && <p className="p-3 text-sm text-slate-400">No table or column matches “{query}”.</p>}
      </div>
    </section>
  );
}
