# Quickstart Guide

Complete setup guide: clone → install → download data → build → launch. Total
time from zero to a running app: **30-60 minutes** (most of which is the
pipeline build).

---

## System requirements

| Resource       | Minimum              | Recommended                          |
|----------------|----------------------|--------------------------------------|
| Python         | 3.11                 | 3.12                                 |
| RAM            | 4 GB                 | 8-16 GB (for full 2.2M LendingClub)  |
| Disk           | 3 GB free            | 5 GB free                            |
| OS             | Windows, macOS, Linux | Any with Python support             |
| Kaggle account | Not required         | Required for LendingClub download    |

**Note on RAM:** Building on the full LendingClub dataset (2.2M rows) comfortably
needs 8 GB of working memory. If you have 4 GB, the build still works but may
swap heavily. See the troubleshooting section for a workaround (reduce
`chunksize`).

**Note on Python version:** Python 3.11 and 3.12 are tested. Python 3.13 is
untested — some dependencies (xgboost, shap) may not have wheels yet.

---

## Step 1 — Clone the repository

```bash
git clone https://github.com/hammadmrza/credit-risk-platform.git
cd credit-risk-platform
```

---

## Step 2 — Create a Python virtual environment (recommended)

Isolating the project's dependencies prevents conflicts with other Python work.

**Windows (Command Prompt):**
```cmd
python -m venv venv
venv\Scripts\activate
```

**macOS / Linux:**
```bash
python -m venv venv
source venv/bin/activate
```

Your prompt should now show `(venv)` at the start, confirming the environment
is active.

---

## Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

Installs roughly 20 packages including `pandas`, `numpy`, `scikit-learn`,
`xgboost`, `optbinning`, `shap`, `streamlit`, `plotly`, `fastapi`, `uvicorn`.

**Expected time:** 3-8 minutes depending on network speed and whether any
packages need to compile from source.

If you see compilation errors on Windows, install the Microsoft C++ Build
Tools first: https://visualstudio.microsoft.com/visual-cpp-build-tools/

---

## Step 4 — Download the data (two datasets)

The repo does **not** include raw data — this is a licensing constraint.
You'll download it yourself in this step.

### 4a. LendingClub dataset (2.2M rows, ~1.5 GB)

1. Go to: https://www.kaggle.com/datasets/wordsforthewise/lending-club
2. Click **Download** (requires a free Kaggle account)
3. Unzip the downloaded file. You'll see `accepted_2007_to_2018Q4.csv.gz`
4. Decompress the `.gz` file using 7-Zip (Windows), `gunzip` (macOS/Linux), or
   any archive tool
5. **Rename** the resulting CSV to exactly `lending_club_loans.csv`
6. Place it at `data/raw/lending_club_loans.csv`

### 4b. FICO HELOC dataset (10K rows, ~660 KB)

**Preferred source:**
1. Go to: https://community.fico.com/s/explainable-machine-learning-challenge
2. Download `heloc_dataset_v1.csv`
3. Place it at `data/raw/heloc_dataset_v1.csv`

**Mirror if FICO link unavailable:**
1. Go to: https://www.kaggle.com/datasets/averkiyoliabev/home-equity-line-of-creditheloc
2. Download and place the file at `data/raw/heloc_dataset_v1.csv`

### 4c. Verify both files are in place

```bash
python -c "import config; print('LC:', config.LC_RAW_PATH.exists()); print('HELOC:', config.HELOC_RAW_PATH.exists())"
```

Expected output:
```
LC: True
HELOC: True
```

If either shows `False`, re-check the filenames. The loader expects exactly
`lending_club_loans.csv` and `heloc_dataset_v1.csv` — no variations.

---

## Step 5 — Run the build pipeline

```bash
python build.py
```

Runs the 7 core phases end-to-end. Expected wall time: **15-25 minutes** on a
modern laptop (8-core CPU, SSD, 16 GB RAM).

```
Phase 1   Data Acquisition & Harmonization         ~2 min
Phase 3   Feature Engineering & WoE Binning        ~3 min
Phase 4   Model Training (PD + LGD + EAD)          ~5 min
Phase 5   Explainable AI (SHAP + Fairness)         ~3 min
Phase 6   Regulatory & Compliance Analytics        ~2 min
Phase 9   Fraud Detection & Monitoring             ~3 min
```

**If the data files aren't found**, `build.py` automatically falls back to
synthetic data. You'll see a warning in the output. This is useful for CI
testing or when you want to explore the code without downloading 1.5 GB —
but the metrics will be illustrative, not measured.

Progress logs print to stdout. If interrupted (Ctrl+C, crash, timeout), resume
from any phase:

```bash
python build.py --from 4       # Resume starting from Phase 4
python build.py --phase 6      # Run only Phase 6
```

### About the phase numbering

The pipeline is organised into 9 logical phases, but only 7 are run by
`build.py`. The missing phases (2, 7, 8) are deliverables rather than
standalone scripts:

| Phase | Name                            | Where                                            |
|-------|---------------------------------|--------------------------------------------------|
| 1     | Data harmonization              | `notebooks/phase1/`                              |
| 2     | Exploratory data analysis       | Integrated into `src/data/eda_utils.py`          |
| 3     | Feature engineering             | `notebooks/phase3/`                              |
| 4     | Model training                  | `notebooks/phase4/`                              |
| 4b    | Segmented per-product models    | `notebooks/phase4b/` (optional, run separately)  |
| 5     | Explainability                  | `notebooks/phase5/`                              |
| 6     | Regulatory analytics            | `notebooks/phase6/`                              |
| 7     | FastAPI endpoint + Ollama LLM   | `src/api/` and `src/llm/`                        |
| 8     | Streamlit application           | `src/app/`                                       |
| 9     | Fraud detection                 | `notebooks/phase9/`                              |

---

## Step 6 — (Optional) Train the v1.1 segmented challenger models

The v1.1 per-product PD models are built separately to keep the main pipeline
focused. Running this populates real OOT AUC numbers in Tab 3, Section 3:

```bash
python notebooks/phase4b/04b_segmented_models.py
```

**Expected wall time:** 5-10 minutes.

Produces:
- `models/xgb_pd_unsecured.pkl`
- `models/xgb_pd_secured.pkl`
- `reports/phase4/model_comparison_segmented.csv`

See `MODEL_CARD.md` §"v1.1 Segmented Product Models" for why this is structured
as a challenger rather than a replacement.

---

## Step 7 — Launch the Streamlit app

```bash
streamlit run src/app/streamlit_app.py
```

Your browser opens at `http://localhost:8501`. Seven interactive tabs render:
Application Assessment, Batch Portfolio Scoring, Model Performance, Compliance,
Risk-Based Pricing, Fraud Monitoring, Executive Dashboard.

See `PRODUCT_GUIDE.md` for a complete tab-by-tab walkthrough.

---

## Step 8 — (Optional) Launch the FastAPI endpoint

For programmatic scoring from external systems (LOS integrations, batch
scoring jobs, mobile apps):

```bash
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

Once running:
- **Interactive Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
- **OpenAPI schema:** http://localhost:8000/openapi.json

See `API_GUIDE.md` for full endpoint reference with request/response schemas,
curl examples, and integration patterns.

---

## Step 9 — (Optional) Enable Ollama LLM for credit memos

The app uses Llama 3 locally via Ollama to draft credit memos and
adverse-action letters in plain English. Without Ollama, structured
templates are used — the app still works, just with less natural memo text.

**Why local LLM?** PIPEDA compliance. No applicant PII leaves your machine,
which is essential for Canadian lending deployments.

### Install Ollama

1. Download from https://ollama.ai (Windows, macOS, Linux installers available)
2. Install and launch

### Pull Llama 3 and start the server

```bash
ollama pull llama3      # One-time download, ~4.7 GB
ollama serve            # Starts the local server on port 11434
```

Re-run the Streamlit app. Memos and adverse-action letters now route through
Llama 3.

### Verify Ollama connectivity

```bash
curl http://localhost:11434/api/tags
```

Should return a JSON list including `llama3`. If you get "connection refused,"
Ollama isn't running.

---

## Post-build verification checklist

After the build completes and the app launches, confirm these to rule out
common issues:

- [ ] **Tab 1** — loan term dropdown shows only `[36, 60]` for Unsecured
      and only `[36]` for HELOC
- [ ] **Tab 2** — "Load Test Portfolio" populates 194K rows; 4 filters work
- [ ] **Tab 3 Section 1** — combined XGBoost OOT AUC displays (expected 0.67-0.72
      given the product-proxy issue documented in MODEL_CARD section 6)
- [ ] **Tab 3 Section 3** — v1.0 vs v1.1 segmented comparison renders
      (requires running Step 6 above)
- [ ] **Tab 3 Section 5** — calibration gap between mean-PD and actual-DR
      is under 2%
- [ ] **Tab 4** — Capital Adequacy Ratio (CAR) reads **11.50%** (not 26.87%)
- [ ] **Tab 4** — IFRS 9 stage rows colour-coded green/amber/red vs industry
      coverage bands
- [ ] **Tab 5** — profit curve renders with annotated profit-max threshold
- [ ] **Tab 6** — fraud trend chart and product by fraud-type breakdown render
- [ ] **Tab 7** — 7-column KPI row displays with CAR (assumed) at 11.50%

If any of these fail, see troubleshooting below.

---

## Resuming or re-running

The build is phase-based and each phase writes its own outputs. This means
you can re-run a specific phase without rebuilding everything:

```bash
python build.py --from 4       # Resume from Phase 4 onward
python build.py --phase 6      # Run only Phase 6 (e.g. to re-stress)
```

Each phase writes to `reports/phaseN/` and `models/` so subsequent phases
pick up where they left off.

---

## Troubleshooting

### Installation errors

**"pip install fails with 'Microsoft Visual C++ 14.0 or greater is required'"**
(Windows) — Install the Microsoft C++ Build Tools:
https://visualstudio.microsoft.com/visual-cpp-build-tools/

**"No matching distribution found for xgboost"** — Your Python version is
likely 3.13. Downgrade to 3.11 or 3.12, or wait for upstream wheels.

**"ERROR: Could not install packages due to an EnvironmentError"** — Your pip
doesn't have write permission. Try `pip install --user -r requirements.txt`.

### Data issues

**"LendingClub raw file not found"** — Filename must be exactly
`lending_club_loans.csv` in `data/raw/`. Check for extra extensions like
`.csv.csv` from unzipping.

**"These expected columns not found in file"** — Harmless warning. LendingClub
changed schema over the years; the loader uses only columns that exist.

**"Synthetic fallback used"** — Your data files aren't in `data/raw/`. Either
place them there and re-run, or continue with synthetic data (metrics will
be illustrative, not measured).

### Build errors

**Out of memory during Phase 1** — Reduce `chunksize` in
`src/data/lendingclub.py:77` from 50000 to 20000. Trades build time for RAM.

**Build stops at Phase N** — Scroll up for the actual error. Once fixed,
resume with `python build.py --from N`.

### App errors

**"Streamlit: Module not found"** — Your shell isn't in the virtual
environment. Activate it (Step 2) and reinstall.

**"Tab 4 shows CAR 26.87%"** — You're running older v1.0 code. Pull the
latest main branch and rebuild.

**"Profit curve is empty"** — Portfolio hasn't been scored yet. Run
`python build.py --from 4` to regenerate.

**"Segmented comparison not available"** — You haven't run Phase 4b yet.
See Step 6 above.

### LLM / Ollama errors

**"Ollama connection refused"** — Ollama server isn't running. Start with
`ollama serve` in a separate terminal. Or ignore — the app falls back to
templates automatically.

**"Memo generation slow (5+ seconds)"** — Llama 3 8B on CPU is slow. Set
`generate_memo=false` in the Streamlit app or switch to a smaller quantized
model (`llama3:7b-q4_0`).

---

## What's next

Once your app is running:

- Read **PRODUCT_GUIDE.md** for a tab-by-tab walkthrough and what each metric
  means in a credit-risk context
- Read **MODEL_CARD.md** for model governance details, v1.1 challenger, and
  limitations disclosure
- Read **CREDIT_POLICY.md** for the formal credit policy in real-lender voice
- Read **API_GUIDE.md** for FastAPI endpoint integration patterns

---

*QuickStart v1.1 · April 2026 · If you hit an issue not covered here, please
open a GitHub issue with your OS, Python version, and the full error message.*
