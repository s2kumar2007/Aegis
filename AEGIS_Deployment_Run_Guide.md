# AEGIS — Deployment & Run Guide

**Adaptive Graph-Based UPI Fraud Detection & Explainable Money-Trail Tracing**
Track: *Predict, Detect & Optimize*
**Repo:** https://github.com/s2kumar2007/Aegis
**Team:** 404 FOUNDERS

AEGIS detects coordinated multi-account UPI fraud rings (smurfing, layering, mule networks), explains *why* each account was flagged, and traces the full money trail. **Exasol Personal is the active computational core** — rolling-window velocity features and multi-hop path tracing are computed as SQL views inside the database, not recomputed in pandas.

---

## 1. Prerequisites

| Requirement | Notes |
|---|---|
| Docker + Docker Compose | Required for the app stack |
| Exasol Personal (Launcher CLI) | The hackathon mandates the **real Exasol Personal edition**, deployed via Exasol's Launcher CLI — **not** a local Docker container |
| GPU (optional) | NVIDIA Container Toolkit for `gpu_hist` XGBoost / GraphSAGE on CUDA. Both ML modules auto-detect and fall back to CPU, so this is optional for a demo |

---

## 2. Deploy Exasol Personal

This runs **outside** this repo, via Exasol's own installer:

```bash
curl https://downloads.exasol.com/exasol-personal/installer.sh | sh
mkdir deployment && cd deployment

# Choose your target: aws, azure, or local (macOS)
exasol install local

# Get your connection details
exasol info
```

You can also connect directly with `exasol connect` to inspect the instance.

---

## 3. Configure the Repo

```bash
git clone https://github.com/s2kumar2007/Aegis.git aegis
cd aegis

cp .env.example .env
```

Edit `.env` and fill in the real values from `exasol info`:

```env
EXASOL_HOST=<from exasol info>
EXASOL_PORT=<from exasol info>
EXASOL_USER=<from exasol info>
EXASOL_PASSWORD=<from exasol info>
```

---

## 4. One-Command Start

```bash
docker compose up -d
./run_demo.sh
```

`run_demo.sh` waits for services to be healthy, then does three things:

1. Runs `simulation/generate_data.py` inside the backend container — creates the Exasol schema/views and loads accounts, transactions, and fraud labels (normal traffic + planted smurfing/layering/mule rings).
2. Calls `POST /pipeline/run` — trains the baseline XGBoost classifier on `account_velocity_view`, scores ring membership via the graph/GNN layer, generates Bayesian explanations, and writes it all to `risk_scores`.
3. Tells you the UI is ready.

Open the War Room UI:
```
http://localhost:3000
```

---

## 5. Re-Running Things Manually

Re-run just the scoring pipeline (e.g. after the adaptive-loop demo adds new transactions):
```bash
curl -X POST http://localhost:8000/pipeline/run
```

Trigger the adaptive-loop stretch demo (rings mutate to smaller/slower transactions; the system logs a threshold adjustment):
```bash
curl -X POST http://localhost:8000/adapt/run
```

Re-apply a changed SQL view under `/sql` **without** re-seeding data:
```bash
docker exec -it aegis-backend python -c \
  "import sys; sys.path.append('/app/simulation'); from exasol_conn import get_connection, run_sql_file; \
   c = get_connection(); run_sql_file(c, '/app/sql/03_ring_trace_view.sql'); c.close()"
```

---

## 6. API Reference

| Endpoint | Description |
|---|---|
| `GET /accounts` | All simulated accounts |
| `GET /transactions?since=` | Transactions, optionally from a timestamp |
| `GET /risk-scores` | Per-account model + ring scores + explanation |
| `GET /rings` | Ring candidates from `ring_summary_view` |
| `GET /rings/{root_account_id}/trace` | Full hop-by-hop path (from `ring_trace_view`) |
| `GET /explain/{account_id}` | Bayesian plain-language explanation for one account |
| `POST /simulate/replay` | Resets the server-side replay cursor |
| `GET /timeline-state?t=` | Network snapshot as of simulated time `t` |
| `POST /pipeline/run` | Re-run baseline + graph + Bayesian scoring |
| `POST /adapt/run` | Run the adaptive-loop stretch scenario |

Sanity check:
```bash
curl http://localhost:8000/risk-scores
```

---

## 7. Why Exasol Is the Core, Not Just Storage

- **`account_velocity_view`** (`/sql/02_account_velocity_view.sql`) computes rolling 1h/24h/30d transaction counts, sums, averages, standard deviations, and z-score-style amount deviation — all via Exasol analytic window functions (`RANGE BETWEEN ... PRECEDING`). The backend `SELECT`s this view directly; these numbers are never recomputed in pandas.
- **`ring_trace_view`** (`/sql/03_ring_trace_view.sql`) is a **recursive CTE** that walks the transaction graph up to 5 hops forward in time, with cycle guards, entirely in SQL — this is how layering/mule chains are traced. This is the top-weighted piece of the hackathon brief.
- **`ring_summary_view`** aggregates those traces into ring candidates for the API and the UI's case-file panel.

---

## 8. Architecture

```
Data Simulation (generate_data.py)
        |  normal txns + planted rings
        v
Exasol Personal (computational core)
  accounts / transactions / fraud_labels
        |
        +--> account_velocity_view (rolling window SQL) --> baseline_classifier.py (GPU XGBoost)
        +--> ring_trace_view (recursive CTE, depth <= 5) --> ring_summary_view
        +--> transactions --> gnn_ring_scorer.py (networkx + GPU GraphSAGE)
        +--> account_velocity_view --> explainability.py (pgmpy Bayesian network)
                                                |
                            fraud_labels --> adaptive_loop.py --> adaptation_log
                                                |
                        risk_scores + ring_summary_view
                                                v
                              FastAPI backend (/accounts, /transactions,
                              /risk-scores, /rings, /explain/{id},
                              /simulate/replay, /timeline-state)
                                                v
                        React War Room (force-directed graph,
                              case file panel, time scrubber)
```

---

## 9. Build Order This Repo Follows

Each stage is additive — if you stop after step 4, `/risk-scores` still returns real, working baseline scores; the UI degrades gracefully (0 for `ring_membership_score`, generic explanation) rather than crashing.

1. **Infrastructure** — `docker-compose.yml`, one-command startup.
2. **Data simulation** — `simulation/generate_data.py`.
3. **Exasol SQL layer** — `sql/02_account_velocity_view.sql`, `sql/03_ring_trace_view.sql` (top-weighted piece).
4. **Detection: baseline** — `ml/baseline_classifier.py` (GPU XGBoost, CPU fallback). Always works.
5. **Detection: graph/GNN** — `ml/gnn_ring_scorer.py`. Falls back to a networkx-only heuristic score if `torch_geometric` isn't installed.
6. **Explainability** — `ml/explainability.py` (pgmpy Bayesian network).
7. **Adaptive loop (stretch)** — `ml/adaptive_loop.py`.
8. **Backend API** — `backend/main.py`.
9. **Frontend War Room** — `frontend/src/App.jsx`.

---

## 10. Repo Layout

```
/simulation   synthetic UPI data generator + Exasol connection helper
/sql          schema + the two mandatory Exasol views + ring summary view
/backend      FastAPI service (reads Exasol, exposes REST API)
/ml           baseline XGBoost, graph/GNN ring scorer, Bayesian explainability,
              adaptive loop, and the pipeline orchestrator that ties them together
/frontend     React "War Room" UI (force graph, case files, time scrubber)
```

---

## 11. Cloud Deployment Notes

Exasol Personal Edition is deployed via the Launcher CLI (`exasol install aws` / `exasol install azure`) — **not** via docker-compose.

- **Production scale**: for genuine production workloads, Exasol offers managed deployments (Exasol SaaS / cloud marketplaces) sized for multi-node clusters. Swap the `EXASOL_HOST`/port/credentials env vars to point the backend at that cluster — no application code changes needed, since all access goes through `pyexasol` using standard connection parameters.
- **Secrets**: put `EXASOL_PASSWORD` etc. in a secrets manager (AWS Secrets Manager / Azure Key Vault), not in `.env`, for anything beyond local demo use.
- **Statelessness**: the FastAPI backend is stateless aside from a small in-memory replay cursor — safe to run multiple replicas behind a load balancer; Exasol remains the single source of truth.
- **GPU**: `gpu_hist` XGBoost and GraphSAGE on CUDA need a GPU-backed instance (AWS `g4dn`/`g5`, Azure `NC`-series) with the NVIDIA Container Toolkit. Optional — both ML modules fall back to CPU automatically.

---

## 12. Troubleshooting (issues hit while building this)

| Symptom | Fix |
|---|---|
| `SSL: CERTIFICATE_VERIFY_FAILED` connecting to Exasol | `pyexasol.connect()` needs `encryption=True, websocket_sslopt={"cert_reqs": 0}` |
| `.env` values not picked up | Confirm `load_dotenv()` runs before any Exasol connection code |
| `ImportError: DiscreteBayesianNetwork` | `pgmpy==0.1.25` renamed this class — import `BayesianNetwork as DiscreteBayesianNetwork` |
| `export_to_pandas` fails with cert/TLS error | Upgrade to `pyexasol>=1.0.0` |
| Columns come back as `ACCOUNT_ID` instead of `account_id` | Exasol returns uppercase columns by default — lowercase them on read |
| A whole table/view silently missing after schema setup | Check `run_sql_file()`'s statement splitter isn't dropping statements that start with a `--` comment line |
| Bind parameters (`:param_name`) fail in `EXPORT` statements | Exasol's `EXPORT` doesn't support host/bind params — use quote-escaped f-string interpolation |

### Exasol SQL dialect notes (if writing new views)
- `ring_trace_view` uses a recursive CTE; if you hit limits on multi-hop tracing, `CONNECT BY` / `START WITH` / `CONNECT_BY_ROOT` / `SYS_CONNECT_BY_PATH` is the fallback hierarchical syntax.
- `PATH` is a reserved keyword — use `route` instead.
- `CONNECT BY` can't mix an equality `PRIOR` condition with a non-equal comparison in the same clause.
- Filters on `LEVEL`-derived columns must sit in an outer wrapping subquery, not inline after `CONNECT BY`.
- No `LIMIT`/`FETCH FIRST` inside a correlated subquery — use `ROW_NUMBER() OVER (...)` + `MAX(CASE WHEN rn = 1 THEN ... END)`.
- `COUNT(DISTINCT ...) OVER (... RANGE ...)` isn't allowed — use `PARTITION BY` with an hour-bucket instead of a moving time window.

---

## 13. Shutting Down / Resetting

```bash
docker compose down            # stop containers, keep data
docker compose down -v         # stop containers and wipe local volumes (full reset)
```
