import { useState } from "react";
import api from "../api";
import { Panel } from "../components/Card.jsx";

export default function EntityInspector() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function search(e) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true); setError(null); setResult(null);
    try {
      const data = await api.explain(query.trim());
      setResult(data);
    } catch (e) {
      setError(`No record found for "${query.trim()}".`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-3 max-w-2xl">
      <Panel title="Entity Inspector">
        <form onSubmit={search} className="flex gap-2 mb-3">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Account ID, e.g. MULE0035009"
            className="flex-1 bg-ink border border-line rounded px-2 py-1.5 text-sm mono outline-none focus:border-amber"
          />
          <button className="px-3 py-1.5 bg-amber text-ink text-sm font-medium rounded" type="submit">
            Inspect
          </button>
        </form>
        {loading && <div className="text-xs text-muted">Searching…</div>}
        {error && <div className="text-xs text-danger">{error}</div>}
        {result && (
          <div className="space-y-3">
            <div className="mono text-lg text-slate-100">{result.account_id}</div>
            <div className="grid grid-cols-3 gap-2">
              <Metric label="Model Score" value={result.model_score} />
              <Metric label="Ring Score" value={result.ring_membership_score} />
              <Metric label="Anomaly Score" value={result.anomaly_score} />
            </div>
            <div>
              <div className="text-[10px] text-muted mono mb-1">EXPLANATION</div>
              <div className="text-sm text-slate-300 leading-relaxed">{result.explanation}</div>
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="border border-line rounded px-2 py-1.5">
      <div className="text-[10px] text-muted mono">{label}</div>
      <div className="mono text-sm text-slate-100">{typeof value === "number" ? value.toFixed(3) : "—"}</div>
    </div>
  );
}
