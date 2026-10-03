"use client";
import { useMemo, useState } from "react";

export default function DataTable({ columns, rows }: { columns: string[]; rows: Record<string, unknown>[] }) {
  const [q, setQ] = useState("");
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [asc, setAsc] = useState(true);
  const [page, setPage] = useState(0);
  const per = 25;

  const filtered = useMemo(() => {
    let r = rows;
    if (q.trim()) {
      const needle = q.toLowerCase();
      r = r.filter((row) => columns.some((c) => String(row[c] ?? "").toLowerCase().includes(needle)));
    }
    if (sortCol) {
      r = [...r].sort((a, b) => {
        const va = a[sortCol]; const vb = b[sortCol];
        if (typeof va === "number" && typeof vb === "number") return asc ? va - vb : vb - va;
        return asc ? String(va ?? "").localeCompare(String(vb ?? "")) : String(vb ?? "").localeCompare(String(va ?? ""));
      });
    }
    return r;
  }, [rows, q, sortCol, asc, columns]);

  const pages = Math.max(1, Math.ceil(filtered.length / per));
  const slice = filtered.slice(page * per, page * per + per);

  return (
    <div className="mt-2">
      <div className="mb-1 flex items-center gap-2">
        <input value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} placeholder="Filter rows…"
          className="w-48 rounded-md bg-slate-900 border border-slate-700 px-2 py-1 text-xs outline-none" />
        <span className="text-[11px] text-slate-500">{filtered.length} rows</span>
        <span className="flex-1" />
        {pages > 1 && (
          <span className="flex items-center gap-1 text-xs text-slate-400">
            <button disabled={page === 0} onClick={() => setPage(page - 1)} className="px-1 disabled:opacity-30">‹</button>
            {page + 1}/{pages}
            <button disabled={page + 1 >= pages} onClick={() => setPage(page + 1)} className="px-1 disabled:opacity-30">›</button>
          </span>
        )}
      </div>
      <div className="max-h-72 overflow-auto rounded-lg border border-slate-800">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-slate-900">
            <tr>{columns.map((c) => (
              <th key={c} onClick={() => { if (sortCol === c) setAsc(!asc); else { setSortCol(c); setAsc(true); } }}
                className="cursor-pointer whitespace-nowrap px-2 py-1.5 text-left font-semibold text-slate-300 hover:text-white">
                {c}{sortCol === c ? (asc ? " ▲" : " ▼") : ""}
              </th>))}
            </tr>
          </thead>
          <tbody>
            {slice.map((r, i) => (
              <tr key={i} className={i % 2 ? "bg-slate-900/40" : ""}>
                {columns.map((c) => <td key={c} className="whitespace-nowrap px-2 py-1 text-slate-200">{String(r[c] ?? "")}</td>)}
              </tr>
            ))}
            {slice.length === 0 && <tr><td colSpan={columns.length} className="px-2 py-4 text-center text-slate-500">No rows match.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
