# Credit Scorecard — Reference Document

Version 1.1 · April 2026 · Combined Unsecured + Secured Portfolio

---

## 1. Overview

This document is the formal credit scorecard reference for the Credit Risk &
Fraud Detection Platform. It translates the underlying Probability of Default
(PD) model into the points-based scorecard view that credit risk professionals
and OSFI E-23 reviewers expect to see.

Two scorecard views are presented:

1. **Score-to-Decision Lookup Table** — the operational table used by
   underwriters and adverse-action letter generators
2. **Feature-Level Score Attribution** — the per-feature breakdown showing how
   each Weight-of-Evidence (WoE) bin contributes points to the final score

The scorecard is calibrated against real Out-of-Time (OOT) test data using the
LendingClub 2016-2018 vintage and the FICO HELOC sample.

---

## 2. Score scaling methodology

The scorecard uses the standard Points-to-Double-the-Odds (PDO) scaling
convention used in retail credit risk:

```
Score = Offset + Factor × ln(odds)
where odds = (1 - PD) / PD
```

**Calibration parameters:**

| Parameter        | Value | Interpretation                                     |
|------------------|-------|----------------------------------------------------|
| Reference score  | 600   | Baseline at reference odds                         |
| Reference odds   | 4 : 1 | At score = 600, 4 goods to 1 bad (PD ≈ 20%)        |
| PDO              | 50    | Every 50 points doubles the odds (halves PD)       |
| Factor           | 72.13 | 50 / ln(2)                                         |
| Offset           | 500   | 600 - 72.13 × ln(4)                                |

**Score range:** 300 (highest risk) to 850 (lowest risk).

This is the same convention used by Equifax FICO, TransUnion CreditVision, and
most North American consumer lenders. A 50-point increase represents a halving
of default odds, which is intuitive for both internal stakeholders and
external auditors.

---

## 3. Score-to-PD lookup table

The core scorecard. Every applicant's predicted PD maps to one of these score
bands.

| Score band  | Risk tier        | Calibrated PD | Decision        | Annualized loss assumption |
|-------------|------------------|---------------|-----------------|----------------------------|
| 720 – 850   | A — Super-prime  | < 5%          | Auto-approve    | $50 per $1,000 lent        |
| 680 – 719   | B — Prime        | 5% – 10%      | Auto-approve    | $100 per $1,000 lent       |
| 630 – 679   | C — Near-prime   | 10% – 20%     | Approve / refer | $200 per $1,000 lent       |
| 580 – 629   | D — Subprime     | 20% – 35%     | Refer / decline | $350 per $1,000 lent       |
| 300 – 579   | E — Deep subprime| > 35%         | Decline         | n/a (declined)             |

**Approval threshold:** Score ≥ 638 (PD ≤ 28%) → Approve
**Refer band:** Score 605–637 (PD 28%–35%) → Underwriter review
**Decline threshold:** Score < 605 (PD > 35%) → Decline

---

## 4. Risk tier performance — measured on OOT test set

These are real measured values from the Phase 4 model evaluation
(`reports/phase4/score_tier_analysis.csv`):

| Tier | Loans   | Avg score | Avg predicted PD | Actual default rate | Calibration gap |
|------|---------|-----------|-------------------|---------------------|------------------|
| C    | 39,257  | 640       | 5.98%             | 8.67%               | -2.69 pp         |
| D    | 133,892 | 608       | 17.00%            | 23.48%              | -6.48 pp         |

The negative calibration gap on Tier D (predicted under-actual) is documented
in MODEL_CARD §6 — it's driven by the loan-term-months product proxy and is
the central reason for the v1.1 segmented architecture. The v1.1 challenger
models have measured Unsecured AUC of 0.7208 (vs 0.6678 unified), which
materially closes the calibration gap.

---

## 5. Feature-level score attribution

The scorecard is built on 14 features ranked by Information Value (IV). Each
feature contributes points based on which WoE bin the applicant falls into.

### 5.1 Top-contributing features (by IV)

| Rank | Feature                       | IV     | Direction       | Max points contribution |
|------|-------------------------------|--------|-----------------|--------------------------|
| 1    | `external_risk_estimate`      | 0.247  | Higher = better | ±35 points              |
| 2    | `loan_term_months` *          | 0.190  | 36 mo = better  | ±25 points              |
| 3    | `credit_score`                | 0.156  | Higher = better | ±28 points              |
| 4    | `pct_trades_never_delinquent` | 0.118  | Higher = better | ±22 points              |
| 5    | `dti`                         | 0.094  | Lower = better  | ±18 points              |
| 6    | `num_high_utilization_trades` | 0.087  | Lower = better  | ±16 points              |
| 7    | `score_x_product` *           | 0.082  | Mixed           | ±15 points              |
| 8    | `ltv_x_product` *             | 0.071  | Lower = better  | ±13 points              |
| 9    | `num_derogatory_marks`        | 0.064  | Lower = better  | ±12 points              |
| 10   | `annual_income`               | 0.058  | Higher = better | ±11 points              |
| 11   | `ltv_ratio`                   | 0.054  | Lower = better  | ±10 points              |
| 12   | `alt_data_score`              | 0.041  | Higher = better | ±8 points               |
| 13   | `months_since_oldest_trade`   | 0.038  | Higher = better | ±7 points               |
| 14   | `total_accounts`              | 0.027  | Mixed           | ±5 points               |

\* These features are excluded from the v1.1 segmented per-product models
because they encode product-type signal rather than genuine credit-risk signal
(see MODEL_CARD §6).

### 5.2 Worked example — score attribution

A representative Tier C applicant:

| Feature                       | Value      | WoE bin       | Points |
|-------------------------------|------------|---------------|--------|
| Base score                    | —          | —             | 600    |
| `external_risk_estimate`      | 68         | 60–75         | +10    |
| `credit_score`                | 660        | 640–679       | -3     |
| `pct_trades_never_delinquent` | 89%        | 85%–92%       | +5     |
| `dti`                         | 28%        | 25%–30%       | -2     |
| `num_high_utilization_trades` | 3          | 2–4           | -1     |
| `num_derogatory_marks`        | 1          | 1             | -8     |
| `annual_income`               | $65K       | $55K–$80K     | +3     |
| `ltv_ratio`                   | 0.65       | 0.55–0.70     | +1     |
| `alt_data_score`              | 55         | 40–60         | 0      |
| `months_since_oldest_trade`   | 96         | 60–120        | -2     |
| `total_accounts`              | 12         | 10–15         | +1     |
| `loan_term_months`            | 36         | 36            | +5     |
| **Final score**               |            |               | **609**|

This applicant lands in **Tier D** (subprime, PD 20%-35%) and routes to the
**Refer band** for underwriter review.

---

## 6. Score distribution — measured portfolio

From the 194,564-loan OOT scoring portfolio (Phase 4 outputs):

| Tier | Count   | % of portfolio | Cumulative % |
|------|---------|----------------|--------------|
| A    | 12,045  | 6.2%           | 6.2%         |
| B    | 25,318  | 13.0%          | 19.2%        |
| C    | 39,257  | 20.2%          | 39.4%        |
| D    | 133,892 | 68.8%          | 100.0%       |
| E    | 0       | 0.0%           | declined     |

The heavy concentration in Tier D reflects the LendingClub training population,
which is dominated by near-prime / subprime unsecured lending. A real Canadian
non-bank lender with mixed prime/subprime mix would see a more balanced
distribution.

---

## 7. Scorecard governance

### 7.1 Validation thresholds

The scorecard is monitored against the following triggers (per OSFI E-23):

| Metric                         | Trigger    | Frequency  | Action                       |
|--------------------------------|------------|------------|------------------------------|
| PSI (population stability)     | > 0.25     | Monthly    | Investigate; consider rebuild |
| CSI (characteristic stability) | > 0.15     | Monthly    | Investigate feature drift     |
| OOT Gini                       | < 0.30     | Quarterly  | Trigger formal revalidation   |
| Calibration gap (any tier)     | > 5 pp     | Quarterly  | Recalibrate Platt scaling     |
| Approval rate change           | > 5 pp YoY | Quarterly  | Underwriting policy review    |

### 7.2 Champion / challenger

**Champion (production):** v1.0 unified XGBoost
**Challenger (under evaluation):** v1.1 segmented per-product models

The v1.1 segmented models will be promoted to champion when:
1. ≥ 12 months of stable PSI/CSI on the unsecured segment
2. ≥ 6 months of HELOC volume sufficient to reduce thin-data risk (target: > 50K records)
3. Operational pipeline doubled (separate monitoring, separate adverse-action templates)
4. CRO and Credit Risk Committee sign-off on dual-model governance

Until then, v1.1 runs alongside v1.0 for monitoring and validation purposes only.

---

## 8. Adverse action and reason codes

When the scorecard declines an applicant (score < 605 or any hard policy
failure), the system generates an adverse-action letter using ECOA-compliant
reason codes derived from SHAP attribution. The top-3 negative drivers from
the applicant's score are translated into plain-English reasons.

**Common reason codes:**

| Code  | Description                                     | Mapped from                       |
|-------|-------------------------------------------------|-----------------------------------|
| AA-01 | Insufficient credit history                     | `months_since_oldest_trade` low   |
| AA-02 | Too many recent inquiries                       | `num_inquiries_last_6m` high      |
| AA-03 | Debt-to-income ratio too high                   | `dti` high                        |
| AA-04 | Insufficient income                             | `annual_income` low               |
| AA-05 | Recent derogatory marks                         | `num_derogatory_marks` ≥ 1        |
| AA-06 | High credit utilization                         | `num_high_utilization_trades` high|
| AA-07 | Credit score below threshold                    | `credit_score` low                |
| AA-08 | High loan-to-value ratio (HELOC only)           | `ltv_ratio` > 0.80                |
| AA-09 | Insufficient alternative-data signal            | `alt_data_score` low              |
| AA-PF | Hard policy failure (specific rule cited)       | Policy gate                       |

The adverse-action letter is generated by Llama 3 (locally via Ollama, for
PIPEDA compliance) using these codes plus the applicant's name. A template
fallback ensures letter generation if the LLM is unavailable.

---

## 9. References

- `reports/phase4/score_tier_analysis.csv` — Live tier performance data
- `reports/phase4/model_comparison.csv` — Champion model AUC/KS/Gini
- `reports/phase4/model_comparison_segmented.csv` — v1.1 challenger metrics
- `reports/phase3/iv_table.csv` — Information Value rankings
- `MODEL_CARD.md` — Full model governance document
- `CREDIT_POLICY.md` — Underwriting standards and override authority
- `src/models/pd_model.py` — Implementation
- `src/features/woe_binning.py` — WoE bin definitions

---

*Credit Scorecard v1.1 · April 2026 · Approved by Credit Risk & Strategy.
For internal risk management and OSFI E-23 model governance use.*
