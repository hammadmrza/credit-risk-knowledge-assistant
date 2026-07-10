# API Guide — Credit Risk & Fraud Detection Platform

Version 1.1 · FastAPI Endpoint Reference

---

## 1. Overview

The platform exposes a FastAPI HTTP endpoint (`src/api/main.py`) that wraps the
full decisioning pipeline. External systems — Loan Origination Systems (LOS),
mobile apps, CRM integrations — can POST a loan application and receive a fully
scored decision with all regulatory artifacts in one call.

The API applies the same **hierarchical decision engine** as the Streamlit app:

```
POST /score
  │
  ├─ Gate 1: Fraud screening (decline if fraud > 65%)
  ├─ Gate 2: Hard policy rules (decline on any rule breach)
  ├─ Gate 3: Credit model scoring (PD via XGBoost + Platt)
  ├─ Gate 4: Decision band (PD ≤ 28% approve, 28-35% refer, > 35% decline)
  └─ Response: full regulatory + explainability payload
```

The response is a single JSON object containing the decision code, PD/LGD/EAD,
Basel III RWA, IFRS 9 stage and ECL, SHAP feature attributions, ECOA-compliant
adverse-action reasons, and (optionally) an LLM-drafted credit memo.

**Latency target:** < 500 ms per application on commodity hardware (4-core
laptop, 8 GB RAM). Measured `latency_ms` is returned in every response.

---

## 2. Starting the server

```bash
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

Once running:

- **Interactive Swagger UI:** `http://localhost:8000/docs`
- **ReDoc documentation:** `http://localhost:8000/redoc`
- **OpenAPI JSON schema:** `http://localhost:8000/openapi.json`

The interactive Swagger UI is the fastest way to explore the API — you can
click "Try it out" on any endpoint, fill in the schema, and see a live
response without writing any client code.

---

## 3. Endpoint reference

### 3.1 `POST /score` — Score a single applicant

The main endpoint. Runs the full 12-step pipeline and returns a complete decision.

#### Request schema

| Field                      | Type    | Required | Default   | Constraints              | Description                                              |
|----------------------------|---------|----------|-----------|--------------------------|----------------------------------------------------------|
| `loan_amount`              | float   | Yes      | —         | `> 0`, `<= 500,000`      | Requested principal in dollars                           |
| `annual_income`            | float   | Yes      | —         | `> 0`                    | Applicant's gross annual income                          |
| `dti`                      | float   | Yes      | —         | `0 <= dti <= 100`        | Debt-to-income ratio as a percentage                     |
| `credit_score`             | float   | Yes      | —         | `300 <= score <= 850`    | FICO-equivalent bureau score                             |
| `employment_length_years`  | float   | No       | `3.0`     | `0 <= x <= 40`           | Years at current employer                                |
| `product_type`             | int     | No       | `0`       | `0` or `1`               | 0 = Unsecured Personal Loan, 1 = HELOC                   |
| `loan_term_months`         | float   | No       | `36.0`    | —                        | Term in months. Standardised to 36 for HELOC internally  |
| `credit_utilization`       | float   | No       | `null`    | `0 <= x <= 100`          | Revolving balance / limit as a percentage                |
| `num_derogatory_marks`     | float   | No       | `0.0`     | `>= 0`                   | Bankruptcies + charge-offs + collections                 |
| `num_inquiries_last_6m`    | float   | No       | `0.0`     | `>= 0`                   | Hard credit inquiries in last 6 months                   |
| `total_accounts`           | float   | No       | `10.0`    | `>= 0`                   | Total credit accounts ever opened                        |
| `ltv_ratio`                | float   | No       | `null`    | `0 <= ltv <= 1`          | Loan-to-value ratio. Required for HELOC (product_type=1) |
| `alt_data_score`           | float   | No       | `50.0`    | `0 <= score <= 100`      | Alternative data composite (rent/telco/utility proxy)    |
| `thin_file_flag`           | bool    | No       | `false`   | —                        | Fewer than 3 credit accounts on file                     |
| `applicant_name`           | string  | No       | `"Applicant"` | —                    | First name; used in adverse-action letter salutation     |
| `generate_memo`            | bool    | No       | `true`    | —                        | Whether to invoke the LLM for credit memo generation     |

#### Response schema

The response is a `ScoreResponse` object containing **seven groups** of fields:

**Decision**
- `decision` — `"APPROVE"` | `"REFER"` | `"DECLINE_CREDIT"` | `"DECLINE_POLICY"` | `"DECLINE_FRAUD"`
- `decision_reason` — Plain-language summary
- `policy_failures` — List of failed hard-policy rules (empty unless DECLINE_POLICY)
- `approval_threshold` — The PD threshold used (0.28)
- `refer_band_lower` — Lower bound of the refer band (0.28)
- `model_version` — `"v1.0-unified"` or `"v1.1-segmented"`

**Fraud**
- `fraud_score` — Fraud probability, 0.0-1.0
- `fraud_alert_tier` — `"CONFIRMED"` | `"HIGH"` | `"MEDIUM"` | `"LOW"`

**PD (Probability of Default)**
- `pd_score` — Point-in-time PD, 0.0-1.0, calibrated via Platt scaling
- `pd_ttc` — Through-the-cycle PD for Basel III capital computation
- `risk_score` — Internal PDO-scale score, integer 300-850
- `risk_tier` — `"A"` | `"B"` | `"C"` | `"D"` | `"E"`

**Loss components**
- `lgd` — Loss Given Default, 0.0-1.0
- `ead` — Exposure at Default, in dollars
- `expected_loss` — PD × LGD × EAD, in dollars

**Regulatory metrics**
- `rwa` — Basel III Risk-Weighted Assets, in dollars
- `min_capital` — 8% × RWA, in dollars
- `ifrs9_stage` — `1`, `2`, or `3`
- `ecl` — Expected Credit Loss provision, in dollars
- `risk_based_rate` — Recommended APR as a decimal (e.g. 0.1285 for 12.85%)

**Explanation**
- `shap_factors` — List of top SHAP contributions, each a `{feature, value, shap_impact, direction}` object
- `adverse_reasons` — ECOA-compliant adverse-action reason strings (populated on DECLINE/REFER)

**Memo and diagnostics**
- `credit_memo` — LLM-drafted memo text (or template fallback). `null` if `generate_memo=false`
- `latency_ms` — End-to-end pipeline latency in milliseconds

---

### 3.2 `POST /score/batch` — Batch scoring via CSV upload

Upload a CSV file with multiple loan applications. Each row is scored
independently through the same pipeline as `/score`. Returns a JSON array of
`ScoreResponse` objects, one per input row (with an `error` field on rows that
failed scoring).

**Request:** Multipart form-data with a CSV file attached under the `file` field.

**Required CSV columns:** `loan_amount`, `annual_income`, `dti`, `credit_score`,
`employment_length_years`, `product_type`.

**Optional CSV columns:** any of the optional fields listed in §3.1. Missing
columns get their default values.

**Response:** Array of `ScoreResponse` objects, plus a summary header with
`total_rows`, `scored_successfully`, `failed`.

---

### 3.3 `GET /health` — Health check

Returns model-load status and API readiness. Use this as the liveness probe in
a Kubernetes deployment or load-balancer health check.

**Response:**
```json
{
  "status": "healthy",
  "models_loaded": true,
  "ollama_available": true,
  "uptime_seconds": 3627.42
}
```

`status` is `"healthy"` only when all models load successfully.
`ollama_available` is `true` only if the Ollama LLM server responds on its
expected port (11434 by default).

---

### 3.4 `GET /model/info` — Model metadata

Returns metadata about the deployed models: version, training data provenance,
features used, decision thresholds, and calibration method.

**Response includes:**
- `model_version` (e.g. `"v1.0-unified"`)
- `training_data` (dataset names, row counts, training date)
- `features_used` — List of 10 selected features
- `calibration_method` — `"Platt scaling"`
- `decision_thresholds` — `approval`, `refer_band_lower`, `fraud_decline`
- `segmented_models_available` — Boolean, `true` if v1.1 segmented models are loaded
- `next_review_date`

Use this to validate from a client that the model version they're targeting is
still live and hasn't silently been changed.

---

### 3.5 `GET /ollama/status` — LLM availability

Checks whether Ollama is running and Llama 3 is pulled. Useful if your client
wants to decide whether to request memo generation (which slows down scoring
by 2-5 seconds).

**Response:**
```json
{
  "ollama_reachable": true,
  "model": "llama3",
  "ready": true
}
```

If `ready` is `false`, subsequent `/score` calls will fall back to the template
memo, which is faster but less fluent.

---

## 4. Usage examples

### 4.1 curl — simplest case

```bash
curl -X POST http://localhost:8000/score \
  -H "Content-Type: application/json" \
  -d '{
    "loan_amount": 15000,
    "annual_income": 65000,
    "dti": 28.5,
    "credit_score": 680,
    "employment_length_years": 5,
    "product_type": 0
  }'
```

### 4.2 Python — with all fields

```python
import requests

url = "http://localhost:8000/score"
payload = {
    "loan_amount": 25000,
    "annual_income": 95000,
    "dti": 22.0,
    "credit_score": 720,
    "employment_length_years": 8,
    "product_type": 0,
    "num_inquiries_last_6m": 2,
    "credit_utilization": 35,
    "applicant_name": "Sarah",
    "generate_memo": True,
}

r = requests.post(url, json=payload, timeout=10)
result = r.json()

print(f"Decision: {result['decision']}")
print(f"PD:       {result['pd_score']:.2%}")
print(f"EL:       ${result['expected_loss']:,.0f}")
print(f"Rate:     {result['risk_based_rate']:.2%}")
print(f"Latency:  {result['latency_ms']:.0f}ms")

if result["decision"] in ("DECLINE_CREDIT", "DECLINE_POLICY", "REFER"):
    print("\nAdverse action reasons:")
    for reason in result["adverse_reasons"]:
        print(f"  · {reason}")
```

### 4.3 Python — HELOC application

```python
payload = {
    "loan_amount": 50000,
    "annual_income": 120000,
    "dti": 18.0,
    "credit_score": 740,
    "employment_length_years": 10,
    "product_type": 1,           # HELOC
    "ltv_ratio": 0.65,           # Required for HELOC
    "loan_term_months": 36,      # Standardised internally
}
r = requests.post("http://localhost:8000/score", json=payload)
print(r.json()["risk_based_rate"])  # HELOC rate typically 6.5-9.5%
```

### 4.4 Batch scoring via CSV

```bash
# Create a CSV with headers matching field names
cat > applications.csv <<EOF
loan_amount,annual_income,dti,credit_score,employment_length_years,product_type
15000,65000,28.5,680,5,0
25000,95000,22.0,720,8,0
50000,120000,18.0,740,10,1
EOF

curl -X POST http://localhost:8000/score/batch \
  -F "file=@applications.csv"
```

### 4.5 JavaScript / Node

```javascript
const response = await fetch("http://localhost:8000/score", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    loan_amount: 15000,
    annual_income: 65000,
    dti: 28.5,
    credit_score: 680,
    employment_length_years: 5,
    product_type: 0,
  }),
});
const result = await response.json();
console.log(`Decision: ${result.decision} · PD: ${result.pd_score}`);
```

---

## 5. Error handling

| HTTP code | Meaning                  | When it happens                                              |
|-----------|--------------------------|--------------------------------------------------------------|
| `200 OK`  | Successful scoring       | Request processed; decision returned                         |
| `422 Unprocessable Entity` | Request validation failed | Required field missing; value out of bounds (e.g. DTI > 100) |
| `503 Service Unavailable`  | Models not loaded        | `build.py` hasn't been run yet; `.pkl` artifacts missing     |
| `500 Internal Server Error`| Unhandled exception      | Scoring pipeline failure — check server logs                |

All error responses follow FastAPI's standard structure:

```json
{
  "detail": "Models not loaded. Run build.py first."
}
```

For `422` validation errors:

```json
{
  "detail": [
    {
      "loc": ["body", "dti"],
      "msg": "ensure this value is less than or equal to 100",
      "type": "value_error.number.not_le"
    }
  ]
}
```

---

## 6. Integration patterns

### 6.1 LOS integration (synchronous)

A typical Loan Origination System calls `/score` synchronously during the
application flow. Budget 500 ms for the scoring call; if the response is
`APPROVE`, proceed to funds-disbursement; if `REFER`, route to the analyst
work queue; if any `DECLINE_*`, trigger the adverse-action letter workflow.

The LOS should persist the full `ScoreResponse` payload as a decision audit
record — this is what an OSFI examiner or internal auditor will review when
investigating a specific decision.

### 6.2 CRM integration (asynchronous)

For portfolio re-scoring or proactive pre-qualification, use `/score/batch`
in a nightly job that pulls account data from the CRM, generates a CSV,
POSTs it to the endpoint, and writes results back to the CRM's decision
table. Combine with the PSI/CSI monitoring output to detect model drift
against the scored population.

### 6.3 Mobile / frontend

The Streamlit app in `src/app/streamlit_app.py` is one way to expose the
scoring service; a mobile app calling `/score` directly is another. The
response schema is designed to be stable across clients — the decision
banner, SHAP waterfall, and adverse-action letter can all be rendered from
the same JSON.

---

## 7. Ollama LLM configuration

When `generate_memo=true`, the API calls the Ollama server (default
`http://localhost:11434`) to produce a credit memo and adverse-action letter.

### 7.1 PIPEDA compliance

Ollama runs locally. **No applicant PII is transmitted externally.** This is
critical for Canadian deployments — PIPEDA requires applicant consent before
personal information leaves the jurisdiction, and a cloud LLM call would
require documenting that consent at application time.

### 7.2 Fallback behaviour

If Ollama is unreachable, the scoring pipeline falls back to a structured
template. The decision, PD, and regulatory outputs are unaffected — only the
narrative memo and letter text change from LLM-drafted to template-filled.

### 7.3 Model choice

Default: `llama3:8b`. For faster responses on CPU-only machines, switch to
`llama3:7b-q4_0` (quantized). For higher memo quality on GPU-backed
deployments, use `llama3:70b`. The model name is configured in
`src/llm/ollama_client.py`.

---

## 8. Production deployment considerations

This platform is a portfolio-quality reference implementation. Before
deploying to a production lending environment, add:

1. **Authentication** — API keys or OAuth 2.0. The current endpoint has no
   auth layer.
2. **Rate limiting** — Prevent abuse and cost attacks (e.g. via
   `slowapi` or an API gateway).
3. **TLS termination** — Never expose the endpoint over plain HTTP.
4. **Request/response logging** — For OSFI E-23 audit trail. Scrub PII
   before persisting to log aggregators.
5. **Model versioning** — A `model_version` query parameter or path prefix
   (e.g. `/v1/score`, `/v2/score`) so clients can pin to a specific model
   during a champion/challenger rollout.
6. **Circuit breaker on Ollama** — If Ollama latency exceeds a threshold,
   fall back to the template without blocking the main pipeline.
7. **Observability** — Prometheus metrics for latency percentiles, decision
   distribution, fraud-score distribution, error rates.
8. **Schema validation at ingress** — Confirm product-specific required
   fields (e.g. `ltv_ratio` for HELOC) before the pipeline runs, rather
   than failing deep in the scoring code.

---

## 9. Troubleshooting

**"Models not loaded" (503)**
Run `python build.py` first. The `.pkl` files in `models/` are required.

**"Missing required column" on batch scoring**
The CSV must have all 6 required columns. Optional columns default; required
columns fail the whole batch.

**Very slow `/score` calls (>5 seconds)**
Ollama is enabled but slow. Set `generate_memo=false` in the request, or
switch to a quantized Llama 3 model in `ollama_client.py`.

**`fraud_score` always 0.5**
The fraud model `.pkl` file failed to load. Check `models/fraud_model.pkl`
exists and re-run `python build.py --from 9`.

**HELOC application returns `DECLINE_POLICY` unexpectedly**
HELOC requires `ltv_ratio` in the request. If missing or defaulted to 0,
the policy rule P-05 fails even for an otherwise-good applicant.

**API responses don't match Streamlit app**
Check `GET /model/info` returns `v1.0-unified` — if it returns
`v1.1-segmented` you're hitting the challenger architecture, which uses
different per-product models and produces slightly different PDs.

---

## 10. Related documentation

- [README.md](README.md) — Project overview
- [QUICKSTART.md](QUICKSTART.md) — Install and run
- [PRODUCT_GUIDE.md](PRODUCT_GUIDE.md) — Functional description, tab walkthrough
- [CREDIT_POLICY.md](CREDIT_POLICY.md) — Formal credit policy
- [MODEL_CARD.md](MODEL_CARD.md) — OSFI E-23 model card

---

*API Guide v1.1 · April 2026 · For the latest OpenAPI schema, see `/openapi.json` on a running server.*
