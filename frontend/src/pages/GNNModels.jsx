import { useEffect, useState } from "react";
import api from "../api";
import { attributionWeights } from "../stats";
import { Panel, Stat } from "../components/Card.jsx";

export default function GNNModels() {
  const [riskScores, setRiskScores] = useState([]);

  useEffect(() => { api.riskScores().then(setRiskScores).catch(() => {}); }, []);

  const weights = attributionWeights(riskScores);
  const scored = riskScores.length;
  const avgRing = scored
    ? (riskScores.reduce((s, r) => s + (r.ring_membership_score || 0), 0) / scored).toFixed(3)
    : "—";
  const avgAnomaly = scored
    ? (riskScores.reduce((s, r) => s + (r.anomaly_score || 0), 0) / scored).toFixed(3)
    : "—";

  return (
    <div className="p-3 space-y-3 max-w-3xl">
      <div className="grid grid-cols-3 gap-2">
        <Stat label="ACCOUNTS SCORED" value={scored.toLocaleString()} />
        <Stat label="AVG RING SCORE" value={avgRing} />
        <Stat label="AVG ANOMALY SCORE" value={avgAnomaly} />
      </div>

      <Panel title="Feature Attribution (from live explanations)">
        {weights.length === 0 && <div className="text-xs text-muted">Run the pipeline to generate explanations.</div>}
        <div className="space-y-2">
          {weights.map((w) => (
            <div key={w.label}>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-300">{w.label}</span>
                <span className="text-muted mono">n={w.n}</span>
              </div>
              <div className="h-1.5 bg-line rounded overflow-hidden">
                <div className="h-full bg-amber" style={{ width: `${w.pct}%` }} />
              </div>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="Model Stack">
        <ul className="text-xs text-slate-300 space-y-1 list-disc pl-4">
          <li>XGBoost baseline classifier (velocity features)</li>
          <li>Ring scorer — networkx heuristic, GNN (GraphSAGE) when torch_geometric is available</li>
          <li>Autoencoder anomaly score (PyTorch, CPU)</li>
          <li>Logistic-regression stacker combining model + ring scores</li>
          <li>SHAP explanations for plain-language reasoning</li>
        </ul>
      </Panel>
    </div>
  );
}
