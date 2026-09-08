# Submission Cases Showcase — Fact Knowledge Layer

This document details the **4 required submission cases** for evaluation on the starter datasets (Delhivery Corporate Filing Excerpts & India Macroeconomy Reports).

---

## Case 1: Corroborated Fact Across Documents

### Description
Both documents assert the exact same metric value, entity, and reporting period. Evidence grounding is verified against source chunks, and final confidence is increased via corroboration.

### Grounded Evidence Case
- **Entity**: `Delhivery Limited`
- **Metric**: `Express Parcel Services Volume`
- **Normalized Value**: `289,200,000 parcels` (`289.20 million`)
- **Period**: `FY 2023`

#### Source A Evidence
- **Document**: `02-delhivery-annual-report-fy24-excerpt.pdf`
- **Page**: `Page 42`
- **Verbatim Quote**: `"Express parcel volume reached 289.20 million parcels in FY23."`
- **Grounding Confidence**: `100.0%` (Exact verbatim match)

#### Source B Evidence
- **Document**: `03-delhivery-q4-fy24-earnings-presentation.pdf`
- **Page**: `Page 8`
- **Verbatim Quote**: `"FY23 Express Parcel Volume: 289.20 million."`
- **Grounding Confidence**: `100.0%` (Exact verbatim match)

### System Classification & Scoring
- **Relationship Enum**: `CORROBORATES`
- **Reconciliation Type**: `NONE`
- **Delta Applied**: `+0.20`
- **Reasoning**: Both documents corroborate the exact same metric value (289.20 million parcels) for FY 2023.

---

## Case 2: Genuine Contradiction

### Description
Two documents report conflicting numerical figures or claims for the exact same metric, entity, and time scope, without explicit contextual reconciliation in the source text.

### Grounded Evidence Case
- **Entity**: `Delhivery Limited`
- **Metric**: `Restated Revenue from Operations`
- **Period**: `FY 2022`

#### Source A Evidence
- **Document**: `01-delhivery-prospectus-2022-excerpt.pdf`
- **Page**: `Page 18`
- **Verbatim Quote**: `"Revenue from operations for the financial year 2022 was ₹68,814.93 million."`
- **Normalized Value**: `₹68,814,930,000.0 INR`

#### Source B Evidence
- **Document**: `02-delhivery-annual-report-fy24-excerpt.pdf`
- **Page**: `Page 105`
- **Verbatim Quote**: `"Revenue from operations for FY22 was reported as ₹72,110.00 million."`
- **Normalized Value**: `₹72,110,000,000.0 INR`

### System Classification & Scoring
- **Relationship Enum**: `CONTRADICTS` / `LIKELY_CONTRADICTION`
- **Percentage Delta**: `4.67%`
- **Confidence Penalty**: `-0.30`
- **Reasoning**: Significant direct numerical contradiction (₹68,814.93M vs ₹72,110.00M) for FY 2022 revenue without explicit reconciliation in quote.

---

## Case 3: Reconciled Contradiction by Context

### Description
An apparent numerical or semantic discrepancy across documents is successfully resolved and reconciled by contextual metadata, such as unit normalization, rounding margins, reporting period differences, or audit restatements.

### Grounded Evidence Case (Unit Normalization & Period Difference)
- **Entity**: `Delhivery Limited`
- **Metric**: `Revenue from Operations`

#### Source A Evidence
- **Document**: `01-delhivery-prospectus-2022-excerpt.pdf`
- **Page**: `Page 14`
- **Raw Claim**: `₹36,465.28 million`
- **Normalized Value**: `₹36,465,280,000.0 INR`
- **Period**: `FY 2021`

#### Source B Evidence
- **Document**: `02-delhivery-annual-report-fy24-excerpt.pdf`
- **Page**: `Page 60`
- **Raw Claim**: `₹81,415.38 million` (`₹8,141.538 crore`)
- **Normalized Value**: `₹81,415,380,000.0 INR`
- **Period**: `FY 2024`

### System Classification & Scoring
- **Relationship Enum**: `RECONCILED`
- **Reconciliation Type**: `PERIOD_DIFFERENCE` (and `UNIT_CONVERSION`)
- **Confidence Delta**: `+0.10`
- **Reasoning**: Apparent revenue growth discrepancy (₹36,465.28M vs ₹81,415.38M) is reconciled by differing reporting periods (FY 2021 vs FY 2024).

---

## Case 4: Extraction & Reasoning Failure Handling

### Description
Demonstrates the system's ability to catch, invalidate, and log noisy candidate extractions (table unit headers, context-less numbers, bare unit keywords) into a dedicated ledger rather than propagating invalid facts into downstream relationship matching.

### Logged Failure Case in `rejected_extractions`
- **Document**: `02-delhivery-annual-report-fy24-excerpt.pdf`
- **Page**: `Page 101`
- **Candidate Text**: `"(₹ in million)"`
- **Attempted Extraction**: `{"entity": "Unknown Entity", "metric": "Table Unit Header", "value": "(₹ in million)"}`
- **Failure Type**: `TABLE_HEADER_WITHOUT_VALUE`
- **Rejection Reason**: `"Detected a table-wide unit label or header ('(₹ in million)') without associated entity or metric."`

### Additional System Safeguard
- **Evidence Grounding Fallback**: If an LLM candidate contains a hallucinated quote not present in source chunk text, `grounding_confidence` evaluates to `0.0`, dropping `final_confidence` to `0.0` and marking status as `rejected`.
- **Unrelated Metrics Filter**: If two facts share identical values (e.g. `0.00% == 0.00%`) but concern distinct metrics (e.g. `EBITDA Margin` vs `Employee Attrition Rate`), `calculate_comparability_score` evaluates to `0.0`, classifying the pair as `UNRELATED` and preventing false corroborations.
