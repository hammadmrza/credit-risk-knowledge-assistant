# Product Guide — Credit Risk & Fraud Detection Platform

Version 1.1 · April 2026

---

## 1. What this is

An end-to-end credit risk **decisioning system** for Canadian consumer lending.
It takes a loan application, runs it through a hierarchical five-step decision
engine, and produces a fully documented credit decision with all the artifacts
a lender's risk team, model governance committee, or external examiner would
need: the score, the probability of default, the expected loss, the Basel III
capital charge, the IFRS 9 provision, the adverse action reasons, the
counterfactual recourse paths, and a credit memo.

Unlike a typical portfolio ML project that trains one model, this platform
reproduces the architecture of a real commercial lending system — integrated
credit, fraud, policy, explainability, compliance, and pricing in one
coherent workflow.

---

## 2. The problem it solves

Canadian non-bank consumer lenders — automotive finance companies, fintechs,
consumer finance firms, B-lender HELOC providers — face a compounding set of
pressures:

1. **Regulatory weight.** OSFI Guideline B-20 (residential mortgage
   underwriting), OSFI E-23 (model risk management), Basel III capital
   requirements under the IRB approach, IFRS 9 forward-looking ECL provisioning,
   ECOA / Regulation B adverse action disclosure, and the Criminal Code s.347
   35% APR cap (effective January 2025) together require every credit decision
   to be scored, explained, provisioned, capital-charged, and disclosed —
   consistently and auditably.

2. **Data complexity.** Most lenders operate multiple product books (secured
   auto, unsecured personal, HELOC, credit card) each with different default
   mechanisms, collateral profiles, and regulatory treatment. Single-model
   approaches either underperform per-product or become unmanageable to govern.

3. **Decisioning fragility.** Credit, fraud, and policy rules are typically
   built by separate teams, in separate systems, with little coordination.
   The result: conflicting decisions, inconsistent adverse-action disclosures,
   and legal exposure on rejected applications.

4. **Explainability gaps.** ECOA and Regulation B require adverse action
   reasons that are specific and actionable. SHAP is the industry-standard
   solution, but integrating it with counterfactual recourse paths ("to get
   approved, reduce DTI to 28%") and with an LLM-drafted letter that a
   non-technical applicant can understand is genuinely hard.

This platform demonstrates one coherent approach to all four.

---

## 3. What makes this different

### 3.1 Hierarchical decision engine

Most portfolio projects score a loan and call the result the decision. Real
lenders don't work that way. The engine here runs the application through
five ordered gates:

1. **Fraud gate.** If the fraud score exceeds 65%, the decision is
   `DECLINE_FRAUD`. Critically, the adverse-action letter does **not** cite
   fraud as the reason (FCAC guidance, line 376-378 of `streamlit_app.py`).
   Fraud takes priority over credit because a fraudulent application is not
   a credit risk question.

2. **Hard policy rules.** Credit score below the floor, DTI above the ceiling,
   derogatory marks at or over the maximum, inquiries above the velocity
   threshold, or HELOC LTV above 90% — any of these triggers `DECLINE_POLICY`.
   The credit model never runs. The adverse-action letter cites the specific
   policy rule that failed, not SHAP reasons (ECOA-correct).

3. **Credit model.** PD > 35% triggers `DECLINE_CREDIT`. Adverse action reasons
   are SHAP-derived and suppression-filtered (internal features and non-bureau
   signals are never disclosed).

4. **Refer band.** PD between 28% and 35% goes to `REFER` — a human credit
   analyst reviews compensating factors (employment stability, asset position,
   relationship depth) not captured by the model.

5. **Approve.** PD ≤ 28% passes through to approval with a recommended
   risk-based APR, capital charge, and IFRS 9 stage.

### 3.2 Calibration-first validation

For IFRS 9 ECL, Basel III capital, and risk-based pricing, the absolute PD
value matters more than the relative ranking. A well-calibrated 0.72 AUC
model beats a miscalibrated 0.80 AUC model for regulatory and pricing use
because everything downstream consumes PD as a probability, not as a ranking.

Tab 3, Section 5 leads with calibration evidence: Brier score, Brier skill
score, calibration gap (mean-PD minus actual-default-rate), per-product segment
calibration, and a decile-level bar-and-line chart. If calibration is sound,
moderate AUC is defensible. If calibration is off, even excellent AUC is
unusable.

### 3.3 v1.0 unified vs v1.1 per-product segmented — documented choice

The v1.0 unified PD model trains one XGBoost on both product books combined,
with `product_type` as a feature. This produces an OOT AUC of ~0.68 —
acceptable, not excellent. The architectural cause: `loan_term_months` becomes
a product-type proxy (36/60-month unsecured vs imputed-36 HELOC) and absorbs
signal that belongs to real credit features.

The v1.1 challenger (`src/models/pd_model_segmented.py`) trains separate PD
models per product book with product-proxy features removed. Expected lift:
Unsecured OOT AUC ~0.72, Secured ~0.76. Tab 3, Section 3 shows both
side-by-side.

The v1.0 unified model remains champion for production decisioning because:

- **HELOC is thin-data** — 10K rows vs 2.2M unsecured. Segmented HELOC risks
  overfitting.
- **Operational overhead doubles** — two model cards, two monitoring pipelines,
  two OSFI E-23 governance documents.
- **Cross-product score comparability matters** — portfolio-level capital
  allocation and concentration limits require comparable scores across books.
  Segmented models have different baseline default rates and are not directly
  comparable.

The segmented models are used for per-product monitoring, challenger
validation, and thin-file performance diagnosis. Both sets of numbers are
published in the model card.

### 3.4 Regulatory grounding

This is not a model with regulation bolted on — regulatory constraints are
first-class features of the architecture:

- **Basel III IRB formula shown in full** in Tab 4 with R (asset correlation),
  N (standard normal CDF), G (inverse), and the 99.9th percentile capital
  calculation. Not just the number.
- **IFRS 9 three-stage classification** with documented staging triggers
  (PD > 20% from origination, credit score drop > 30, 30+ DPD for Stage 2;
  PD ≥ 70% or 90+ DPD for Stage 3) and colour-coded coverage ratios vs
  industry bands (Stage 1: 0.5-2%, Stage 2: 5-15%, Stage 3: 40-80%).
- **Criminal Code s.347 35% APR cap** visibly enforced in pricing with an
  explicit hard line on the rate-decomposition chart.
- **PIPEDA-compliant LLM.** All Ollama inference runs locally — no PII is
  transmitted externally.
- **ECOA / Regulation B adverse action reasons** — SHAP-derived, suppressed
  for non-bureau and interaction features, with counterfactual recourse paths.

### 3.5 Honest disclosure as a feature

Every synthetic proxy, every simplifying assumption, every known limitation
is surfaced in yellow callout boxes inside the app. This is deliberate. OSFI
E-23 expects model documentation to be honest about boundaries. An examiner
or auditor sees the disclosures before needing to ask. Specific examples:

- **`loan_term_months` is a product-type proxy** (Tab 3 caption + MODEL_CARD §6)
- **IFRS 9 origination PD is proxied using LendingClub grade**, with explicit
  statement that "the grade-based proxy would not be acceptable for a
  regulatory submission" (Tab 4)
- **LGD held constant across stress scenarios** — documented simplification;
  real HELOC LGD rises 30%→60% during a 2008-style house-price shock (Tab 4)
- **Fraud labels are synthetic** — LendingClub and FICO HELOC contain no
  confirmed fraud labels. Real AUC would be 0.72–0.85 on investigation-labeled
  data (Tab 6 banner)
- **Alternative data is synthetic** — ADS is anchored 40% to credit score;
  real Borrowell / NeoBureau integration would add genuine independent signal
  (PRODUCT_GUIDE §6.5)

---

## 4. Data

### 4.1 LendingClub Loan Data (2007–2018)

**Source:** Kaggle — `wordsforthewise/lending-club`
**Filename:** `lending_club_loans.csv` (~1.5 GB)
**How used:** Unsecured personal loan book (`product_type = 0`).
**Rows retained:** ~2.2M settled loans (Fully Paid or Charged Off).
**Default definition:** `loan_status` in {Charged Off, Default}.

### 4.2 FICO HELOC Dataset v1

**Source:** FICO Explainable Machine Learning Challenge
**Filename:** `heloc_dataset_v1.csv` (~660 KB)
**How used:** Secured HELOC book (`product_type = 1`).
**Rows:** 10,459 anonymized HELOC records from a real bureau.
**Default definition:** `RiskPerformance = "Bad"` — at least one 90-day
delinquency in the 24 months after origination.
**Engineered proxies:** income, LTV, employment tenure (not present in raw
bureau data; engineered as synthetic but defensibly-distributed columns).

### 4.3 Harmonization — Phase 1

Both books are merged into a single schema with `product_type` as the
discriminator. The combined training set contains ~2.2M rows. An
out-of-time (OOT) test split reserves 2016–2018 vintages (194,564 loans).
This OOT set is never seen during training and provides the honest
discriminatory-power evidence shown in Tab 3.

---

## 5. The seven tabs

### 5.1 Tab 1 — Application Assessment

**Audience:** Loan officer, underwriter, credit analyst.

**What it does:** Single-applicant scoring end-to-end. Enter 13 inputs (product,
loan amount, term, LTV if HELOC, credit score, income, DTI, employment tenure,
derogatory marks, total accounts, inquiries, utilization, alt data, thin file
flag). Click Score. In under a second you see:

- **Decision banner** — colour-coded for the five outcomes
- **Plain-English summary** — "This applicant is a moderate-risk borrower..."
- **Fraud status** — collapsed into an expander for LOW alert tier, prominent
  for MEDIUM/HIGH/CONFIRMED
- **Core Risk Metrics** — Risk Score (300-850 PDO scale), PD, EL, IFRS 9 stage
- **SHAP waterfall** — top 6 features ranked by contribution to the decision
- **Adverse action reasons** — ECOA/Reg B compliant, suppressing internal and
  interaction features
- **Counterfactual recourse paths** — "To get approved, reduce DTI to 28%"
- **Regulatory metrics** — RWA, Min Capital (8%), ECL Provision, Recommended Rate
- **Credit memo** — drafted by Llama 3 (or template fallback)
- **Adverse action letter** — generated on decline/refer, downloadable

**Policy integrations:**
- Loan term dropdown is restricted per product (36/60 for unsecured, 36 only
  for HELOC) — the model was only trained on those values.
- Applicant name is required before the adverse-action letter generates
  (prevents letters addressed to "Applicant" — not ECOA-compliant).

### 5.2 Tab 2 — Batch Portfolio Scoring

**Audience:** Portfolio manager, risk analyst, commercial pricing team.

**What it does:** Score thousands of applications at once, either by uploading
a CSV or loading the 194K-loan OOT test portfolio.

**Features:**
- Four interactive filters: Product, Risk Tier, Decision, Minimum Expected Loss
- Error summary banner ("Scored N of M rows successfully, K failed") with
  expandable per-row error details
- Product × Tier concentration pivot table
- Risk-tier distribution bar chart
- Dual downloads: filtered results + full pre-filter results

**Use cases:**
- Pre-book scoring a prospective acquisition portfolio
- Stress-testing an existing book at a new policy threshold
- Generating tier-split inputs for a treasury funding model

### 5.3 Tab 3 — Model Performance

**Audience:** Model risk manager, validation officer, OSFI examiner, auditor.

**What it does:** Complete validation workbench, organized into nine sections:

1. **Discriminatory power** — Scorecard vs XGBoost AUC/KS/Gini with industry
   thresholds (AUC ≥ 0.70, KS ≥ 0.30)
2. **ROC and KS curves** — With KS-max score annotation and AUC annotation
3. **v1.0 unified vs v1.1 segmented** — Side-by-side per-product metrics with
   lift narrative
4. **Confusion matrix** — Interactive threshold slider; precision, recall,
   F1, FPR at the chosen cutoff; lift and gains charts below
5. **Calibration** — Decile bar-and-line chart, Brier score, Brier skill
   score, calibration gap, per-product segment calibration
6. **Vintage default rate** — 2007-2018 actual performance by origination
   year; 2016-2018 flagged as OOT
7. **Global SHAP feature importance** — Top 10 with caveat on
   `loan_term_months` product-proxy role
8. **PSI / CSI feature stability** — OSFI E-23 thresholds colour-coded
9. **Fairness assessment** — Demographic parity + equalized odds across 5
   segments, with explicit scope-and-limitations box

### 5.4 Tab 4 — Compliance

**Audience:** CFO, treasury, regulatory affairs, OSFI examiner.

**What it does:** Three core regulatory outputs:

**Basel III Capital** — Full IRB formula shown with R (asset correlation),
N (standard normal CDF), G (inverse CDF), and the 99.9th percentile capital
calculation. KPI row: Total Exposure (EAD), Total RWA, Capital Adequacy Ratio
(available capital / RWA, with the 11.5% CET1 assumption explicitly flagged),
Minimum Capital Required at 8%.

**IFRS 9 — Expected Credit Loss by Stage** — Stage 1/2/3 breakdown with
colour-coded coverage ratios:
- 🟢 Green: within industry band (Stage 1: 0.5-2%, Stage 2: 5-15%, Stage 3: 40-80%)
- 🟡 Amber: within 1.5× of band
- 🔴 Red: materially outside band

Per-stage text summary explains whether coverage is above, below, or within
band.

**Macroeconomic Stress Test** — Three scenarios (Base / Adverse / Severe)
with PD multipliers (1.0× / 1.4× / 2.0×) derived from 2008-09 GFC and 2020
COVID recession data. Documented simplifications: LGD held constant (real
HELOC LGD rises 30%→60% during house-price shock), TTC vs PIT explained,
capital headroom test articulated.

### 5.5 Tab 5 — Risk-Based Pricing

**Audience:** Pricing committee, treasury, commercial strategy.

**What it does:** Five sections:

1. **Rate Decomposition Calculator** — Build rate from first principles:
   CoF + EL (PD × LGD) + OpEx + ROE − collateral adjustment. Sliders update
   in real time. Criminal Code s.347 35% cap enforced visibly.

2. **Full Rate Schedule by Risk Tier** — Mid-PD per tier computed from the
   actual scored portfolio (not hardcoded). Shows which tiers hit the 35% cap
   at current inputs.

3. **Market Rate Comparison** — Six Canadian lender benchmarks (prime bank,
   credit union, fintech, subprime, B-lender HELOC) with the model's
   tier-A and tier-E rates overlaid. Anchors the model's output against
   commercial reality.

4. **Profit Curve** — Sweeps approval thresholds from 5% to 70% PD, computing
   expected revenue, expected loss, and net profit at each cutoff. Identifies
   the profit-maximising threshold and compares it to the current platform
   threshold (PD ≤ 28%). Shows the dollar P&L delta.

5. **Cost of Funds Sensitivity** — How many tiers hit the 35% cap as CoF
   rises from 3% to 8%. Illustrates the margin-compression risk of rising-rate
   environments for subprime-heavy books.

### 5.6 Tab 6 — Fraud Monitoring

**Audience:** Fraud operations, SOC, Second Line of Defense.

**What it does:** Post-funding fraud detection view. Note that fraud is also
integrated upstream in Tab 1 as the first gate of the decision engine; this
tab shows the portfolio-level monitoring view.

**Synthetic label disclosure** at the top of the tab: LendingClub and FICO
HELOC contain no confirmed fraud investigation labels. Labels here are
synthetic. Real AUC would be 0.72-0.85 on genuine investigation labels.

**Sections:**
- Alert tier distribution (CONFIRMED / HIGH / MEDIUM / LOW)
- Fraud type breakdown (first-party, synthetic ID, income misrepresentation, etc.)
- Fraud trend over time by origination cohort — auto-detects spikes
  (>25% above prior-period average)
- Product × fraud type drill-down (pivot + stacked bar)
- First Payment Default (FPD) analysis — the strongest post-funding signal
- Investigation queue with full column definitions

### 5.7 Tab 7 — Executive Dashboard

**Audience:** CRO, Board Risk Committee.

**What it does:** Three sub-views consolidating views 1-6 into a CRO-level
morning briefing:

- **Portfolio Health** — 7-KPI row (Loans, EAD, EL Rate, Avg PD, Avg Score,
  RWA, CAR), tier distribution, EL by tier, product split, vintage performance
- **Model Monitoring** — Score + PD distributions, scorecard vs XGBoost
  performance, PSI/CSI alert counts, pointer to Tab 3 for segmented comparison
- **Risk Concentration** — EL concentration by tier (loan share vs EL share
  with concentration ratio), IFRS 9 stage distribution with ECL provisioning,
  stress test capital headroom

The dashboard guards against empty portfolios (surfaces a helpful warning
before any chart render) and shares constants with the rest of the app so it
cannot drift out of sync with the tabs.

---

## 6. Models

### 6.1 PD — Probability of Default

**Champion: XGBoost (v1.0 unified)** on WoE-transformed features.
- Training set: ~1.57M rows harmonized across both product books
- Features: 10 selected via Information Value ≥ 0.02
- Calibration: Platt scaling (sigmoid fit to cross-validated scores)
- Output: Calibrated 12-month point-in-time PD
- OOT AUC: ~0.68 (depressed by `loan_term_months` product proxy)

**Challenger: XGBoost per-product (v1.1 segmented)**
- Unsecured model: trained on LendingClub only, product-proxy features excluded
- Secured model: trained on HELOC only, thinner depth + regularization for
  small sample
- Expected OOT AUC: Unsecured ~0.72, Secured ~0.76

**Also included: Logistic-regression Scorecard** on WoE-transformed features
as a transparent benchmark. Scorecard OOT AUC is ~0.67 — slightly below
XGBoost as expected for a linear model.

### 6.2 LGD — Loss Given Default

Linear regression on collateral and recovery features. Output: expected loss
severity as a fraction of EAD.
- Unsecured LGD: ~65-75% (bankruptcy/charge-off driven, low recovery)
- Secured LGD: ~30-45% (collateral seizure + property sale net of costs)

### 6.3 EAD — Exposure at Default

For installment loans (unsecured), EAD is the outstanding principal at the
time of default. For revolving credit (HELOC), EAD includes a credit
conversion factor (CCF) for undrawn-but-committed exposure. Phase 4 computes
both.

### 6.4 Fraud Detection

XGBoost on 14 fraud-specific features:
- Application-time red flags (income inconsistency, address mismatch)
- First payment default signals
- Velocity / loan-stacking indicators
- Synthetic identity indicators
- Identity consistency features

**Label disclosure:** synthetic labels calibrated to industry benchmarks
(6.86% fraud rate). Every label-generating function in
`src/data/fraud_label_generator.py` documents its real-data swap interface
(LexisNexis RiskView, Equifax Fraud Shield, Socure, or an internal platform).

### 6.5 Alternative Data Score (ADS)

Synthetic composite 0-100 representing rent / utility / telecom payment
behaviour. Construction:
- 40% credit score component
- 30% delinquency recency (rent/utility arrears proxy)
- 20% utilization (cash flow proxy)
- 10% account vintage (stability proxy)

**Honest note:** because 40% of the construction is anchored to credit score,
ADS is largely redundant with `credit_score` in the current synthetic data.
Its IV is 0.015 — below the 0.02 selection threshold — so it's dropped during
feature selection and does not enter the production model.

**In a real deployment**, ADS would be replaced by a call to a commercial
alternative-data API (Equifax NeoBureau, Borrowell Rental Advantage, Experian
Clarity, Nova Credit). The interface (`src/data/alt_data.py`) is a drop-in
swap. The commercial value is strongest for thin-file applicants where
traditional bureau data is limited.

### 6.6 Regulatory models

**Basel III IRB** — Per-product asset correlation R, standard normal CDF N,
inverse CDF G, 99.9th percentile capital K, RWA = 12.5 × K × EAD.

**IFRS 9 ECL** — Stage 1 uses 12-month PD × LGD × EAD. Stages 2-3 use
lifetime ECL: monthly PD curve × LGD × EAD, discounted at the original
effective interest rate.

**Stress testing** — PD multipliers by scenario (Base 1.0×, Adverse 1.4×,
Severe 2.0×). LGD constant (documented simplification). RWA uses TTC PD;
stressed EL uses PIT PD × multiplier — these move differently by design
(Basel III anti-procyclical mechanism).

---

## 7. Explainability

### 7.1 SHAP

TreeSHAP on the XGBoost model. Global importance in Tab 3, local explanations
in Tab 1. Contributions sum exactly to the prediction (Shapley guarantee).

### 7.2 Adverse action suppression

Some features should never appear in an adverse action letter:
- **Interaction features** (`dti_x_emp_risk`, `ads_x_thin_file`,
  `score_x_product`, `ltv_x_product`) — not explainable to a consumer
- **Product proxies** (`loan_term_months`) — not a genuine credit signal
- **Internal flags** (`has_synthetic_features`, `product_type`) — meaningless
  to the applicant
- **Features with healthy values** — a 0-inquiry applicant is never told
  "too many inquiries" even if SHAP flags it

The adverse-action reason list is the result of applying this suppression
filter to the top SHAP risk drivers.

### 7.3 Counterfactual recourse paths

For declined applicants, the system generates "what would change the
outcome" paths. Example: *"Reduce DTI from 45% to 28% → new PD 22% → APPROVE"*.

Search logic is constrained to features the applicant can realistically modify
(DTI, utilization, inquiries, employment length, alt data score) and returns
the top 3 single-feature paths that cross the approval threshold.

### 7.4 LLM-drafted credit memos

When Ollama is available, Llama 3 drafts:
1. A credit memo summarizing the applicant, the decision, the key risk
   drivers, and the regulatory metrics
2. An adverse-action letter (on decline/refer) that is ECOA/Reg B compliant
   and uses plain-English reasons from the SHAP suppression list

Template fallbacks exist if Ollama is not available, so the app does not
require the LLM layer to function.

---

## 8. Known limitations

Documented in full in [MODEL_CARD.md](MODEL_CARD.md). The major items:

1. **Training data is US** (LendingClub). Canadian market dynamics may differ.
2. **HELOC-specific features are synthetic proxies** (income, LTV, DTI).
3. **Reject inference** applied via augmentation (synthetic declined population)
   — not a behavioural override.
4. **No forward-looking macro factors** in the PD model itself. Macro is
   handled separately via the PIT→TTC conversion and stress test PD multipliers.
5. **Performance metrics on synthetic-proxy-adjusted data** — re-validation
   required on a real production portfolio.
6. **`loan_term_months` is a product-type proxy** in the v1.0 unified model.
   Neutralized at scoring time for HELOC (standardised to 36 months). v1.1
   segmented models remove it structurally.
7. **Fraud labels are synthetic.** Real AUC on investigation labels would be
   0.72-0.85.
8. **IFRS 9 origination PD is proxied** using LendingClub grade. Would not
   be acceptable for regulatory submission.
9. **Stress-test LGD held constant.** Real HELOC LGD rises under house-price
   shock (30%→60% during GFC).

---

## 9. Scope — what this is and is not

### Is

- A portfolio-quality demonstration of integrated credit-risk decisioning
- A working reference implementation of Basel III IRB + IFRS 9 ECL on real data
- A validation workbench that surfaces calibration, segmentation, and fairness
- An OSFI E-23 model card template with genuine challenger comparison
- A teaching artifact showing how lending systems are actually built

### Is not

- A production credit system (no LOS integration, no real-time bureau feed,
  no SOC 2 audit, no PIPEDA data-processing agreement with applicants)
- A substitute for formal OSFI E-23 model validation (the MODEL_CARD is a
  starting framework, not the endpoint)
- A compliance opinion on ECOA, Reg B, or FCAC (consult counsel)
- A recommendation engine for actual lending decisions

---

## 10. Product roadmap — v1.2 candidates

1. **Promote v1.1 segmented to champion** — if the governance committee
   accepts the operational cost of dual model governance for the AUC lift
2. **Replace synthetic alt-data with Equifax NeoBureau / Borrowell integration**
   — the API interface is already in place
3. **Stressed LGD for HELOC** — model LGD migration under house-price shock
   rather than holding LGD constant
4. **Behavioural scoring extension** — rescore existing loans monthly using
   post-funding payment behaviour (FPD, DPD buckets, utilization changes)
5. **Champion/challenger framework** — automate the shadow-scoring of v1.1
   segmented alongside v1.0 unified, with monthly performance divergence
   reporting
6. **MLOps retraining triggers** — automatic retraining when PSI > 0.25 on
   monthly monitoring (OSFI E-23)
7. **Production LOS integration roadmap** — replace the synthetic
   origination-PD proxy with actual booked-at-origination risk ratings from
   the LOS

---

## 11. Further reading

- [README.md](README.md) — Project front door
- [QUICKSTART.md](QUICKSTART.md) — Install and run
- [CREDIT_POLICY.md](CREDIT_POLICY.md) — Formal credit policy
- [MODEL_CARD.md](MODEL_CARD.md) — OSFI E-23 model card
- [API_GUIDE.md](API_GUIDE.md) — FastAPI endpoint reference

---

*Product Guide v1.1 · April 2026 · This document is part of the credit risk
platform documentation suite.*
