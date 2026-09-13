# AEGIS — Deployment & Run Guide

**Project:** Multi-Layer UPI Fraud Detection
**Repo:** https://github.com/s2kumar2007/Aegis
**Team:** 404 FOUNDERS

This guide covers local deployment on **Windows + WSL2 + Docker Desktop**, the environment AEGIS is built and verified against (the original Azure deployment path is not required and is documented only as background at the end).

---

## 1. Prerequisites

| Requirement | Notes |
|---|---|
| Windows 10/11 | with WSL2 enabled |
| WSL2 (Ubuntu) | `wsl --install -d Ubuntu` if not already set up |
| Docker Desktop | with **WSL2 integration** enabled for your Ubuntu distro (Settings → Resources → WSL Integration) |
| Python 3.10+ | inside WSL, for the venv |
| Node.js + npm | inside WSL, required to build the frontend (see §5) |
| Git | inside WSL |

Verify Docker is reachable from inside WSL before continuing:
```bash
docker ps
```
If this fails, fix the WSL↔Docker integration in Docker Desktop settings first — nothing else will work until `docker` resolves inside WSL.

---

## 2. Clone & Python Environment

```bash
git clone https://github.com/s2kumar2007/Aegis.git
cd Aegis

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
# Optional, only if you want GNN-based ring scoring:
pip install -r requirements-gnn.txt
```

> The Dockerfile installs a **CPU-only torch wheel** for `requirements-gnn.txt` — GPU is not needed at this data scale.

---

## 3. Environment Variables

Create a `.env` file at the project root (loaded via `load_dotenv()`):

```env
EXASOL_HOST=127.0.0.1
EXASOL_PORT=8563
EXASOL_USER=sys
EXASOL_PASSWORD=exasol
EXASOL_SCHEMA=aegis
```

**Important Docker-specific override:** inside the `aegis-backend` container, `127.0.0.1` refers to the container itself, not the host running Exasol. `docker-compose.yml` already overrides this for you:

```yaml
services:
  aegis-backend:
    environment:
      - EXASOL_HOST=host.docker.internal
```

Only edit this if you rename services or change networking — the default compose file handles it.

---

## 4. Start the Stack

```bash
docker compose up -d --build
```

This brings up four containers:

| Container | Role |
|---|---|
| `aegis-exasol` | Exasol (via `exasol/nano` image), local system of record, `127.0.0.1:8563` |
| `aegis-db-init` | Runs schema/setup SQL against Exasol on first boot |
| `aegis-backend` | FastAPI service + ML pipeline |
| `aegis-frontend` | React "War Room" dashboard, served via nginx |

Check everything is healthy:
```bash
docker compose ps
docker compose logs -f aegis-exasol   # wait for Exasol to report ready
docker compose logs -f aegis-backend
```

---

## 5. Building the Frontend (manual step — currently required)

`frontend/Dockerfile` expects a **pre-built** `dist/` folder — it does `COPY dist /usr/share/nginx/html` rather than building inside Docker. You must build locally first:

```bash
cd frontend
npm install
npm run build      # produces frontend/dist/
cd ..

docker compose up -d --build aegis-frontend
```

If `npm`/`node` aren't available in WSL yet:
```bash
sudo apt update
sudo apt install -y nodejs npm
# or, for a specific LTS version, use nvm:
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
nvm install --lts
```

---

## 6. Run the ML Pipeline

Once the stack is up and the frontend is built:

```bash
docker exec -it aegis-backend python ml/pipeline.py
```

Expected: the pipeline trains the XGBoost classifier, runs the graph-based ring scorer, trains the autoencoder, computes SHAP explanations, and writes rows (≈4,700 in the reference run) into the `risk_scores` table in Exasol.

---

## 7. Verify the API

```bash
curl http://localhost:8000/risk-scores
```
Should return well-formed JSON with fraud-risk scores and explanations per transaction.

Open the dashboard at:
```
http://localhost:3000
```
(or whatever port `aegis-frontend` is mapped to in `docker-compose.yml`)

---

## 8. Common Issues & Fixes

These are the real issues hit while standing this project up — check here first if something breaks.

| Symptom | Fix |
|---|---|
| `SSL: CERTIFICATE_VERIFY_FAILED` connecting to Exasol | Ensure `pyexasol.connect()` is called with `encryption=True, websocket_sslopt={"cert_reqs": 0}` |
| `.env` values not picked up | Confirm `load_dotenv()` runs before any Exasol connection code |
| Local (non-Docker) script fails on file paths | `generate_data.py` uses relative `sql/...` paths, not `/app/sql/...` — run it from the project root |
| Backend can't reach Exasol inside Docker | `EXASOL_HOST` must be `host.docker.internal` inside containers, not `127.0.0.1` |
| GNN import errors on build | Make sure `requirements-gnn.txt` is copied in the Dockerfile and CPU-only torch wheel is used |
| `ImportError: DiscreteBayesianNetwork` | `pgmpy==0.1.25` renamed this class — import `BayesianNetwork as DiscreteBayesianNetwork` |
| `export_to_pandas` fails with cert/TLS error | Upgrade to `pyexasol>=1.0.0` (older versions don't support Exasol's newer ETL TLS requirement) |
| pyexasol crashes on version string `2026.2.0-nano.3` | Known non-PEP440 version from `exasol/nano`; a monkey-patch on `ExaConnection.exasol_db_version` fixes it (already applied in this repo) |
| Columns come back as `ACCOUNT_ID` instead of `account_id` | Exasol returns uppercase columns by default; `export_to_pandas` is patched to lowercase them globally |
| A whole table silently missing after schema setup | `run_sql_file()`'s statement splitter used to drop any statement starting with a `--` comment line — strip comment-only lines before splitting on `;` |
| `KeyError: device_ip_reuse_count` | Column never existed — already removed from `FEATURE_COLS` |
| Autoencoder write fails on `risk_scores` insert | Table needs a 6th column, `anomaly_score DOUBLE` |
| Bind parameters (`:param_name`) fail in `EXPORT` statements | Exasol's `EXPORT` doesn't support host/bind params — use quote-escaped f-string interpolation instead (already applied in `backend/main.py`) |
| Frontend hits `/transactions&limit=5000` (missing `?`) | Fixed upstream — pull latest `frontend/` code |

### Exasol SQL dialect notes (if writing new queries)
- No `WITH RECURSIVE` — use `CONNECT BY` / `START WITH` / `CONNECT_BY_ROOT` / `SYS_CONNECT_BY_PATH` for multi-hop ring tracing.
- `PATH` is reserved — use `route` instead.
- `CONNECT BY` can't mix an equality `PRIOR` condition with a non-equal comparison in the same clause.
- Filters on `LEVEL`-derived columns must sit in an outer wrapping subquery, not inline after `CONNECT BY`.
- No `LIMIT`/`FETCH FIRST` inside a correlated subquery — use `ROW_NUMBER() OVER (...)` + `MAX(CASE WHEN rn = 1 THEN ... END)`.
- `COUNT(DISTINCT ...) OVER (... RANGE ...)` isn't allowed — use `PARTITION BY` with an hour-bucket instead of a moving time window.

---

## 9. Shutting Down / Resetting

```bash
docker compose down            # stop containers, keep data
docker compose down -v         # stop containers and wipe Exasol volume (full reset)
```

---

## 10. Background: Deployment Path

Cloud deployment on Azure was attempted first but blocked by `--location` config errors and `Standard_D4s_v3` SKU capacity failures in two regions (Central India, East US) — consistent with a subscription-level quota block. The project pivoted to the local WSL2 + Docker Desktop path described above using Exasol Personal's official starter-kit installer, which is the supported path for this repo going forward.
