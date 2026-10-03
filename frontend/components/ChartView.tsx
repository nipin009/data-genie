"use client";
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";

const COLORS = ["#38bdf8", "#f472b6", "#a3e635", "#fbbf24", "#c084fc", "#2dd4bf", "#fb7185", "#93c5fd"];

export default function ChartView({ chartType, x, y, columns, rows }: {
  chartType: string; x?: string | null; y?: string | null; columns: string[]; rows: Record<string, unknown>[];
}) {
  if (!rows?.length || !columns?.length) return <p className="mt-2 text-xs text-slate-500">No data to chart.</p>;
  const xk = x || columns[0];
  const yk = y || columns.find((c) => typeof rows[0]?.[c] === "number") || columns[1];
  const data = rows.slice(0, 50).map((r) => ({ ...r, [xk]: String(r[xk] ?? "") }));

  if (chartType === "line") {
    return (
      <div className="mt-2 h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 32 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey={xk} tick={{ fill: "#94a3b8", fontSize: 11 }} angle={-20} textAnchor="end" height={50} interval="preserveStartEnd" />
            <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} />
            <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
            <Legend />
            <Line type="monotone" dataKey={yk} stroke="#38bdf8" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    );
  }
  if (chartType === "pie") {
    return (
      <div className="mt-2 h-64">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} dataKey={yk} nameKey={xk} outerRadius={90} label>
              {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
            </Pie>
            <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      </div>
    );
  }
  // default bar
  return (
    <div className="mt-2 h-64">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 32 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey={xk} tick={{ fill: "#94a3b8", fontSize: 11 }} angle={-20} textAnchor="end" height={50} interval={0} />
          <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} />
          <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
          <Legend />
          <Bar dataKey={yk} fill="#38bdf8">
            {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
