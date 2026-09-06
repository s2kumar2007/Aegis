import React, { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { api } from "./api.js";
import "./styles.css";

function riskColor(score) {
  if (score >= 0.75) return "#ff3b3b";
  if (score >= 0.5) return "#ff9f1c";
  if (score >= 0.25) return "#f4d35e";
  return "#3fbf7f";
}

export default function App() {
  const [accounts, setAccounts] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [riskScores, setRiskScores] = useState([]);
  const [rings, setRings] = useState([]);
  const [selectedNode, setSelectedNode] = useState(null);
  const [selectedRing, setSelectedRing] = useState(null);
  const [explanation, setExplanation] = useState(null);
  const [timeRange, setTimeRange] = useState([0, 100]);
  const [scrubberPos, setScrubberPos] = useState(100);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const fgRef = useRef();

  const scoreByAccount = useMemo(() => {
    const m = new Map();
    riskScores.forEach((r) => m.set(r.account_id, r));
    return m;
  }, [riskScores]);

  const allTimestamps = useMemo(
    () => transactions.map((t) => new Date(t.txn_timestamp).getTime()).filter(Boolean),
    [transactions]
  );

  const minTs = allTimestamps.length ? Math.min(...allTimestamps) : 0;
  const maxTs = allTimestamps.length ? Math.max(...allTimestamps) : 1;

  const cutoffTs = minTs + ((maxTs - minTs) * scrubberPos) / 100;

  async function loadAll() {
    setLoading(true);
    setError(null);
    try {
      const [acc, txns, scores, ringSummaries] = await Promise.all([
        api.accounts(),
        api.transactions(),
        api.riskScores().catch(() => []),
        api.rings().catch(() => []),
      ]);
      setAccounts(acc);
      setTransactions(txns);
      setRiskScores(scores);
      setRings(ringSummaries);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
  }, []);

  const graphData = useMemo(() => {
    const visibleTxns = transactions.filter(
      (t) => new Date(t.txn_timestamp).getTime() <= cutoffTs
    );
    const nodeIds = new Set();
    visibleTxns.forEach((t) => {
      nodeIds.add(t.sender_id);
      nodeIds.add(t.receiver_id);
    });
    const nodes = Array.from(nodeIds).map((id) => {
      const score = scoreByAccount.get(id);
      return {
        id,
        val: 2 + (score ? score.model_score * 6 : 0),
        color: riskColor(score ? score.model_score : 0),
      };
    });
    const links = visibleTxns.map((t) => ({
      source: t.sender_id,
      target: t.receiver_id,
      amount: t.amount,
    }));
    return { nodes, links };
  }, [transactions, cutoffTs, scoreByAccount]);

  async function handleNodeClick(node) {
    setSelectedNode(node);
    setExplanation(null);
    try {
      const exp = await api.explain(node.id);
      setExplanation(exp);
    } catch {
      setExplanation({ explanation: "No explanation on file yet — run the pipeline first." });
    }
  }

  async function handleRingClick(ring) {
    setSelectedRing(ring);
    try {
      const trace = await api.ringTrace(ring.root_account_id);
      setSelectedRing({ ...ring, trace });
    } catch {
      setSelectedRing({ ...ring, trace: [] });
    }
  }

  return (
    <div className="war-room">
      <header className="header">
        <div className="brand">
          <span className="brand-mark">AEGIS</span>
          <span className="brand-sub">Adaptive Graph-Based UPI Fraud Detection</span>
        </div>
        <div className="actions">
          <button onClick={() => api.runPipeline().then(loadAll)}>Run Detection Pipeline</button>
          <button onClick={() => api.startReplay()}>Start Replay</button>
          <button onClick={() => api.runAdaptation()}>Trigger Adaptation</button>
          <button onClick={loadAll}>Refresh</button>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}
      {loading && <div className="loading-banner">Loading network state…</div>}

      <div className="body">
        <div className="graph-panel">
          <ForceGraph2D
            ref={fgRef}
            graphData={graphData}
            backgroundColor="#0b0e14"
            nodeLabel={(n) => `${n.id}`}
            linkColor={() => "rgba(120,140,200,0.25)"}
            linkDirectionalArrowLength={3}
            linkDirectionalArrowRelPos={1}
            onNodeClick={handleNodeClick}
            nodeCanvasObjectMode={() => "after"}
          />
          <div className="scrubber">
            <label>Timeline replay</label>
            <input
              type="range"
              min={0}
              max={100}
              value={scrubberPos}
              onChange={(e) => setScrubberPos(Number(e.target.value))}
            />
            <span>{new Date(cutoffTs || Date.now()).toLocaleString()}</span>
          </div>
        </div>

        <aside className="side-panel">
          <section>
            <h3>Ring Case Files</h3>
            <div className="ring-list">
              {rings.length === 0 && <p className="muted">No ring candidates yet — run the pipeline.</p>}
              {rings.map((r) => (
                <div
                  key={r.root_account_id}
                  className={`ring-card ${selectedRing?.root_account_id === r.root_account_id ? "active" : ""}`}
                  onClick={() => handleRingClick(r)}
                >
                  <div className="ring-title">{r.root_account_id}</div>
                  <div className="ring-meta">
                    {r.accounts_touched} accounts · ₹{Number(r.total_amount_moved).toLocaleString()} · depth {r.max_depth}
                  </div>
                </div>
              ))}
            </div>
            {selectedRing && (
              <div className="case-file">
                <h4>Case File: {selectedRing.root_account_id}</h4>
                <p>Total moved: ₹{Number(selectedRing.total_amount_moved).toLocaleString()}</p>
                <p>Accounts touched: {selectedRing.accounts_touched}</p>
                <p>Max hop depth: {selectedRing.max_depth}</p>
                <p>Window: {selectedRing.chain_start} → {selectedRing.chain_end}</p>
                {selectedRing.trace && (
                  <div className="trace-list">
                    {selectedRing.trace.map((hop, i) => (
                      <div key={i} className="trace-hop">
                        hop {hop.hop_no}: {hop.account_id} · ₹{Number(hop.amount).toLocaleString()}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>

          <section>
            <h3>Explain</h3>
            {!selectedNode && <p className="muted">Click a node in the graph to see its explanation.</p>}
            {selectedNode && (
              <div className="explain-box">
                <h4>{selectedNode.id}</h4>
                {explanation ? (
                  <>
                    <p className="explanation-text">{explanation.explanation}</p>
                    {explanation.model_score !== undefined && (
                      <p className="muted">
                        model_score: {Number(explanation.model_score).toFixed(3)} · ring_membership_score:{" "}
                        {Number(explanation.ring_membership_score || 0).toFixed(3)}
                      </p>
                    )}
                  </>
                ) : (
                  <p className="muted">Loading explanation…</p>
                )}
              </div>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
