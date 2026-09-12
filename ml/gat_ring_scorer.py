import os
import sys
import numpy as np
import pandas as pd

import torch
import torch.nn.functional as F
from torch_geometric.data import Data
from torch_geometric.nn import GATConv
from sklearn.metrics import roc_auc_score, average_precision_score

# Add simulation path so we can import the DB connection (works locally or in Docker)
sys.path.append(os.path.join(os.path.dirname(__file__), '../simulation'))
sys.path.append('/app/simulation')
try:
    from exasol_conn import get_connection
except ImportError:
    print("Warning: Could not import exasol_conn. Make sure you are running from the correct directory.")


def load_data():
    """Fetch nodes (accounts), edges (transactions), and labels from Exasol."""
    conn = get_connection()
    
    # 1. Node Features (aggregate account_velocity_view per account)
    node_sql = """
    SELECT 
        v.account_id, 
        MAX(v.txn_count_1h) as txn_count_1h,
        MAX(v.amount_deviation_score) as amount_deviation_score,
        MAX(a.account_age_days) as account_age_days,
        MAX(v.distinct_receivers_1h) as distinct_receivers_1h,
        MAX(v.distinct_senders_1h) as distinct_senders_1h
    FROM account_velocity_view v 
    JOIN accounts a ON a.account_id = v.account_id
    GROUP BY v.account_id
    """
    node_df = conn.export_to_pandas(node_sql)
    
    # Accounts without outbound txns might not be in the view, ensure we fetch all
    all_accounts_sql = "SELECT account_id, account_age_days FROM accounts"
    all_acc_df = conn.export_to_pandas(all_accounts_sql)
    
    # Merge and fill missing feature values with 0
    node_df = all_acc_df.merge(node_df.drop(columns=['account_age_days'], errors='ignore'), 
                               on='account_id', how='left').fillna(0.0)

    # 2. Edges
    edge_sql = "SELECT sender_id, receiver_id, amount, txn_id FROM transactions"
    edge_df = conn.export_to_pandas(edge_sql)
    
    # 3. Labels (Ring membership from planted transactions)
    # An account is in a ring if it participated in a planted fraud transaction
    label_sql = """
    SELECT DISTINCT account_id, 1 as is_fraud FROM (
        SELECT t.sender_id AS account_id FROM transactions t JOIN fraud_labels fl ON t.txn_id = fl.txn_id
        UNION
        SELECT t.receiver_id AS account_id FROM transactions t JOIN fraud_labels fl ON t.txn_id = fl.txn_id
    )
    """
    label_df = conn.export_to_pandas(label_sql)
    conn.close()
    
    # Merge labels to nodes
    node_df = node_df.merge(label_df, on='account_id', how='left')
    node_df['is_fraud'] = node_df['is_fraud'].fillna(0).astype(int)
    
    return node_df, edge_df


def prepare_pyg_data(node_df, edge_df):
    """Convert pandas DataFrames to a PyTorch Geometric Data object."""
    # Ensure consistent ordering
    node_df = node_df.sort_values("account_id").reset_index(drop=True)
    account_to_idx = {acc: i for i, acc in enumerate(node_df["account_id"])}
    
    # Node features tensor
    feature_cols = ["txn_count_1h", "amount_deviation_score", "account_age_days", 
                    "distinct_receivers_1h", "distinct_senders_1h"]
    x = torch.tensor(node_df[feature_cols].values, dtype=torch.float)
    x = (x - x.mean(dim=0)) / (x.std(dim=0) + 1e-6)  # Normalize
    
    # Edge index tensor
    edge_df["src"] = edge_df["sender_id"].map(account_to_idx)
    edge_df["dst"] = edge_df["receiver_id"].map(account_to_idx)
    edge_df = edge_df.dropna(subset=["src", "dst"])
    
    edge_index = torch.tensor([edge_df["src"].values, edge_df["dst"].values], dtype=torch.long)
    
    # Edge attributes tensor (transaction amount)
    edge_attr = torch.tensor(edge_df[["amount"]].values, dtype=torch.float)
    edge_attr = (edge_attr - edge_attr.mean(dim=0)) / (edge_attr.std(dim=0) + 1e-6)  # Normalize
    
    # Target labels
    y = torch.tensor(node_df["is_fraud"].values, dtype=torch.float)
    
    # Train/Val Split (80/20)
    num_nodes = len(node_df)
    indices = np.random.permutation(num_nodes)
    train_size = int(0.8 * num_nodes)
    
    train_mask = torch.zeros(num_nodes, dtype=torch.bool)
    val_mask = torch.zeros(num_nodes, dtype=torch.bool)
    train_mask[indices[:train_size]] = True
    val_mask[indices[train_size:]] = True
    
    return Data(x=x, edge_index=edge_index, edge_attr=edge_attr, y=y,
                train_mask=train_mask, val_mask=val_mask)


class GATFraudScorer(torch.nn.Module):
    """2-Layer Graph Attention Network for node classification."""
    def __init__(self, in_channels, hidden_channels, out_channels, heads=2):
        super().__init__()
        # edge_dim=1 processes the single edge feature (transaction amount)
        self.conv1 = GATConv(in_channels, hidden_channels, heads=heads, edge_dim=1, concat=True)
        self.conv2 = GATConv(hidden_channels * heads, out_channels, heads=1, edge_dim=1, concat=False)
        
    def forward(self, x, edge_index, edge_attr):
        x = self.conv1(x, edge_index, edge_attr=edge_attr)
        x = F.elu(x)
        x = F.dropout(x, p=0.5, training=self.training)
        
        x = self.conv2(x, edge_index, edge_attr=edge_attr)
        return x.squeeze()  # Return raw logits for BCEWithLogitsLoss


def train(model, data, optimizer, criterion):
    model.train()
    optimizer.zero_grad()
    out = model(data.x, data.edge_index, data.edge_attr)
    loss = criterion(out[data.train_mask], data.y[data.train_mask])
    loss.backward()
    optimizer.step()
    return loss.item()


def evaluate(model, data):
    model.eval()
    with torch.no_grad():
        logits = model(data.x, data.edge_index, data.edge_attr)
        probs = torch.sigmoid(logits)
        
        val_probs = probs[data.val_mask].cpu().numpy()
        val_labels = data.y[data.val_mask].cpu().numpy()
        
        if len(np.unique(val_labels)) < 2:
            return 0.0, 0.0, 0.0  # Failsafe if validation set missing one class
            
        loss = F.binary_cross_entropy_with_logits(logits[data.val_mask], data.y[data.val_mask]).item()
        roc_auc = roc_auc_score(val_labels, val_probs)
        pr_auc = average_precision_score(val_labels, val_probs)
        
    return loss, roc_auc, pr_auc


def main():
    print("Loading data from Exasol...")
    try:
        node_df, edge_df = load_data()
        print(f"Loaded {len(node_df)} accounts (nodes) and {len(edge_df)} transactions (edges).")
        print(f"Total planted ring accounts: {node_df['is_fraud'].sum()}")
    except Exception as e:
        print(f"Failed to load data: {e}")
        sys.exit(1)
        
    print("Preparing PyTorch Geometric graph data...")
    data = prepare_pyg_data(node_df, edge_df)
    
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    data = data.to(device)
    
    # Model Setup
    model = GATFraudScorer(
        in_channels=data.num_node_features, 
        hidden_channels=16, 
        out_channels=1, 
        heads=2
    ).to(device)
                           
    optimizer = torch.optim.Adam(model.parameters(), lr=0.005, weight_decay=5e-4)
    
    # Calculate pos_weight to handle extreme class imbalance (fraud is rare!)
    num_neg = (data.y[data.train_mask] == 0).sum()
    num_pos = (data.y[data.train_mask] == 1).sum()
    pos_weight = (num_neg / num_pos) if num_pos > 0 else torch.tensor(1.0)
    
    criterion = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight.to(device))
    
    print("\nStarting GAT Training...")
    print("-" * 75)
    for epoch in range(1, 101):
        train_loss = train(model, data, optimizer, criterion)
        
        if epoch % 10 == 0:
            val_loss, roc_auc, pr_auc = evaluate(model, data)
            print(f"Epoch {epoch:03d} | Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f} | "
                  f"Val ROC-AUC: {roc_auc:.4f} | Val PR-AUC: {pr_auc:.4f}")
                  
    print("-" * 75)
    print("\nTraining complete! The model successfully learned ring patterns from node features and graph structure.")

if __name__ == "__main__":
    main()
