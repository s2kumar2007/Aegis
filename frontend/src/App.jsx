import React, { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { api } from "./api.js";
import "./styles.css";

function riskColor(score) {
  if (score >= 0.75) return "#ff3333";
  if (score >= 0.5) return "#ffb000";
  if (score >= 0.25) return "#ffea00";
  return "#00e676";
}

export default function App() {
  const [accounts, setAccounts] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [riskScores, setRiskScores] = useState([]);
  const [rings, setRings] = useState([]);
  const [selectedNode, setSelectedNode] = useState(null);
  const [selectedRing, setSelectedRing] = useState(null);
  const [explanation, setExplanation] = useState(null);
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
        val: 3 + (score ? score.model_score * 8 : 0),
        color: riskColor(score ? score.model_score : 0),
        rawScore: score ? score.model_score : 0,
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
      setExplanation({ explanation: "NO EXPLANATION RECORDED FOR TARGET NODE." });
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

  // Draw custom high-finance square nodes with sharp borders and brackets
  const drawNode = (node, ctx, globalScale) => {
    const size = Math.max(5, node.val || 4);
    const isSelected = selectedNode && selectedNode.id === node.id;
    const isHighRisk = node.rawScore >= 0.75;

    ctx.fillStyle = isSelected ? "#ffffff" : node.color;
    ctx.fillRect(node.x - size / 2, node.y - size / 2, size, size);

    // Draw targeting bracket around high risk or selected nodes
    if (isSelected || isHighRisk) {
      const bSize = size + 6;
      const h = bSize / 2;
      ctx.strokeStyle = isSelected ? "#ffffff" : node.color;
      ctx.lineWidth = 1.2 / globalScale;
      ctx.beginPath();
      // Top Left
      ctx.moveTo(node.x - h, node.y - h + 3);
      ctx.lineTo(node.x - h, node.y - h);
      ctx.lineTo(node.x - h + 3, node.y - h);
      // Top Right
      ctx.moveTo(node.x + h - 3, node.y - h);
      ctx.lineTo(node.x + h, node.y - h);
      ctx.lineTo(node.x + h, node.y - h + 3);
      // Bottom Right
      ctx.moveTo(node.x + h, node.y + h - 3);
      ctx.lineTo(node.x + h, node.y + h);
      ctx.lineTo(node.x + h - 3, node.y + h);
      // Bottom Left
      ctx.moveTo(node.x - h + 3, node.y + h);
      ctx.lineTo(node.x - h, node.y + h);
      ctx.lineTo(node.x - h, node.y + h - 3);
      ctx.stroke();
    }

    if (globalScale > 1.2 || isSelected) {
      const label = node.id;
      const fontSize = 10 / globalScale;
      ctx.font = `${fontSize}px 'JetBrains Mono', monospace`;
      ctx.fillStyle = isSelected ? "#ffffff" : "#a0a0a0";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText(label, node.x, node.y + size / 2 + 4);
    }
  };

  return (
    <div className="terminal-container">
      <div className="scanlines"></div>

      <div className="ticker-bar">
        <div className="ticker-block">
          <span className="ticker-lbl">SYS.STATUS:</span>
          <span className="ticker-val c-green blink">ONLINE</span>
        </div>
        <div className="ticker-block">
          <span className="ticker-lbl">TOTAL.ACC:</span>
          <span className="ticker-val">{accounts.length}</span>
        </div>
        <div className="ticker-block">
          <span className="ticker-lbl">TXN.FLOW:</span>
          <span className="ticker-val">{graphData.links.length} EDGES</span>
        </div>
        <div className="ticker-block">
          <span className="ticker-lbl">ALERT.RINGS:</span>
          <span className="ticker-val c-red">{rings.length}</span>
        </div>
        <div className="ticker-block">
          <span className="ticker-lbl">TIME.WINDOW:</span>
          <span className="ticker-val">{new Date(cutoffTs || Date.now()).toLocaleTimeString()}</span>
        </div>
      </div>

      <header className="header-bar">
        <div className="brand">
          <h1>AEGIS // F.I.N.T.</h1>
          <span>Financial Intelligence Network Terminal v2.1</span>
        </div>
        <div className="actions">
          <button className="btn accent" onClick={() => api.runPipeline().then(loadAll)}>
            [ EXEC_PIPELINE ]
          </button>
          <button className="btn" onClick={() => api.startReplay()}>
            [ REPLAY ]
          </button>
          <button className="btn" onClick={() => api.runAdaptation()}>
            [ ADAPT_MODEL ]
          </button>
          <button className="btn" onClick={loadAll}>
            [ REFRESH ]
          </button>
        </div>
      </header>

      {error && <div className="banner banner-err">SYS.ERR: {error}</div>}
      {loading && <div className="banner banner-load typing">LOADING NETWORK TOPOLOGY</div>}

      <div className="workspace">
        <div className="graph-pane">
          <div className="graph-wrapper">
            <ForceGraph2D
              ref={fgRef}
              graphData={graphData}
              backgroundColor="rgba(0,0,0,0)" // Transparent to see CSS grid
              nodeCanvasObject={drawNode}
              nodePointerAreaPaint={(node, color, ctx) => {
                const size = Math.max(6, node.val || 4);
                ctx.fillStyle = color;
                ctx.fillRect(node.x - size / 2, node.y - size / 2, size, size);
              }}
              linkColor={(link) => selectedNode && (link.source.id === selectedNode.id || link.target.id === selectedNode.id) ? "#ffffff" : "#222222"}
              linkWidth={(link) => selectedNode && (link.source.id === selectedNode.id || link.target.id === selectedNode.id) ? 1.5 : 1}
              linkDirectionalParticles={(link) => link.amount > 5000 ? 2 : 0}
              linkDirectionalParticleSpeed={0.005}
              linkDirectionalParticleWidth={2}
              linkDirectionalParticleColor={() => "#ffb000"}
              onNodeClick={handleNodeClick}
            />
            
            <div className="hud">
              <div className="hud-title">TOPOLOGY OVERVIEW</div>
              <div className="hud-row">
                <span className="hud-lbl">ACTIVE NODES</span>
                <span className="hud-val">{graphData.nodes.length}</span>
              </div>
              <div className="hud-row">
                <span className="hud-lbl">VISIBLE TXNS</span>
                <span className="hud-val">{graphData.links.length}</span>
              </div>
            </div>
          </div>

          <div className="timeline">
            <span className="time-lbl">SCRUBBER</span>
            <input
              type="range"
              className="time-slider"
              min={0}
              max={100}
              value={scrubberPos}
              onChange={(e) => setScrubberPos(Number(e.target.value))}
            />
            <span className="time-val">
              {new Date(cutoffTs || Date.now()).toISOString().replace("T", " ").substring(0, 19)}
            </span>
          </div>
        </div>

        <aside className="side-pane">
          <div className="pane-section">
            <div className="sec-header">
              <span>[ CASE_FILES ]</span>
              <span className="sec-count">{rings.length}</span>
            </div>
            <div className="sec-body">
              <div className="ring-list">
                {rings.length === 0 && <div className="no-data">NO ACTIVE RINGS</div>}
                {rings.map((r) => {
                  const isSelected = selectedRing?.root_account_id === r.root_account_id;
                  return (
                    <div
                      key={r.root_account_id}
                      className={`ring-card ${isSelected ? "active" : ""}`}
                      onClick={() => handleRingClick(r)}
                    >
                      <div className="r-header">
                        <span className="r-id">ROOT: {r.root_account_id}</span>
                        <span className="tag-high">HIGH_RISK</span>
                      </div>
                      <div className="r-stats">
                        <span>ACC: <strong>{r.accounts_touched}</strong></span>
                        <span>AMT: <strong>₹{Number(r.total_amount_moved).toLocaleString()}</strong></span>
                        <span>DPT: <strong>{r.max_depth}</strong></span>
                      </div>
                    </div>
                  );
                })}
              </div>

              {selectedRing && (
                <div className="inspector-card">
                  <div style={{ color: "var(--amber)", fontWeight: 700, marginBottom: "8px" }}>CASE: {selectedRing.root_account_id}</div>
                  <div className="inspector-row">
                    <span className="inspector-key">TOTAL MOVED:</span>
                    <span className="inspector-val">₹{Number(selectedRing.total_amount_moved).toLocaleString()}</span>
                  </div>
                  <div className="inspector-row">
                    <span className="inspector-key">ACCOUNTS:</span>
                    <span className="inspector-val">{selectedRing.accounts_touched}</span>
                  </div>
                  <div className="inspector-row">
                    <span className="inspector-key">WINDOW:</span>
                    <span className="inspector-val" style={{ fontSize: "9px" }}>
                      {selectedRing.chain_start} → {selectedRing.chain_end}
                    </span>
                  </div>

                  {selectedRing.trace && selectedRing.trace.length > 0 && (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>HOP</th>
                          <th>ACCOUNT</th>
                          <th>AMOUNT</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedRing.trace.map((hop, i) => (
                          <tr key={i}>
                            <td>#{hop.hop_no}</td>
                            <td>{hop.account_id}</td>
                            <td>₹{Number(hop.amount).toLocaleString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="pane-section">
            <div className="sec-header">
              <span>[ NODE_INSPECTOR ]</span>
            </div>
            <div className="sec-body">
              {!selectedNode && <div className="no-data">SELECT A NODE TO INSPECT</div>}
              {selectedNode && (
                <div className="inspector-card" style={{ marginTop: 0 }}>
                  <div className="inspector-row">
                    <span className="inspector-key">ID:</span>
                    <span className="inspector-val">{selectedNode.id}</span>
                  </div>
                  <div className="inspector-row">
                    <span className="inspector-key">RISK:</span>
                    <span className="inspector-val" style={{ color: selectedNode.color }}>
                      {(selectedNode.rawScore * 100).toFixed(1)}%
                    </span>
                  </div>

                  <div style={{ marginTop: "12px" }}>
                    <div className="inspector-key" style={{ marginBottom: "6px" }}>TRACE:</div>
                    {explanation ? (
                      <div style={{ color: "var(--text-main)", lineHeight: "1.4" }}>
                        {explanation.explanation}
                        {explanation.model_score !== undefined && (
                          <div style={{ marginTop: "8px", color: "var(--text-dim)", fontSize: "9px" }}>
                            MOD_SCR: {Number(explanation.model_score).toFixed(4)} | RNG_SCR: {Number(explanation.ring_membership_score || 0).toFixed(4)}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="no-data typing">FETCHING</div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
