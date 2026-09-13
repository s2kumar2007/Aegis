import { useEffect, useMemo, useState } from "react";
import api from "../api";
import { Panel } from "../components/Card.jsx";

export default function CaseFiles() {
  const [riskScores, setRiskScores] = useState([]);
  const [openCase, setOpenCase] = useState(null);

  useEffect(() => { api.riskScores().then(setRiskScores).catch(() => {}); }, []);

  const cases = useMemo(
    () => [...riskScores].sort((a, b) => b.model_score - a.model_score).slice(0, 50),
    [riskScores]
  );

  return (
    <div className="grid grid-cols-[1fr_380px] gap-3 p-3">
      <Panel title={`Case Files (${cases.length})`}>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-muted text-left border-b border-line">
              <th className="py-1.5">Account</th>
              <th>Risk</th>
              <th>Flagged</th>
            </tr>
          </thead>
          <tbody>
            {cases.map((c) => (
              <tr
                key={c.account_id}
                onClick={() => setOpenCase(c)}
                className="border-b border-line hover:bg-ink cursor-pointer"
              >
                <td className="py-1.5 mono">{c.account_id}</td>
                <td className={c.model_score >= 0.7 ? "text-danger" : "text-amber"}>
                  {(c.model_score * 100).toFixed(1)}
                </td>
                <td className="text-muted">{c.flagged_at?.slice(0, 16).replace("T", " ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel title="Case File">
        {!openCase && <div className="text-xs text-muted">Select a case to open its file.</div>}
        {openCase && (
          <div className="space-y-2 text-xs">
            <div className="mono text-base text-slate-100">{openCase.account_id}</div>
            <div className="text-danger mono text-2xl font-semibold">
              {(openCase.model_score * 100).toFixed(1)}
              <span className="text-muted text-xs font-normal"> / 100</span>
            </div>
            <div className="text-muted leading-relaxed">{openCase.explanation}</div>
            <div className="pt-2 border-t border-line text-muted">
              Ring score: {openCase.ring_membership_score?.toFixed(2)} · Anomaly: {openCase.anomaly_score?.toFixed(2)}
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}
