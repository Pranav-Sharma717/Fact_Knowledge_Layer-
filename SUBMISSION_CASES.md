# Submission Cases: Fact Knowledge Layer

This document details the four core cases required for evaluation, demonstrating how the system extracts, grounds, compares, and reconciles facts across unstructured PDF documents.

---

## 1. Corroborated Fact Across Documents

- **Claim**: ACME Corp workforce headcount reached 120 employees by December 2023.
- **Source Document A** (`doc_2023.pdf`, Page 1):
  - *Verbatim Quote*: `"The company headcount reached 120 employees by December 2023."`
  - *Extracted Fact*: `{subject: "Workforce headcount", predicate: "reached", value: "120", unit: "employees", time_scope: "December 2023"}`
- **Source Document B** (`doc_2024.pdf`, Page 1):
  - *Verbatim Quote*: `"Company headcount as of December 2023 was confirmed at 120 employees."`
  - *Extracted Fact*: `{subject: "Workforce headcount", predicate: "confirmed at", value: "120", unit: "employees", time_scope: "December 2023"}`
- **System Reasoning**:
  - Embedding vector similarity between candidate facts: `0.81` ($> 0.35$ threshold).
  - LLM Relationship Judge classifies relationship as `CORROBORATES` because both documents state identical employee counts for the exact same timeframe.
  - **Confidence Impact**: $+0.15$ boost applied to final confidence score.

---

## 2. Genuine Contradiction

- **Claim**: Directly conflicting numerical metrics reported for the exact same timeframe without explanation.
- **Source Document A**:
  - *Verbatim Quote*: `"Operating expenditure in 2023 totaled $1.2 million."`
- **Source Document B**:
  - *Verbatim Quote*: `"Operating expenditure in 2023 totaled $1.9 million."`
- **System Reasoning**:
  - Vector similarity pairs candidate facts for analysis.
  - LLM Relationship Judge classifies relationship as `CONTRADICTS` because values ($1.2M vs $1.9M) conflict for the identical scope without any restatement context.
  - **Confidence Impact**: $-0.25$ penalty applied to final confidence score.

---

## 3. Apparent Contradiction Reconciled by Context

- **Claim**: Reported 2023 revenue differs between 2023 disclosure ($5.2M) and 2024 update ($5.5M).
- **Source Document A** (`doc_2023.pdf`, Page 1):
  - *Verbatim Quote*: `"In FY2023, ACME Corp reported total revenue of $5.2 million."`
- **Source Document B** (`doc_2024.pdf`, Page 1):
  - *Verbatim Quote*: `"Following an independent audit in Q1 2024, ACME Corp restated its 2023 revenue to $5.5 million due to revenue recognition adjustments."`
- **System Reasoning**:
  - LLM Relationship Judge identifies the apparent numerical discrepancy ($5.2M vs $5.5M) and checks for contextual modifiers.
  - It detects the contextual clause `"Following an independent audit in Q1 2024 ... restated its 2023 revenue"`.
  - Classifies relationship as `RECONCILED` (audit restatement context).
  - **Confidence Impact**: $+0.05$ minor adjustment (reconciled contradiction is noted rather than penalized).

---

## 4. Extraction & Reasoning Failure Handling

- **Failure Mode**:
  1. **LLM Quote Hallucination**: The LLM summarizes or rewrites text instead of returning a verbatim quote.
  2. **Boundary Truncation**: A sentence spanning across chunk boundaries gets split, resulting in incomplete quote matching.
- **System Mitigation**:
  - **Verbatim Substring Grounding Verification** (`verify_grounding`): The system checks if `raw_quote` exists as an exact or normalized substring inside the source chunk text.
  - If a quote is hallucinated or absent from the source chunk:
    - `grounding_confidence` drops to `0.0`.
    - `final_confidence` $= \text{extraction\_confidence} \times 0.0 = 0.0$.
  - Low-confidence or ungrounded facts are automatically filtered out, preventing hallucinated claims from polluting the knowledge layer.
