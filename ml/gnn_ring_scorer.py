"""
Graph layer: build the transaction graph, run classical cycle /
community detection as an always-available baseline, and — if
torch_geometric is installed and a GPU is present — train a small GNN
to score subgraphs for "ring-likeness".

Design goal from the brief: this must be ADDITIVE. If torch/PyG aren't
available, `score_rings()` still returns a usable ring_membership_score
computed from networkx community + cycle structure alone, so the rest
of the app (API, frontend) never breaks.
"""
import sys
import numpy as np
import pandas as pd
import networkx as nx

sys.path.append("/app/simulation")
from exasol_conn import get_connection  # noqa: E402

try:
    import torch
    import torch.nn.functional as F
    from torch_geometric.data import Data
    from torch_geometric.nn import GraphSAGE
    TORCH_AVAILABLE = torch.cuda.is_available() or True  # allow CPU torch too
    HAS_PYG = True
except Exception:  # noqa: BLE001
    HAS_PYG = False


def load_transactions() -> pd.DataFrame:
    conn = get_connection()
    df = conn.export_to_pandas("SELECT sender_id, receiver_id, amount, txn_id FROM transactions")
    conn.close()
    return df


def build_graph(txns: pd.DataFrame) -> nx.DiGraph:
    G = nx.DiGraph()
    for _, row in txns.iterrows():
        G.add_edge(row["sender_id"], row["receiver_id"],
                    weight=float(row["amount"]), txn_id=row["txn_id"])
    return G


def heuristic_ring_scores(G: nx.DiGraph) -> pd.DataFrame:
    """
    Always-available fallback: combine
      - membership in a small strongly-connected component (mule loops)
      - Louvain-style community density (networkx greedy modularity)
      - in/out-degree imbalance (fan-in/fan-out hubs)
    into a 0-1 ring_membership_score per account.
    """
    scores = {n: 0.0 for n in G.nodes()}

    # 1) small strongly-connected components -> likely closed loops
    for scc in nx.strongly_connected_components(G):
        if 2 <= len(scc) <= 8:
            for n in scc:
                scores[n] = max(scores[n], 0.6)

    # 2) community density via greedy modularity on the undirected projection
    UG = G.to_undirected()
    try:
        communities = list(nx.algorithms.community.greedy_modularity_communities(UG))
        for comm in communities:
            if 3 <= len(comm) <= 20:
                sub = UG.subgraph(comm)
                density = nx.density(sub)
                for n in comm:
                    scores[n] = max(scores[n], min(1.0, density * 1.5))
    except Exception:  # noqa: BLE001
        pass

    # 3) fan-in / fan-out imbalance
    for n in G.nodes():
        in_deg = G.in_degree(n)
        out_deg = G.out_degree(n)
        total = in_deg + out_deg
        if total >= 6:
            imbalance = abs(in_deg - out_deg) / total
            hub_score = min(1.0, (total / 20.0)) * (0.5 + 0.5 * (1 - imbalance))
            scores[n] = max(scores[n], hub_score)

    return pd.DataFrame({"account_id": list(scores.keys()), "ring_membership_score": list(scores.values())})


def gnn_ring_scores(G: nx.DiGraph, fallback: pd.DataFrame) -> pd.DataFrame:
    """
    Small unsupervised GraphSAGE embedding + reconstruction-style anomaly
    score, used to refine the heuristic score when GPU/PyG is available.
    Trains for a handful of epochs — this is a hackathon demo model, not
    a production one.
    """
    if not HAS_PYG:
        print("[gnn_ring_scorer] torch_geometric not available; using heuristic scores only")
        return fallback

    try:
        nodes = list(G.nodes())
        idx = {n: i for i, n in enumerate(nodes)}
        edge_index = torch.tensor(
            [[idx[u] for u, v in G.edges()], [idx[v] for u, v in G.edges()]],
            dtype=torch.long,
        )
        # simple structural features: in-degree, out-degree, weighted strength
        x = torch.tensor(
            [[G.in_degree(n), G.out_degree(n),
              sum(d["weight"] for _, _, d in G.out_edges(n, data=True))]
             for n in nodes],
            dtype=torch.float,
        )
        x = (x - x.mean(0)) / (x.std(0) + 1e-6)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        data = Data(x=x, edge_index=edge_index).to(device)

        model = GraphSAGE(in_channels=x.shape[1], hidden_channels=16, num_layers=2, out_channels=8).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=0.01)

        model.train()
        for epoch in range(30):
            optimizer.zero_grad()
            z = model(data.x, data.edge_index)
            # unsupervised link-reconstruction loss (encourages structurally
            # similar / densely-connected nodes to embed close together)
            src, dst = data.edge_index
            pos_score = (z[src] * z[dst]).sum(dim=-1)
            neg_dst = dst[torch.randperm(dst.size(0))]
            neg_score = (z[src] * z[neg_dst]).sum(dim=-1)
            loss = F.softplus(neg_score - pos_score).mean()
            loss.backward()
            optimizer.step()

        model.eval()
        with torch.no_grad():
            z = model(data.x, data.edge_index).cpu().numpy()

        # anomaly proxy: embedding norm (tight, unusual substructures tend
        # to produce higher-magnitude embeddings under this loss) blended
        # with the heuristic score for stability
        norms = np.linalg.norm(z, axis=1)
        norms = (norms - norms.min()) / (norms.max() - norms.min() + 1e-9)
        gnn_df = pd.DataFrame({"account_id": nodes, "gnn_score": norms})

        merged = fallback.merge(gnn_df, on="account_id", how="left")
        merged["gnn_score"] = merged["gnn_score"].fillna(0)
        merged["ring_membership_score"] = (
            0.5 * merged["ring_membership_score"] + 0.5 * merged["gnn_score"]
        ).clip(0, 1)
        return merged[["account_id", "ring_membership_score"]]

    except Exception as e:  # noqa: BLE001
        print(f"[gnn_ring_scorer] GNN scoring failed ({e}); using heuristic scores only")
        return fallback


def detect_candidate_rings(G: nx.DiGraph, min_size=3, max_size=15):
    """Return list of {ring_members, pattern_guess} for the /rings endpoint & case-file panel."""
    rings = []
    for scc in nx.strongly_connected_components(G):
        if min_size <= len(scc) <= max_size:
            rings.append({"members": sorted(scc), "pattern_guess": "mule_loop"})
    UG = G.to_undirected()
    try:
        for comm in nx.algorithms.community.greedy_modularity_communities(UG):
            if min_size <= len(comm) <= max_size:
                rings.append({"members": sorted(comm), "pattern_guess": "cluster"})
    except Exception:  # noqa: BLE001
        pass
    return rings


def run() -> pd.DataFrame:
    txns = load_transactions()
    G = build_graph(txns)
    heuristic = heuristic_ring_scores(G)
    final = gnn_ring_scores(G, heuristic)
    return final


if __name__ == "__main__":
    scores = run()
    print(scores.sort_values("ring_membership_score", ascending=False).head(20))
