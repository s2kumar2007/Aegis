# Deployment Guide

## Running Exasol Personal locally (what `docker-compose.yml` does)

Exasol Personal Edition ships as a single-node Docker image
(`exasol/docker-db`). Key points for local/demo use:

- **Resources**: give Docker at least 4 CPU cores and 8GB RAM headroom;
  Exasol itself wants ~4-6GB. On a laptop, close other heavy containers
  first.
- **Privileged mode**: the official image requires `privileged: true`
  (it manages its own virtual block devices internally) — already set in
  `docker-compose.yml`.
- **First boot time**: allow 60-90 seconds after the container reports
  "healthy" before the SQL port actually accepts queries — `run_demo.sh`
  and `simulation/exasol_conn.py` both retry with backoff to absorb this.
- **Default credentials**: `sys` / `exasol` (set via `EXASOL_USER` /
  `EXASOL_PASSWORD` env vars in `docker-compose.yml`; change these for
  anything beyond a local demo).
- **Persistence**: the `exasol_data` named volume persists data across
  `docker compose down` / `up`. Use `docker compose down -v` to fully
  reset and re-seed.
- **EXAoperation UI**: reachable at `http://localhost:2580` if you want to
  inspect the cluster/database state visually.
- **Client access**: any Exasol-compatible SQL client (DBeaver, DataGrip,
  `pyexasol`) can connect to `localhost:8563` with the credentials above.

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

Exasol Personal Edition is licensed and sized for local/dev use (single
node, capped data volume) — it is **not** the artifact you'd lift-and-shift
to production. For a cloud deployment, two paths:

### Option A — keep Exasol containerized on a VM
- Provision a VM with enough RAM (`AWS`: e.g. `r6i.xlarge`+/ `Azure`:
  `E4s_v5`+) and run the same `docker-compose.yml` there.
- Put the FastAPI backend and Exasol on the same private subnet/VNet;
  only expose the frontend (and optionally the API) behind a load
  balancer / reverse proxy with TLS.
- This preserves the exact demo architecture — good for a hosted hackathon
  demo, not for real production fraud-detection volume.

### Option B — Exasol's managed offering for real workloads
- For genuine production scale, Exasol offers managed deployments
  (Exasol SaaS / on cloud marketplaces) sized for multi-node clusters.
  Swap the `EXASOL_HOST`/port/credentials env vars to point the backend
  at that cluster — no application code changes needed, since all access
  goes through `pyexasol` using standard connection parameters.

### Regardless of option
- Put secrets (`EXASOL_PASSWORD`, etc.) in a secrets manager (AWS Secrets
  Manager / Azure Key Vault), not in `docker-compose.yml`, for anything
  beyond local demo use.
- The FastAPI backend is stateless aside from the small in-memory replay
  cursor — safe to run multiple replicas behind a load balancer if needed;
  Exasol remains the single source of truth.
- GPU training (XGBoost `gpu_hist`, GraphSAGE on CUDA) requires a GPU-backed
  instance (`AWS` `g4dn`/`g5`, `Azure` `NC`-series) with the NVIDIA
  Container Toolkit installed; both ML modules auto-detect and fall back to
  CPU if no GPU is present, so this is optional for a demo.
