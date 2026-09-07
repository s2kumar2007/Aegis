# Deployment Guide

## Deploying Exasol Personal

The hackathon mandates the real Exasol Personal edition, deployed via Exasol's Launcher CLI (not a local Docker container).

To deploy Exasol Personal outside this repo:

```bash
curl https://downloads.exasol.com/exasol-personal/installer.sh | sh
mkdir deployment && cd deployment
# Choose your target: aws, azure, or local (macOS)
exasol install local
# Get your connection details:
exasol info
```

Once deployed, point this repository to your Exasol instance:
1. Copy `.env.example` to `.env` in the repo root.
2. Fill in the `EXASOL_HOST`, `EXASOL_PORT`, `EXASOL_USER`, and `EXASOL_PASSWORD` values provided by `exasol info`.
3. You can also connect directly to the database using `exasol connect`.

### Manually re-applying the SQL layer

If you change a view definition under `/sql`, re-apply it without
re-seeding data:

```bash
docker exec -it aegis-backend python -c \
  "import sys; sys.path.append('/app/simulation'); from exasol_conn import get_connection, run_sql_file; \
   c = get_connection(); run_sql_file(c, '/app/sql/03_ring_trace_view.sql'); c.close()"
```

---

## Cloud deployment notes (AWS / Azure)

Exasol Personal Edition is deployed via the Launcher CLI (e.g. `exasol install aws` or `exasol install azure`). It is **not** deployed via docker-compose.

### Exasol's managed offering for real workloads
- For genuine production scale, Exasol offers managed deployments
  (Exasol SaaS / on cloud marketplaces) sized for multi-node clusters.
  Swap the `EXASOL_HOST`/port/credentials env vars to point the backend
  at that cluster — no application code changes needed, since all access
  goes through `pyexasol` using standard connection parameters.

### Regardless of option
- Put secrets (`EXASOL_PASSWORD`, etc.) in a secrets manager (AWS Secrets
  Manager / Azure Key Vault), not in `.env`, for anything
  beyond local demo use.
- The FastAPI backend is stateless aside from the small in-memory replay
  cursor — safe to run multiple replicas behind a load balancer if needed;
  Exasol remains the single source of truth.
- GPU training (XGBoost `gpu_hist`, GraphSAGE on CUDA) requires a GPU-backed
  instance (`AWS` `g4dn`/`g5`, `Azure` `NC`-series) with the NVIDIA
  Container Toolkit installed; both ML modules auto-detect and fall back to
  CPU if no GPU is present, so this is optional for a demo.
