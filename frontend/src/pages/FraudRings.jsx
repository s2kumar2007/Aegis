import { useEffect, useState } from "react";
import api from "../api";
import { Panel } from "../components/Card.jsx";

export default function FraudRings() {
  const [rings, setRings] = useState([]);
  const [selected, setSelected] = useState(null);
  const [trace, setTrace] = useState(null);

  useEffect(() => { api.rings().then(setRings).catch(() => {}); }, []);

  function open(r) {
    setSelected(r);
    setTrace(null);
    api.ringTrace(r.root_account_id).then(setTrace).catch(() => setTrace([]));
  }

  return (
    <div className="grid grid-cols-[1fr_360px] gap-3 p-3">
      <Panel title={`Fraud Rings (${rings.length})`}>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-muted text-left border-b border-line">
              <th className="py-1.5">Root Account</th>
              <th>Members</th>
              <th>Pattern</th>
            </tr>
          </thead>
          <tbody>
            {rings.map((r) => (
              <tr
                key={r.root_account_id}
                onClick={() => open(r)}
                className="border-b border-line hover:bg-ink cursor-pointer"
              >
                <td className="py-1.5 mono">{r.root_account_id}</td>
                <td>{r.member_ids?.length ?? "—"}</td>
                <td className="text-muted">{r.pattern_guess ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rings.length === 0 && <div className="text-muted text-xs py-4">No active rings detected.</div>}
      </Panel>

      <Panel title="Ring Trace">
        {!selected && <div className="text-xs text-muted">Select a ring to view its hop-by-hop trace.</div>}
        {selected && !trace && <div className="text-xs text-muted">Loading trace…</div>}
        {selected && trace && (
          <div className="space-y-1.5 text-xs max-h-[70vh] overflow-auto">
            {trace.map((hop, i) => (
              <div key={i} className="flex justify-between border-b border-line pb-1">
                <span className="mono">{hop.route ?? `hop ${i}`}</span>
                <span className="text-muted">₹{hop.amount?.toLocaleString?.() ?? hop.amount}</span>
              </div>
            ))}
            {trace.length === 0 && <div className="text-muted">No trace data.</div>}
          </div>
        )}
      </Panel>
    </div>
  );
}
