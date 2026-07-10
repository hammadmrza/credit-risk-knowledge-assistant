# CREDIT POLICY

**Credit Risk & Fraud Detection Platform**

Version 1.1 · Effective Date: April 2026 · Review Cycle: Annual

---

## Document Control

| Field                        | Value                                                |
|------------------------------|------------------------------------------------------|
| Document ID                  | CRP-POL-001                                          |
| Version                      | 1.1                                                  |
| Effective Date               | April 21, 2026                                       |
| Next Review Date             | March 2027                                           |
| Document Owner               | Credit Risk & Strategy                               |
| Approved By                  | Chief Risk Officer (CRO); Credit Risk Committee (CRC)|
| Regulatory Alignment         | OSFI B-20, OSFI E-23, Basel III IRB, IFRS 9, ECOA/Reg B, FCAC, Criminal Code s.347 |
| Classification               | Internal — Credit Risk Management                    |
| Distribution                 | Credit Risk, Model Risk Management, Internal Audit, External Examiners (upon request) |

---

## 1. Purpose and Scope

### 1.1 Purpose

This Credit Policy establishes the governing rules under which the Credit Risk
and Fraud Detection Platform (hereafter "the Platform") may be used to
underwrite, price, provision for, and capital-charge consumer credit
originations and the existing loan book. It codifies the approved risk
appetite, decisioning rules, hard policy floors, override authority,
model-use boundaries, and documentation requirements. The Platform operates
within the limits set by this Policy and does not extend credit outside them.

### 1.2 Scope

This Policy applies to:

1. All new consumer credit applications processed through the Platform,
   including unsecured personal loans and secured Home Equity Lines of
   Credit (HELOC).
2. Portfolio-level monitoring, stress testing, and regulatory reporting
   produced by the Platform.
3. All staff involved in credit decisioning, model governance, validation,
   and reporting.

This Policy does not apply to:
- Commercial lending, small-business lending, or any non-consumer exposure.
- Automotive secured lending, mortgage origination, or credit card issuance
  (governed by product-specific policies).
- Any activity inconsistent with the Platform's intended use as described
  in the Model Card.

### 1.3 Regulatory Framework

This Policy is designed to operate within the following regulatory
frameworks. Where this Policy and a regulatory requirement are in tension,
the regulatory requirement prevails.

- **OSFI Guideline B-20** — Residential Mortgage Underwriting Practices (HELOC
  portion), including LTV ceilings and qualifying rate treatment.
- **OSFI Guideline E-23** — Enterprise-Wide Model Risk Management, including
  model validation, documentation, and monitoring.
- **Basel III** — Capital adequacy under the Internal Ratings-Based (IRB)
  approach for credit risk, including OSFI CAR requirements.
- **IFRS 9** — Financial Instruments, specifically Expected Credit Loss (ECL)
  provisioning under the three-stage approach.
- **Equal Credit Opportunity Act (ECOA) / Regulation B** — Adverse action
  disclosure requirements. While ECOA is US law, the Platform's disclosure
  standards meet both ECOA and Canadian FCAC requirements.
- **Financial Consumer Agency of Canada (FCAC)** — Consumer protection,
  including prohibited adverse-action disclosure content.
- **Criminal Code of Canada s.347** — Maximum effective interest rate (35%
  APR, effective January 2025).
- **Personal Information Protection and Electronic Documents Act (PIPEDA)**
  — Personal data handling.

---

## 2. Risk Appetite

### 2.1 Philosophy

The Platform targets a prime-to-near-prime consumer book with a controlled
tail of near-subprime exposure. The institution's risk appetite explicitly
avoids deep-subprime exposure (risk tier E represents less than 10% of
originations on a trailing 12-month basis) and prohibits any exposure
inconsistent with the Code of Conduct or the institution's public
commitments.

### 2.2 Quantitative Limits — Approved by the Board

The following risk limits are approved by the Credit Risk Committee and
ratified by the Board. Any breach is reported to the CRO within 1 business
day and to the Board Risk Committee at its next regular meeting.

| Metric                                           | Limit / Target        | Escalation Trigger |
|--------------------------------------------------|-----------------------|--------------------|
| Portfolio Expected Loss rate (EL / EAD)          | Target ≤ 5.0% · Limit ≤ 8.0% | Limit breach → CRO notify + corrective action plan within 30 days |
| Unsecured personal loan share of total EAD       | Target ≤ 75% · Limit ≤ 85% | Approaching limit (>80%) → concentration review |
| Tier E (high-risk subprime) share of originations (T12M) | Target ≤ 5% · Limit ≤ 10% | Limit breach → origination tightening |
| Portfolio 12-month OOT PD calibration gap       | Target ± 1 pp · Limit ± 2 pp | Limit breach → model recalibration review |
| IFRS 9 Stage 2 loan share                        | Monitor only; no hard limit | > 20% → Investigation of macro or underwriting change |
| Fraud rate (confirmed, T12M)                     | Target ≤ 1.5% · Limit ≤ 3.0% | Limit breach → fraud control review |
| Capital Adequacy Ratio (CET1)                    | Target ≥ 11.5% · Limit ≥ 8.0% (Pillar 1) | Limit approach (< 10%) → capital planning review |
| Single-tier EL concentration ratio (EL share / loan share) | Target ≤ 3.0× · Limit ≤ 4.0× for any one tier | Limit breach → tier-level review |

### 2.3 Prohibited Exposures

The Platform shall not be used to decision, approve, or price credit for:
- Applicants under 18 years of age or over 80 years of age (except in
  exceptional cases reviewed by senior underwriting).
- Applicants with active bankruptcy proceedings or an undischarged bankruptcy
  on file.
- Applicants flagged by Office of Foreign Assets Control (OFAC) sanctions
  screening or equivalent Canadian screening.
- Loans for purposes prohibited by law or institutional policy (gambling
  consolidation, certain speculative investments, etc.).
- Applicants where fraud confirmation has been escalated to law enforcement
  or where a prior fraud incident is on file (subject to institutional
  fraud-recovery review).

---

## 3. Hierarchical Decision Engine

### 3.1 Overview

Every credit application processed by the Platform is routed through five
ordered decision gates. The order of evaluation is fixed and cannot be
overridden by any operator. A decline at an earlier gate terminates
evaluation — subsequent gates are not evaluated.

### 3.2 Gate 1 — Fraud Screening

The Platform generates a post-funding-style fraud probability at application
time using 14 fraud-specific features (application-time red flags, velocity
and loan-stacking signals, synthetic identity indicators, first-payment
default risk proxies).

**Rule:** If fraud probability > 65%, the decision is DECLINE_FRAUD.

**Adverse action treatment:** Under FCAC guidance (confirmed in writing by
Legal, February 2024), a lender MUST NOT cite fraud as the decline reason
in the adverse action letter sent to the applicant. The Platform uses a
generic decline reason from the approved adverse-action-reason list. The
fraud status is recorded in the internal decision audit trail for
investigation purposes only.

**Operational requirement:** Fraud declines at HIGH or CONFIRMED alert tiers
require escalation to the Fraud Investigations team within 24 hours.

### 3.3 Gate 2 — Hard Policy Rules

If Gate 1 passes, the Platform evaluates hard policy rules. Any rule
failure is a DECLINE_POLICY outcome. Hard policy rules represent institutional
floors; they cannot be overridden by any compensating factors and do not
consider the output of the credit model.

**Rule set (v1.1):**

| Rule ID | Condition                                  | Threshold                         | Product Scope |
|---------|--------------------------------------------|-----------------------------------|---------------|
| P-01    | Minimum FICO / Equivalent                  | Credit score < 500                | All           |
| P-02    | Maximum Debt-to-Income                     | DTI > 50%                         | All           |
| P-03    | Maximum Derogatory Marks                   | Derogatory marks ≥ 3              | All           |
| P-04    | Maximum Recent Inquiries (6 months)        | Inquiries > 10                    | All           |
| P-05    | Maximum LTV (HELOC only, OSFI B-20 aligned)| LTV > 90%                         | HELOC only    |

**Adverse action treatment:** When a hard policy rule fails, the adverse
action letter cites the specific failed rule in plain language. SHAP-based
reasons are NOT used — the credit model did not run. Example text:
*"Your credit score of 472 is below the minimum of 500 required for this
product. This is an absolute requirement; compensating factors do not apply."*

### 3.4 Gate 3 — Credit Model Scoring

If Gates 1-2 pass, the PD model scores the application. The output is a
calibrated 12-month point-in-time probability of default (PD_PIT) on a 0-100%
scale, which is mapped to:

- A credit score on the 300-850 PDO scale (Base Score 600, base_odds 4.0,
  Points-to-Double-Odds 20).
- A risk tier: A (score ≥ 720), B (680-719), C (630-679), D (580-629),
  E (< 580).
- A through-the-cycle (TTC) PD for Basel III capital computation.
- An IFRS 9 stage (1 = Performing, 2 = Significant Increase in Credit Risk,
  3 = Impaired).

### 3.5 Gate 4 — Decision Bands

The PD_PIT determines the approval band:

| PD_PIT              | Decision        | Treatment                                           |
|---------------------|-----------------|-----------------------------------------------------|
| PD ≤ 28%            | APPROVE         | Automated approval (subject to Gate 5 review)       |
| 28% < PD ≤ 35%      | REFER           | Human analyst review required                       |
| PD > 35%            | DECLINE_CREDIT  | Credit decline with SHAP-derived adverse reasons    |

**Refer band operational requirements:** A Tier C or Tier D application in
the refer band must be reviewed by a credit analyst holding at least Level 2
credit authority. The analyst may consider compensating factors not captured
by the model: employment stability trend (not just tenure), demonstrated
asset position, depth of relationship with the institution, reasons for
derogatory marks (if any), and any information not present in the bureau
file. The analyst's final decision (APPROVE or DECLINE_CREDIT) and rationale
must be documented in the credit file.

### 3.6 Gate 5 — Human Authority Matrix

Even when the Platform returns APPROVE, certain applications require human
review per the Institution's Underwriting Authority Matrix:

| Loan Condition                              | Required Authority                    |
|---------------------------------------------|---------------------------------------|
| Tier A or B, amount ≤ $15,000               | Platform-automated (no human required)|
| Tier A or B, amount > $15,000               | Level 1 underwriter                   |
| Tier C, any amount                          | Level 1 underwriter                   |
| Tier C, amount > $15,000                    | Level 2 underwriter                   |
| Tier D, any amount                          | Level 2 underwriter                   |
| Tier E                                      | Level 3 underwriter + Credit Risk CRC review |
| HELOC, any amount                           | Level 2 underwriter + secured-lending specialist |
| HELOC with LTV > 80%                        | Level 3 underwriter |
| Exception to any hard policy rule           | Level 3 + CRO ratification           |

---

## 4. Product-Specific Requirements

### 4.1 Unsecured Personal Loans

- **Loan amount:** Minimum $1,000, maximum $100,000 per applicant.
- **Term:** 36 or 60 months only. The PD model has been trained on these
  two terms; any other term is outside the model's validated range.
- **Rate:** Risk-based; Criminal Code s.347 35% APR ceiling enforced.
  See §6.
- **Payment-to-Income:** PTI ceiling 20% of gross monthly income. Measured
  on the amortizing payment at the approved APR.
- **Purpose:** Consolidation, home improvement, medical, major purchase,
  debt refinance, and other lawful purposes. Excluded purposes: gambling,
  investment in securities (speculative), business financing, and any purpose
  inconsistent with §2.3.

### 4.2 Home Equity Line of Credit (HELOC)

- **Line amount:** Minimum $10,000, maximum $500,000 per property.
- **LTV:** Maximum 90% (OSFI B-20 aligned). Maximum combined LTV (first
  mortgage + HELOC) 80%.
- **Term:** Not directly comparable across books; the Platform standardises
  HELOC `loan_term_months` to 36 for scoring purposes (see §8.5).
- **Rate:** Variable, tied to prime rate; subject to the same 35% ceiling.
- **Qualifying rate:** Applicant must qualify at the greater of the contract
  rate + 200 bps or the OSFI benchmark qualifying rate (per B-20).
- **Collateral:** Property appraisal required. Acceptable properties:
  owner-occupied detached, semi-detached, townhouse, condominium. Excluded:
  rental properties with more than 2 units, commercial real estate, vacant
  land.

---

## 5. Override Authority

### 5.1 Hard Policy Overrides

Hard policy rules (§3.3) cannot be overridden by front-line underwriters.
An exception requires:
1. A documented rationale in the credit file
2. Sign-off from a Level 3 underwriter
3. CRO ratification in the monthly Credit Risk Committee exception report
4. Year-over-year reporting to the Board Risk Committee

The following hard rules may NOT be overridden under any circumstances:
- P-01 if the applicant's credit score < 450
- P-05 (HELOC LTV > 90%) — absolute regulatory limit
- Any Gate 1 (Fraud) decline at CONFIRMED alert tier

### 5.2 Model Decision Overrides

A credit analyst may override a Platform APPROVE decision to DECLINE for
cause, or override a REFER/DECLINE_CREDIT decision to APPROVE based on
documented compensating factors. Overrides are logged in the decision audit
trail with analyst ID, timestamp, rationale, and authority level.

**Override monitoring:** The monthly Credit Risk Committee report tracks
override rates by analyst, by tier, and by direction. Override rates above
15% for any single analyst trigger a calibration review.

### 5.3 Pricing Overrides

An APR below the Platform's recommended risk-based rate requires:
1. Documented strategic rationale (relationship pricing, acquisition campaign,
   etc.)
2. Level 3 authorization
3. Inclusion in the monthly concession-pricing report

An APR above the Platform's recommended rate is NOT permitted — the risk-based
recommendation already represents the maximum defensible rate under the
CoF + EL + OpEx + ROE construction.

---

## 6. Risk-Based Pricing

### 6.1 Rate Construction

The Platform computes the recommended APR as:

$$\text{APR} = \min\left(\text{CoF} + \text{EL rate} + \text{OpEx} + \text{ROE target} - \text{Collateral adjustment},\ \ 35\%\right)$$

Where:
- **CoF** (Cost of Funds) is published weekly by Treasury
- **EL rate** = PD × LGD
- **OpEx** = 1.5% (approved institutional assumption, reviewed annually)
- **ROE target** = 2.0% (approved institutional assumption, reviewed annually)
- **Collateral adjustment** (HELOC only): -0.5 bps per 10 percentage points
  of LTV below 80%, capped at -200 bps

### 6.2 Criminal Code Compliance

Under Section 347 of the Criminal Code of Canada (effective January 2025),
the effective annual rate (including fees) may not exceed 35%. The Platform
applies this cap at the APR construction step and flags all tier-E applications
that require the cap.

**Operational consequence of the cap:** Tier E applicants whose uncapped
rate exceeds 35% must be DECLINED rather than approved at the capped rate.
This is because the capped rate does not cover expected loss plus operating
costs, rendering the loan unprofitable and indirectly incentivizing risky
origination. The Platform Tab 5 (Risk-Based Pricing) documents this
mechanism explicitly.

### 6.3 Pricing Committee Review

The Pricing Committee reviews the rate schedule quarterly to incorporate:
- Updated Treasury CoF
- Portfolio-derived tier mid-PDs (not hardcoded; the Platform re-computes
  these each run)
- Competitive benchmarks (Tab 5 shows six Canadian lender segments)
- Cost-of-funds sensitivity analysis (Tab 5 Section 5)

---

## 7. Capital, Provisioning, and Stress Testing

### 7.1 Basel III IRB Capital

The Platform implements the Internal Ratings-Based (IRB) approach:

$$K = \text{LGD} \cdot N\left[\frac{G(\text{PD})}{\sqrt{1-R}} + \sqrt{\frac{R}{1-R}} \cdot G(0.999)\right] - \text{PD} \cdot \text{LGD}$$

$$\text{RWA} = 12.5 \cdot K \cdot \text{EAD}$$

Where R is the per-product asset correlation, N is the standard normal CDF,
and G is its inverse. Capital is computed at the 99.9th percentile — sufficient
to survive all but a 1-in-1000 year loss event.

**Reported Capital Adequacy Ratio (CAR):**

$$\text{CAR} = \frac{\text{Available CET1 Capital}}{\text{Total RWA}}$$

The OSFI Pillar 1 minimum is 8%. The institution's internal D-SIB-equivalent
CET1 target is 11.5%, plus the 2.5% Capital Conservation Buffer.

**In the Platform demonstration**, available capital is assumed to be 11.5% ×
RWA (matching the internal target); in production the numerator comes from
the booked CET1 balance in the OSFI return.

### 7.2 IFRS 9 Expected Credit Loss

The Platform computes ECL provisions per the three-stage model:

- **Stage 1 (Performing)**: 12-month ECL = PD × LGD × EAD
- **Stage 2 (Significant Increase in Credit Risk)**: Lifetime ECL on a
  discounted cash flow basis, using the effective interest rate at origination
  and the monthly PD curve
- **Stage 3 (Impaired)**: Lifetime ECL, typically 40-80% coverage of EAD

**Staging triggers:**
- **Stage 2 triggers** (any one is sufficient): PD has increased > 20% from
  origination; credit score has dropped 30+ points; 30+ days past due
- **Stage 3 triggers**: PD ≥ 70%; 90+ days past due; bankruptcy filing;
  unlikeliness to pay determination

**Origination PD proxy** — for historical cohorts where booked-at-origination
PD is unavailable, the Platform uses LendingClub grade as a proxy (A=4%,
B=8%, C=13%, D=20%, E=28%, F=35%, G=40%). This is documented as a known
limitation (see §8.3). In a production setting, origination PD must come
from the Loan Origination System at the time of booking (per IFRS 9 ¶5.5.11).

### 7.3 Macroeconomic Stress Testing

Three scenarios are run quarterly or when OSFI provides updated scenarios:

| Scenario           | PD Multiplier | LGD Multiplier | Calibration                                 |
|--------------------|---------------|----------------|---------------------------------------------|
| Base Case          | 1.0×          | 1.00×          | Continuation of current macro conditions   |
| Adverse Scenario   | 1.4×          | 1.15×          | Moderate recession — plausible downside    |
| Severe Scenario    | 2.0×          | 1.35×          | Deep recession — 2008-09 magnitude tail risk |

**Known simplification:** the v1.0 implementation holds LGD constant across
scenarios. For HELOC specifically, a 2008-style house price shock (-25% to
-35%) would raise HELOC LGD from ~30% to 50-60% per Freddie Mac historical
data. This is documented in the Model Card and flagged for v1.2 enhancement.

**Severe-scenario capital shortfall reporting:** If the severe scenario
implies required capital exceeds available capital at the 11.5% CET1 target,
the Platform generates a Capital Shortfall report for the CRO, triggering
one of three actions: (a) capital raise, (b) portfolio reduction, or (c)
risk appetite adjustment. OSFI is notified per the Institution's supervisory
relationship protocol.

---

## 8. Model Governance

### 8.1 Approved Models

Under OSFI E-23, only models with a current approved Model Card (see
MODEL_CARD.md) may be used for decisioning. As of the Effective Date, the
approved models are:

| Model                           | Use                                    | Status     |
|---------------------------------|----------------------------------------|------------|
| PD XGBoost (v1.0 unified)       | Primary PD decisioning, cross-product  | Champion   |
| PD Scorecard (v1.0 logistic)    | Benchmark / explanation support        | Reference  |
| PD XGBoost Segmented (v1.1)     | Per-product monitoring, challenger     | Challenger |
| LGD Regression (v1.0)           | LGD estimation for EL and RWA          | Champion   |
| Fraud XGBoost (v1.0)            | Pre-approval fraud screening           | Champion   |

### 8.2 Champion / Challenger Framework

The v1.1 per-product segmented PD models run in parallel with the v1.0
unified champion, generating shadow scores for every application. The
Model Risk Management team produces a monthly divergence report. A challenger
is eligible for promotion to champion if all of the following are true for
two consecutive quarters:

- AUC on OOT test data is at least 0.02 absolute AUC above the champion
- Calibration gap is within ± 2 percentage points
- Fairness metrics across the five monitored segments do not show material
  deterioration
- No policy or regulatory conflict is introduced

Promotion requires CRO approval and Credit Risk Committee ratification.

### 8.3 Monitoring and Retraining Triggers

The Platform runs monthly monitoring (Tab 3, Section 8 — Feature Stability).
Per OSFI E-23, a model must be reviewed if the Population Stability Index
(PSI) exceeds 0.25 on the model score or on any input feature. A full
model review is triggered, with a 90-day window to document findings and a
recommendation (retrain, retire, no action).

Automatic retraining is NOT permitted without model governance sign-off.

### 8.4 Fair Lending Compliance

The Platform includes a fairness-audit view (Tab 3, Section 9) using
demographic parity (approval-rate gap) and equalized odds (TPR/FPR gap)
across five operationally-available segments: loan purpose, home ownership,
LendingClub grade, product type, and income verification status. The EEOC
four-fifths rule is used as the primary disparity threshold.

**Scope limitation:** This fairness audit is exploratory and
monitoring-oriented. It is NOT a full protected-class disparate impact
analysis — public datasets do not contain race, gender, or national origin
proxies. Before the Platform is used in production, a proxy-based disparate
impact analysis must be commissioned from a qualified compliance consultant,
and all findings must be addressed.

### 8.5 Known Limitations Requiring Disclosure

The following limitations must be disclosed in any model validation report,
OSFI submission, or external examiner engagement:

1. **Training data is US-origin (LendingClub).** Canadian market
   dynamics may differ.
2. **HELOC-specific features are synthetic proxies** (income, LTV,
   DTI) engineered from bureau data.
3. **Reject inference applied via augmentation method.** Not a
   behavioural override.
4. **No forward-looking macro in the PD model itself.** Macro is
   handled separately via PIT→TTC conversion and stress multipliers.
5. **Performance metrics reflect the proxy-adjusted data.** Re-validation
   required on a real production portfolio.
6. **`loan_term_months` is a product-type proxy** in the v1.0 unified
   model. Neutralized at scoring time for HELOC (standardised to 36);
   removed structurally in the v1.1 segmented challenger.
7. **Fraud labels are synthetic.** Real AUC on investigation labels
   would be 0.72-0.85.
8. **IFRS 9 origination PD is proxied** using LendingClub grade.
   Would not be acceptable for regulatory submission.
9. **Stress-test LGD held constant.** Real HELOC LGD rises under
   house-price shock (30%→60% during GFC).

---

## 9. Adverse Action Compliance

### 9.1 Requirement

All DECLINE and REFER decisions must generate an adverse action letter
that complies with ECOA / Regulation B and FCAC requirements. The letter
must:

1. Be sent within 30 days of the adverse action decision.
2. State the specific reasons for the adverse action (generic reasons
   such as "credit risk" are not sufficient).
3. Inform the applicant of the right to a free credit report from the
   credit reporting agency used.
4. Provide contact information for disputes.
5. NOT cite fraud as the decline reason, even if fraud is the true
   cause (FCAC guidance).

### 9.2 Reason Generation

The Platform generates adverse action reasons per the following rules:

- **DECLINE_FRAUD**: generic reason from the approved adverse-action
  reason list; fraud status recorded only in the internal decision audit
  trail.
- **DECLINE_POLICY**: the specific failed policy rule in plain language.
  SHAP reasons are NOT used because the credit model never ran.
- **DECLINE_CREDIT / REFER**: SHAP-derived reasons, filtered for:
  - Non-bureau signals (internal flags, interaction features)
  - Product proxies (`loan_term_months`)
  - Features with healthy values (never tell a 0-inquiry applicant
    "too many inquiries")
- **DECLINE** (any cause) with counterfactual recourse: up to 3
  single-feature paths that would cross the approval threshold, where
  the feature is something the applicant can realistically modify.

### 9.3 Letter Generation

The Platform uses a local LLM (Llama 3 via Ollama) to draft the letter,
with a template fallback. The LLM is deployed locally for PIPEDA
compliance — no applicant PII is transmitted externally. The generated
letter is reviewed against a checklist before dispatch.

---

## 10. Data Governance

### 10.1 Data Sources

The Platform consumes data from:

- **Credit bureau** — Equifax Canada (primary), TransUnion Canada (backup).
  Hard pull with applicant consent at origination.
- **Income verification** — Equifax The Work Number or direct employer
  confirmation; stated-income only for Tier A with > 5-year tenure.
- **Alternative data (pre-production)** — Equifax NeoBureau, Borrowell
  Rental Advantage. Currently synthesized (`alt_data_score`) as a proxy;
  v1.2 roadmap includes real-data integration.
- **Internal data** — Application form, internal banking data for existing
  customers, decisioning history.

### 10.2 Data Retention and Destruction

- **Applicant PII** retained per PIPEDA guidelines and institutional policy
  — 7 years from last activity, then destroyed per secure-destruction
  procedures.
- **Decision audit trails** retained 7 years.
- **Model training data** retained indefinitely (anonymized); retraining
  uses only anonymized or aggregate data.

### 10.3 Data Quality

Each origination record is validated at application time: required fields
present, numeric ranges plausible, date formats parseable, credit bureau
pull successful. Records failing validation are routed to manual review.

---

## 11. Roles and Responsibilities

| Role                              | Responsibility                                                  |
|-----------------------------------|-----------------------------------------------------------------|
| **Chief Risk Officer (CRO)**      | Overall accountability for credit risk. Ratifies exceptions.    |
| **Credit Risk Committee (CRC)**   | Monthly review of exceptions, override rates, concentration, capital. |
| **Head of Credit Risk**           | Day-to-day portfolio management; triggers policy reviews.       |
| **Credit Analysts (Level 1-3)**   | Decision-making within authority matrix; documented rationale.  |
| **Model Risk Management (MRM)**   | Validation, monitoring, challenger shadow-scoring, PSI triggers.|
| **Fraud Operations**              | Handle fraud escalations; update fraud feature definitions.     |
| **Internal Audit**                | Independent review of Policy adherence and Model Card evidence. |
| **Legal & Compliance**            | ECOA, Reg B, FCAC, Criminal Code, PIPEDA, OFAC alignment.       |
| **Treasury**                      | CoF publication; capital planning; stress-scenario ingestion.   |
| **External Examiners (OSFI)**     | Supervisory review of the Platform under B-20, E-23, Basel III. |

---

## 12. Exceptions and Corrective Action

### 12.1 Exception Reporting

Any breach of this Policy is logged in the monthly Exception Report and
presented at the Credit Risk Committee. The report includes:
- Breach description and root cause
- Loans affected (count and $ amount)
- Corrective action taken or proposed
- Owner and target completion date

### 12.2 Corrective Action

Corrective actions are classified by severity:
- **Critical** — regulatory breach, CRO-level breach of limit, material
  compliance failure. Resolved within 30 days.
- **Significant** — approaching a limit, systemic process failure.
  Resolved within 60 days.
- **Minor** — one-off procedural error. Resolved within 90 days.

All corrective actions are tracked in the Institution's GRC system.

### 12.3 Regulatory Notifications

Breaches requiring OSFI notification are identified by Legal & Compliance
and routed through the CRO. Standard notification categories include:
- Material capital adequacy concerns (§7.3)
- Systemic model validation failures (§8.2)
- Material fair-lending findings (§8.4)

---

## 13. Review and Approval

This Policy is reviewed annually by the Credit Risk Committee. Amendments
require CRO approval and Board Risk Committee ratification. Emergency
amendments (e.g., for regulatory changes) may be approved by the CRO with
Board notification at the next regular meeting.

---

## 14. Document Revision History

| Version | Date         | Author          | Summary of Changes                                 |
|---------|--------------|-----------------|----------------------------------------------------|
| 1.0     | March 2026   | Credit Risk     | Initial Policy. Unified PD model. 9-phase platform.|
| 1.1     | April 2026   | Credit Risk     | Added v1.1 segmented challenger model; disclosed `loan_term_months` product proxy in §8.5.6; added HELOC term-standardisation note; corrected CAR methodology disclosure in §7.1. |

---

## 15. Related Documents

- **MODEL_CARD.md** — OSFI E-23 Model Card for all approved models
- **PRODUCT_GUIDE.md** — Functional description of the Platform
- **README.md** — Public-facing project overview
- **QUICKSTART.md** — Platform installation and operation guide

---

## Signatures

**Approved by:**

____________________________________
Chief Risk Officer · Date

____________________________________
Head of Credit Risk · Date

____________________________________
Head of Model Risk Management · Date

**Ratified by:**

____________________________________
Chair, Credit Risk Committee · Date

____________________________________
Chair, Board Risk Committee · Date

---

*End of Policy Document · CRP-POL-001 v1.1 · Internal — Credit Risk Management*
