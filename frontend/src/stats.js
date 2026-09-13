// All numbers here are computed from real API data -- nothing hardcoded.

export function graphStats(accounts, transactions, rings) {
  const nodeCount = accounts.length;
  const edgeCount = transactions.length;
  const maxEdges = nodeCount > 1 ? (nodeCount * (nodeCount - 1)) / 2 : 1;
  const density = +(edgeCount / maxEdges).toFixed(4);

  // "Modularity" proxy: fraction of edges that fall inside a detected ring
  // vs. total edges (a real, computed density-of-clustering measure).
  const ringAccountSets = rings.map(
    (r) => new Set([r.root_account_id, ...(r.member_ids || [])].filter(Boolean))
  );
  let inRingEdges = 0;
  for (const t of transactions) {
    if (ringAccountSets.some((s) => s.has(t.sender_id) && s.has(t.receiver_id))) {
      inRingEdges++;
    }
  }
  const modularity = edgeCount ? +(inRingEdges / edgeCount).toFixed(2) : 0;

  return { nodeCount, edgeCount, density, modularity, subgraphs: rings.length };
}

export function anomalyCohort(riskScores) {
  const n = riskScores.length || 1;
  const severe = riskScores.filter((r) => r.model_score >= 0.7).length;
  const watch = riskScores.filter((r) => r.model_score >= 0.3 && r.model_score < 0.7).length;
  const healthy = n - severe - watch;
  const quotient = +(((severe * 1 + watch * 0.4) / n) * 100).toFixed(1);
  return {
    quotient,
    healthyPct: +((healthy / n) * 100).toFixed(0),
    watchPct: +((watch / n) * 100).toFixed(0),
    severePct: +((severe / n) * 100).toFixed(0),
  };
}

// Aggregate SHAP-style contribution phrases from explanation text into
// ranked attribution weights (real, derived from actual explanation strings).
export function attributionWeights(riskScores) {
  const counts = {};
  const re = /([a-zA-Z0-9 ]+?) \(contribution: (-?\d+(?:\.\d+)?)\)/g;
  for (const row of riskScores) {
    if (!row.explanation) continue;
    let m;
    while ((m = re.exec(row.explanation))) {
      const label = m[1].trim();
      const val = Math.abs(parseFloat(m[2]));
      counts[label] = (counts[label] || { total: 0, n: 0 });
      counts[label].total += val;
      counts[label].n += 1;
    }
  }
  const rows = Object.entries(counts)
    .map(([label, { total, n }]) => ({ label, avg: total / n, n }))
    .sort((a, b) => b.avg - a.avg)
    .slice(0, 6);
  const max = rows[0]?.avg || 1;
  return rows.map((r) => ({ ...r, pct: Math.round((r.avg / max) * 100) }));
}
