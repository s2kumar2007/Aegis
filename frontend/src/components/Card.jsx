export function Panel({ title, right, children, className = "" }) {
  return (
    <div className={`border border-line rounded-lg bg-panel ${className}`}>
      {title && (
        <div className="px-3 py-2.5 border-b border-line flex items-center justify-between">
          <div className="text-[11px] font-medium text-slate-300 tracking-wide">{title}</div>
          {right}
        </div>
      )}
      <div className="p-3">{children}</div>
    </div>
  );
}

export function Stat({ label, value, sub, tone }) {
  const toneClass = tone === "danger" ? "text-danger" : tone === "ok" ? "text-ok" : "text-slate-100";
  return (
    <div className="border border-line rounded-md bg-ink/40 px-3 py-2">
      <div className="text-[10px] text-muted mono tracking-wide">{label}</div>
      <div className={`text-lg font-semibold mono ${toneClass}`}>{value}</div>
      {sub && <div className="text-[10px] text-muted mt-0.5">{sub}</div>}
    </div>
  );
}

export function Badge({ children, tone = "muted" }) {
  const map = {
    danger: "bg-danger/15 text-danger border-danger/30",
    ok: "bg-ok/15 text-ok border-ok/30",
    amber: "bg-amber/15 text-amber border-amber/30",
    muted: "bg-line/40 text-muted border-line",
  };
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border mono ${map[tone]}`}>
      {children}
    </span>
  );
}

export function ProgressBar({ value, max = 100, tone = "amber" }) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  const color = tone === "danger" ? "bg-danger" : tone === "ok" ? "bg-ok" : "bg-amber";
  return (
    <div className="h-1.5 bg-line rounded-full overflow-hidden">
      <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
    </div>
  );
}
