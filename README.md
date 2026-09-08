# Fact Knowledge Layer — Superjoin Internship Assignment

A production-grade Python + FastAPI system designed to extract MEANINGFUL atomic facts from unstructured financial and economic PDFs, ground them to verbatim source evidence, validate candidates, normalize units/magnitudes, filter comparability across documents, classify cross-document relationships into 6 strict categories, store rejected extractions, and reconcile apparent contradictions using contextual evidence.

---

## Architecture & Workflow

```text
┌─────────────────┐     ┌───────────────────────┐     ┌────────────────────────┐
│ Upload PDF File │ ──> │ PyMuPDF Chunking      │ ──> │ SQLite Storage         │
│ Arbitrary PDFs  │     │ Page-Anchored (500-800)│     │ documents & chunks     │
└─────────────────┘     └───────────────────────┘     └────────────────────────┘
                                                                  │
                                                                  ▼
┌─────────────────────────┐     ┌───────────────────────┐     ┌────────────────────────┐
│ Candidate Normalization │ <── │ LLM Fact Extraction   │ <── │ Validation Engine      │
│ INR/USD/Cr/Mn/Parcels/% │     │ Entity & Metric Schema│     │ Filter Headers & Noise │
└─────────────────────────┘     └───────────────────────┘     └────────────────────────┘
             │                                                            │ (Rejected)
             ▼                                                            ▼
┌─────────────────────────┐     ┌───────────────────────┐     ┌────────────────────────┐
│ Comparability Filter    │ ──> │ Cross-Doc Matcher     │ ──> │ Rejected Extractions   │
│ Entity & Metric Match   │     │ 6 Strict Enums &      │     │ Task 8 Ledger          │
└─────────────────────────┘     │ Reconciliation Engine │     └────────────────────────┘
                                └───────────────────────┘
                                            │
                                            ▼
                                ┌───────────────────────┐
                                │ Dynamic Rescoring &   │
                                │ Glassmorphism Dashboard│
                                └───────────────────────┘
```

### Key Engineering Features

1. **PDF Ingestion & Page-Anchored Chunking**:
   - Parses PDFs using `PyMuPDF` into ~500–800 token chunks.
   - Preserves exact `page_number` (1-indexed), `start_char`, and `end_char` offsets in SQLite.

2. **Candidate Extraction & Grounding Verification**:
   - Structured JSON fact extraction per chunk via OpenRouter (`meta-llama/llama-3.3-70b-instruct:free` or `google/gemma-4-31b-it:free`).
   - Verbatim substring matching verifies `raw_quote` against source chunk text (`grounding_confidence`).

3. **Normalization & Canonical Units**:
   - Converts raw strings into numeric values and canonical units (`INR`, `USD`, `parcels`, `employees`, `%`).
   - Handles Indian numbering system (`crore`, `lakh`) and Western magnitude multipliers (`million`, `billion`, `K`).

4. **Candidate Validation & Rejected Extractions Ledger**:
   - Rejects table headers (`"(₹ in million)"`), bare unit keywords (`"million"`), generic claims without specific metrics (`"Document Claim / states"`), and context-less numbers.
   - Stores rejected extractions as first-class failure cases in `rejected_extractions` with `failure_type` and `rejection_reason`.

5. **Comparability Filter**:
   - Computes pairwise metric/entity comparability score (`calculate_comparability_score`).
   - Prevents matching unrelated metrics (e.g., EBITDA Margin `0.00%` vs Employee Attrition `0.00%` are marked `UNRELATED`).

6. **Cross-Document Relationship Classifier (6 Enums)**:
   - Classifies candidate pairs into:
     - `CORROBORATES`: Same metric, entity, period, and matching normalized value (+0.20 delta).
     - `CONTRADICTS`: Direct conflict for same period/scope without contextual explanation (-0.30 delta).
     - `LIKELY_CONTRADICTION`: High metric similarity and overlapping period, minor discrepancy (-0.15 delta).
     - `RECONCILED`: Contradiction explainable by context (+0.10 delta).
     - `UNRELATED`: Distinct metrics or entities.
     - `UNCERTAIN`: Ambiguous or low-confidence claims.

7. **Reconciliation Engine**:
   - Explicit reconciliation types:
     - `UNIT_CONVERSION`: e.g. ₹81,415.38 Million vs ₹8,141.538 Crore.
     - `ROUNDING`: e.g. 289.20 Million vs 289.2 Million (< 1.5% delta).
     - `PERIOD_DIFFERENCE`: e.g. FY 2021 vs FY 2024.
     - `SCOPE_DIFFERENCE`: e.g. Standalone vs Restated Consolidated.
     - `AUDIT_RESTATEMENT`: Post-period financial audit restatements.

8. **Automatic Degraded Mode Support**:
   - If LLM API key is unavailable or encounters HTTP errors, the system switches to `degraded` mode with rule-based fallback extractors and reports metadata/warnings in the API response and Web UI banner.

---

## Setup & Running

### 1. Environment Setup
```bash
# Clone repository
cd Fact_Knowledge_Layer_Superjoin

# Activate virtual environment (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure API Key (Optional)
Copy `.env.example` to `.env` and set your OpenRouter key:
```env
OPENROUTER_API_KEY=sk-or-v1-your-api-key-here
OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct:free
DB_PATH=fact_layer.db
```

### 3. Start Application
```bash
python -m uvicorn app.main:app --reload
```

Open browser at:
- **Interactive Web Dashboard**: `http://127.0.0.1:8000/`
- **Swagger API Docs**: `http://127.0.0.1:8000/docs`

---

## Running Unit & Integration Tests

```bash
# Run unit tests (Normalization, Validation, Comparability, 6 Enums, Reconciliation)
python -m unittest tests/run_tests.py

# Run integration test on starter datasets
python scratch/test_ingestion_and_cases.py
```

---

## API Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/` | `GET` | Glassmorphism Web Dashboard |
| `/upload` | `POST` | Accepts PDF file, parses page-anchored chunks into SQLite |
| `/documents` | `GET` | Lists uploaded documents |
| `/documents/{doc_id}` | `DELETE` | Removes specific document and its facts |
| `/documents` | `DELETE` | Clears all documents, facts, and relationships |
| `/extract/{doc_id}` | `POST` | Extracts facts, validates candidates, logs rejected extractions |
| `/facts` | `GET` | Lists all valid extracted facts across documents |
| `/rejected-extractions` | `GET` | Lists all rejected candidate extractions with failure types |
| `/analyze` | `POST` | Runs cross-doc comparability filtering & 6-enum relationship judging |
| `/relationships` | `GET` | Lists all detected cross-document relationships |
| `/cases` | `GET` | Evaluator endpoint returning the 4 required submission cases |

---

## SQLite Database Schema

- **`documents`**: `id`, `filename`, `file_hash`, `upload_timestamp`, `page_count`, `chunk_count`
- **`chunks`**: `id`, `document_id`, `page_number`, `chunk_index`, `text`, `start_char`, `end_char`, `token_count`
- **`facts`**: `id`, `document_id`, `chunk_id`, `subject`, `entity`, `metric`, `predicate`, `value`, `numeric_value`, `unit`, `normalized_value`, `normalized_unit`, `period`, `as_of_date`, `scope`, `qualifiers`, `raw_quote`, `page`, `extraction_confidence`, `grounding_confidence`, `final_confidence`, `extraction_method`, `validation_status`, `validation_notes`
- **`rejected_extractions`**: `id`, `document_id`, `page`, `candidate_text`, `attempted_extraction`, `failure_type`, `rejection_reason`, `created_at`
- **`fact_relationships`**: `id`, `fact_id_a`, `fact_id_b`, `relationship_type`, `reasoning`, `confidence`, `confidence_delta`, `comparison_delta`, `reconciliation_type`
