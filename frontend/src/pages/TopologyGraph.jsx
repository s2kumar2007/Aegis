import { useEffect, useMemo, useState, useCallback } from "react";
import ForceGraph2D from "react-force-graph-2d";
import api from "../api";
import { graphStats, anomalyCohort } from "../stats";
import { Panel, Stat, Badge, ProgressBar } from "../components/Card.jsx";

export default function TopologyGraph() {
  const [accounts, setAccounts] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [rings, setRings] = useState([]);
  const [riskScores, setRiskScores] = useState([]);
  const [selected, setSelected] = useState(null);
  const [selectedRing, setSelectedRing] = useState(null);
  const [error, setError] = useState(null);
  const [minFlow, setMinFlow] = useState(0);

  useEffect(() => {
    async function load() {
      try {
        const [acc, txn, rng, risk] = await Promise.all([
          api.accounts(), api.transactions(), api.rings(), api.riskScores(),
        ]);
        setAccounts(acc); setTransactions(txn); setRings(rng); setRiskScores(risk);
      } catch (e) {
        setError(e.message);
      }
    }
    load();
  }, []);

  const riskByAccount = useMemo(() => {
    const m = new Map();
    riskScores.forEach((r) => m.set(r.account_id, r));
    return m;
  }, [riskScores]);

  const filteredTxns = useMemo(
    () => transactions.filter((t) => t.amount >= minFlow),
    [transactions, minFlow]
  );

  const graphData = useMemo(() => {
    const nodes = accounts.map((a) => ({
      id: a.account_id,
      risk: riskByAccount.get(a.account_id)?.model_score ?? 0,
    }));
    const links = filteredTxns.map((t) => ({
      source: t.sender_id, target: t.receiver_id, amount: t.amount,
    }));
    return { nodes, links };
  }, [accounts, filteredTxns, riskByAccount]);

  const stats = useMemo(() => graphStats(accounts, transactions, rings), [accounts, transactions, rings]);
  const cohort = useMemo(() => anomalyCohort(riskScores), [riskScores]);

  // Ring cards: real exposure (sum of txn amounts touching ring members),
  // velocity (txn count), age (earliest txn among members) -- all computed.
  const ringCards = useMemo(() => {
    return rings.slice(0, 8).map((r) => {
      const members = new Set([r.root_account_id, ...(r.member_ids || [])].filter(Boolean));
      const touching = transactions.filter((t) => members.has(t.sender_id) || members.has(t.receiver_id));
      const exposure = touching.reduce((s, t) => s + (t.amount || 0), 0);
      const ts = touching.map((t) => new Date(t.txn_timestamp).getTime()).filter((n) => !isNaN(n));
      const ageMs = ts.length ? Date.now() - Math.min(...ts) : 0;
      const ageHrs = Math.max(0, Math.round(ageMs / 3600000));
      const risk = riskByAccount.get(r.root_account_id);
      return {
        id: r.root_account_id,
        pattern: r.pattern_guess || "structuring",
        exposure,
        velocity: touching.length,
        ageHrs,
        nodes: members.size,
        score: Math.round((risk?.model_score ?? 0) * 100),
      };
    });
  }, [rings, transactions, riskByAccount]);

  // 24h flow velocity, bucketed hourly from real transaction timestamps.
  const flowSeries = useMemo(() => {
    const buckets = new Array(24).fill(0);
    const now = Date.now();
    transactions.forEach((t) => {
      const ts = new Date(t.txn_timestamp).getTime();
      const hoursAgo = Math.floor((now - ts) / 3600000);
      if (hoursAgo >= 0 && hoursAgo < 24) buckets[23 - hoursAgo]++;
    });
    return buckets;
  }, [transactions]);

  const nodeColor = useCallback((n) => {
    if (n.risk >= 0.7) return "#e5484d";
    if (n.risk >= 0.3) return "#e0a336";
    return "#3ecf8e";
  }, []);

  if (error) {
    return <div className="p-6 text-danger mono text-sm">SYS.ERR: {error}</div>;
  }

  const maxFlow = Math.max(1, ...flowSeries);
  const feed = [...transactions].sort((a, b) => new Date(b.txn_timestamp) - new Date(a.txn_timestamp)).slice(0, 8);

  return (
    <div className="grid grid-cols-[270px_1fr_320px] gap-3 p-3 h-[calc(100vh-3rem)]">
      <div className="flex flex-col gap-3 overflow-auto pr-1">
        <Panel title="Graph topology" right={<Badge tone="ok">LOD-1 stream</Badge>}>
          <div className="grid grid-cols-2 gap-2">
            <Stat label="NODES" value={stats.nodeCount.toLocaleString()} />
            <Stat label="EDGES" value={stats.edgeCount.toLocaleString()} />
            <Stat label="SUBGRAPHS" value={stats.subgraphs} />
            <Stat label="MODULARITY" value={stats.modularity} />
          </div>
        </Panel>

        <Panel title="Anomaly cohort" right={<span className="mono text-amber text-xs">{cohort.quotient}%</span>}>
          <ProgressBar value={cohort.severePct} tone="danger" />
          <div className="flex justify-between text-[10px] text-muted mt-1.5">
            <span>Healthy {cohort.healthyPct}%</span>
            <span>Watch {cohort.watchPct}%</span>
            <span>Severe {cohort.severePct}%</span>
          </div>
        </Panel>

        <Panel title="Topology filters" right={<Badge>1 active</Badge>}>
          <div className="text-[10px] text-muted mb-1">Min flow threshold</div>
          <input
            type="range" min="0" max="10000" step="100" value={minFlow}
            onChange={(e) => setMinFlow(Number(e.target.value))}
            className="w-full accent-amber"
          />
          <div className="flex justify-between text-[10px] text-muted mt-1 mono">
            <span>0</span><span>{minFlow.toLocaleString()}</span><span>10k+</span>
          </div>
        </Panel>

        <Panel title="24h flow velocity" right={<span className="text-[10px] text-danger">peak {Math.max(...flowSeries)}/hr</span>}>
          <div className="flex items-end gap-0.5 h-14">
            {flowSeries.map((v, i) => (
              <div key={i} className="flex-1 bg-danger/60 rounded-sm" style={{ height: `${(v / maxFlow) * 100}%`, minHeight: v > 0 ? "2px" : 0 }} />
            ))}
          </div>
          <div className="flex justify-between text-[10px] text-muted mt-1">
            <span>-24h</span><span>now</span>
          </div>
        </Panel>
      </div>

      <Panel className="min-w-0 flex flex-col" title="Investigation focus" right={
        <div className="flex gap-3 text-[10px] text-muted">
          <span><span className="inline-block w-2 h-2 rounded-full bg-ok mr-1" />nominal</span>
          <span><span className="inline-block w-2 h-2 rounded-full bg-amber mr-1" />watchlist</span>
          <span><span className="inline-block w-2 h-2 rounded-full bg-danger mr-1" />flagged</span>
        </div>
      }>
        <div className="h-[calc(100vh-9rem)]">
          <ForceGraph2D
            graphData={graphData}
            nodeColor={nodeColor}
            nodeRelSize={3}
            linkColor={() => "rgba(122,135,148,0.2)"}
            backgroundColor="#0a0c0f"
            onNodeClick={(n) => setSelected(n.id)}
          />
        </div>
      </Panel>

      <div className="flex flex-col gap-3 overflow-auto pl-1">
        <Panel title="Active fraud rings" right={<Badge tone="danger">{rings.length} active</Badge>}>
          <div className="space-y-2 max-h-72 overflow-auto">
            {ringCards.map((r) => (
              <button
                key={r.id}
                onClick={() => setSelectedRing(r)}
                className={`w-full text-left border rounded-md p-2 transition ${
                  selectedRing?.id === r.id ? "border-danger bg-danger/5" : "border-line hover:border-line"
                }`}
              >
                <div className="flex justify-between items-start">
                  <div>
                    <div className="text-xs text-slate-100 mono">{r.id}</div>
                    <div className="text-[10px] text-muted capitalize">{r.pattern.replace("_", " ")}</div>
                  </div>
                  <Badge tone={r.score >= 70 ? "danger" : "amber"}>{r.score}/100</Badge>
                </div>
                <div className="flex gap-3 text-[10px] text-muted mt-1.5">
                  <span>Exposure ₹{(r.exposure / 1000).toFixed(0)}k</span>
                  <span>Nodes {r.nodes}</span>
                  <span>{r.velocity} tx</span>
                </div>
              </button>
            ))}
            {ringCards.length === 0 && <div className="text-muted text-xs">No active rings.</div>}
          </div>
        </Panel>

        <Panel title="Node inspector">
          {!selected && <div className="text-xs text-muted">Click a node to inspect it.</div>}
          {selected && <NodeInspector accountId={selected} />}
        </Panel>

        <Panel title="Live ingestion feed" right={<span className="text-[10px] text-ok">continuous</span>}>
          <div className="space-y-1 max-h-56 overflow-auto text-[10px] mono">
            {feed.map((t, i) => (
              <div key={i} className="flex justify-between border-b border-line py-1 last:border-0">
                <span className="text-muted">{t.sender_id?.slice(0, 10)}</span>
                <span className="text-slate-300">₹{t.amount?.toLocaleString?.()}</span>
                <span className="text-muted">{t.receiver_id?.slice(0, 10)}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function NodeInspector({ accountId }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setData(null); setErr(null);
    api.explain(accountId).then(setData).catch((e) => setErr(e.message));
  }, [accountId]);

  if (err) return <div className="text-xs text-muted">No score on file for {accountId}.</div>;
  if (!data) return <div className="text-xs text-muted">Loading…</div>;

  return (
    <div className="text-xs space-y-2">
      <div className="text-slate-200 mono">{data.account_id}</div>
      <div className="flex items-center gap-2">
        <span className="text-2xl font-semibold mono text-danger">
          {(data.model_score * 100).toFixed(1)}
        </span>
        <span className="text-muted">/ 100 risk</span>
      </div>
      <div className="text-muted leading-relaxed">{data.explanation}</div>
    </div>
  );
}
