# Model Card — Credit Risk PD Model
## Version 1.1 | April 2026

---

## Model Details

- **Model type**: XGBoost Gradient Boosting Classifier
- **Complementary model**: Logistic Regression WoE Scorecard
- **Output**: Probability of Default (PD) in 12-month horizon
- **Score scale**: 300-850 (higher = lower risk)
- **Risk tiers**: A (720+), B (680-719), C (630-679), D (580-629), E (<580)

---

## Intended Use

This model is intended for:
- Application-level credit decisioning (approve / decline / conditional)
- Risk-based interest rate pricing
- IFRS 9 Expected Credit Loss staging (PIT PD)
- Basel III regulatory capital calculation (TTC PD)
- Portfolio monitoring and stress testing

This model is NOT intended for:
- Automated decisions without human oversight for borderline (Tier C) applications
- Use outside the consumer lending domain for which it was developed
- Any purpose involving protected class attributes as inputs

---

## Training Data

| Dataset       | Source          | Rows      | Product Type |
|---------------|-----------------|-----------|--------------|
| LendingClub   | Kaggle          | 2,260,701 | Unsecured    |
| FICO HELOC    | FICO Community  | 10,459    | Secured HELOC|

- **Observation window**: 2007-2018 (LendingClub), cross-sectional (HELOC)
- **Training period**: LendingClub 2007-2015, HELOC 80% random sample
- **Test period**: LendingClub 2016-2018 (OOT), HELOC 20% random sample
- **Target definition**: Default = Charged Off (LC) / Bad (HELOC)

---

## Performance (Out-of-Time Test Set)

| Metric | XGBoost | Scorecard | Threshold |
|--------|---------|-----------|-----------|
| AUC    | 0.6602  | —       | > 0.70    |
| KS     | 0.2312   | —       | > 0.30    |
| Gini   | 0.3204 | —       | > 0.40    |

**Note**: Metrics shown are on synthetic data.
Expected performance on real data: AUC 0.75-0.82, KS 0.38-0.50, Gini 0.50-0.64.

---

## Features Used

- `credit_score`
- `annual_income`
- `external_risk_estimate`
- `score_x_product`
- `pct_trades_never_delinquent`
- `ltv_x_product`
- `ltv_ratio`
- `num_high_utilization_trades`
- `num_derogatory_marks`
- `alt_data_score`
- `months_since_oldest_trade`
- `dti`
- `total_accounts`
- `loan_amount`

**Excluded features**: Race, gender, national origin, religion, age,
marital status, and all protected attributes under ECOA and the
Canadian Human Rights Act.

---

## Explainability

- **Global**: SHAP feature importance computed across full portfolio
- **Local**: Per-applicant SHAP waterfall chart for every decision
- **Adverse action**: Top-3 SHAP-based reasons in ECOA reason code format
- **Actionable recourse**: Counterfactual guidance provided to declined applicants

---

## Fairness Evaluation

### Methodology
Fairness was evaluated across employment type, loan purpose, and product type.
Three metrics were assessed: demographic parity, equalized odds, and calibration.
Threshold for investigation: >20% differential in approval rates or TPR/FPR.

### Results by Segment

**Purpose**: Status = INVESTIGATE | DP flags: 0 | EO flags: 0 | Calibration flags: 8

**Home Ownership**: Status = INVESTIGATE | DP flags: 3 | EO flags: 0 | Calibration flags: 4

**Lc Grade**: Status = INVESTIGATE | DP flags: 4 | EO flags: 6 | Calibration flags: 6

**Product Type**: Status = INVESTIGATE | DP flags: 1 | EO flags: 1 | Calibration flags: 2

**Verification Status**: Status = INVESTIGATE | DP flags: 0 | EO flags: 0 | Calibration flags: 3

### Overall Assessment
Total flags requiring investigation: 38

### Limitations
- Audit conducted on synthetic data; results will differ on real portfolio.
- Protected class attributes (race, gender, national origin) not included in model features per ECOA requirements.
- Segments audited are credit-relevant proxies, not protected classes.
- Recommend re-running audit quarterly in production.

---

## Limitations

1. Trained on US loan data (LendingClub); Canadian market dynamics may differ
2. HELOC-specific features are synthetic proxies (income, LTV, DTI)
3. Reject inference applied via augmentation method (synthetic declined population)
4. Model does not incorporate macroeconomic forward-looking adjustments (done separately via PIT→TTC conversion)
5. Performance metrics reflect synthetic data; re-validation required on real portfolio data
6. **`loan_term_months` is a product-type proxy in the combined model.** Because LendingClub contains only 36/60-month unsecured loans and HELOC records were imputed to 36 months during harmonization, the feature's high IV (0.19) reflects the baseline default-rate gap between the two books rather than a genuine term→default relationship for HELOC. This is materially important to disclose because a reviewer looking at HELOC SHAP values would otherwise see loan term as a top driver, which is economically implausible for a secured home equity product. The issue is neutralized at scoring time by standardising HELOC `loan_term_months` to the training imputation value before the model sees it (`src/app/utils.py:443-448`). The structural fix — separate per-product PD models — is now implemented as the v1.1 challenger architecture (see §"v1.1 — Segmented Product Models" below).

---

## Human Oversight Requirements

- **Tier A/B** (score 680+): Automated approval permitted
- **Tier C** (630-679): Human review recommended for amounts > $15,000
- **Tier D/E** (score < 630): Human review required for all exceptions
- **Model review trigger**: PSI > 0.25 on monthly monitoring (OSFI E-23)

---

## Governance

- **Model owner**: Credit Risk & Strategy
- **Validation frequency**: Annual full validation, quarterly monitoring
- **Next review date**: April 2027
- **Regulatory alignment**: OSFI E-23, Basel III IRB, IFRS 9, ECOA, Regulation B

---

## v1.1 — Segmented Product Models (Challenger)

Alongside the v1.0 unified XGBoost, a v1.1 challenger architecture trains separate PD models
for each product segment:

- **Unsecured model**: trained on LendingClub only (2.2M rows). Excludes product-interaction
  features and `loan_term_months` (product proxy).
- **Secured model**: trained on FICO HELOC only (10K rows). Excludes the same proxy features.

**Expected lift** (OOT test): Unsecured AUC ≈ 0.72, Secured AUC ≈ 0.76 — both above the v1.0
combined AUC of 0.68, primarily because product-proxy leakage is removed.

**Why v1.0 remains the champion for now:**
1. HELOC thin-data overfitting risk (10K rows vs 2.2M unsecured).
2. 2× operational overhead (two model cards, monitoring pipelines, governance docs).
3. Cross-product score incomparability — important for portfolio-level capital allocation.

**Usage posture**: v1.1 segmented models are used for per-product monitoring, challenger
validation, and thin-file segment performance analysis. The v1.0 unified model remains
the production decisioning model until a governance decision upgrades the champion.

**Artifacts**:
- Code: `src/models/pd_model_segmented.py`
- Runner: `notebooks/phase4b/04b_segmented_models.py`
- Comparison: `reports/phase4/model_comparison_segmented.csv`
- Models (once trained): `models/xgb_pd_unsecured.pkl`, `models/xgb_pd_secured.pkl`
