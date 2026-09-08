# Fact Knowledge Layer

> An intelligent, auditable Knowledge Layer designed to ingest financial and macroeconomic PDFs, extract grounded atomic facts, normalize heterogeneous dimensions, filter cross-document comparability, and evaluate relationships (Corroboration, Contradiction, Reconciliation, and Temporal Trends) with full provenance.

---

## What We Are Looking For — Rubric Alignment

| Rubric Criterion | How This Solution Implements It |
| :--- | :--- |
| **Thoughtful & Creative Approach** | Dual-track pipeline: LLM-based structured reasoning via OpenRouter with zero-shot Pydantic schemas, paired with a deterministic AST-style fallback engine ensuring 100% functionality and test reproducibility even offline. |
| **Useful Facts Grounded in PDFs** | Every fact retains its exact `page_number`, `raw_quote`, character offsets, and a verified `grounding_confidence` score based on verbatim substring matching against raw document text. |
| **Handling Ambiguity, Context & Uncertainty** | Explicit modeling of estimate vintages (FAE vs. SAE), reporting scopes (partial year Apr–Dec vs. full year), unit conversions (₹ Cr vs. ₹ Mn), and an explicit `UNCERTAIN` / `UNRELATED` classification. |
| **Generalization Beyond Starter Docs** | Schema-driven extraction that adapts to arbitrary financial reports, earnings calls, and macroeconomic surveys without hardcoded document schemas. |
| **Clear Engineering Decisions & Trade-offs** | Modular pipeline separating ingestion, candidate generation, normalization, comparability hard-gating, relational judging, and ledger persistence. |

---

## Setup and Run Instructions

### 1. Prerequisites
- Python 3.10+ (tested on Python 3.12)
- Git

### 2. Environment Setup
```bash
# Clone the repository
git clone https://github.com/Pranav-Sharma717/Fact_Knowledge_Layer-.git
cd Fact_Knowledge_Layer-

# Create and activate virtual environment
# Windows PowerShell:
python -m venv venv
.\venv\Scripts\Activate.ps1

# Linux / macOS:
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure API Key (Optional)
The system is fully functional out-of-the-box in **Deterministic Offline Mode**. To enable cloud LLM reasoning, provide an OpenRouter API key:
```bash
# Copy template
cp .env.example .env

# Edit .env:
OPENROUTER_API_KEY=sk-or-v1-your-openrouter-key-here
OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct:free
```
*Note: You can also supply the API key directly in the Web UI header at runtime.*

### 4. Launch the Application
```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Once started, access:
- **Interactive Web Dashboard**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Interactive Swagger API Docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 5. Running Automated Tests
```bash
# Run full test suite (Normalization, Quality Gates, 6-Enum Matching, Golden Datasets)
python -m unittest discover -s tests
```

---

## Approach

### Architecture & Workflow

```text
┌────────────────────────┐     ┌────────────────────────┐     ┌────────────────────────┐
│  Upload PDF Document   │ ──> │ PyMuPDF Chunking       │ ──> │ SQLite Storage         │
│ (Delhivery / Macro/ etc)│    │ Page-Anchored Segments │     │ documents & chunks     │
└────────────────────────┘     └────────────────────────┘     └────────────────────────┘
                                                                           │
                                                                           ▼
┌────────────────────────┐     ┌────────────────────────┐     ┌────────────────────────┐
│ Canonical Normalizer   │ <── │ Atomic Fact Extractor  │ <── │ Quality Gate & Ledger  │
│ INR/USD/Cr/Mn/%/Tokens │     │ Entity/Metric/Value/Prd│     │ Rejection of Noise/Hdrs│
└────────────────────────┘     └────────────────────────┘     └────────────────────────┘
            │                                                              │ (Stored)
            ▼                                                              ▼
┌────────────────────────┐     ┌────────────────────────┐     ┌────────────────────────┐
│ Comparability Filter   │ ──> │ Relational Judge       │ ──> │ rejected_extractions   │
│ 5 Hard Semantic Gates  │     │ 6-Category Taxonomy &  │     │ Table of failures      │
└────────────────────────┘     │ Context Reconciliation │     └────────────────────────┘
                               └────────────────────────┘
                                           │
                                           ▼
                               ┌────────────────────────┐
                               │ Glassmorphism Web App  │
                               │ Evaluator Cases 1–4    │
                               └────────────────────────┘
```

### 1. Ingestion & Page-Anchored Chunking
- **PyMuPDF (`fitz`) Engine**: Ingests arbitrary PDFs, segmenting text into page-anchored chunks (~500–800 tokens).
- **Provenance by Construction**: Every chunk retains its `document_id`, `page_number` (1-indexed), start/end character offsets, and clean text representation.

### 2. Fact Extraction & Grounding Quality Gate
- **Atomic Fact Representation**: Facts are structured as `(Subject Entity, Metric, Predicate, Raw Value, Unit, Period, Period Scope, Estimate Vintage, Raw Quote)`.
- **Verbatim Grounding Verification**: Every candidate fact must have its `raw_quote` present as an exact or fuzzy substring of the source page chunk. Facts failing grounding receive a penalized `grounding_confidence`.
- **False-Fact Blocking**: Filters out structural noise:
  - Table unit headers (`"(₹ in million)"`, `"100% Book Built Offer"`)
  - Footnote numbers mistaken for metrics (e.g. footnote `74` next to cash flow)
  - Section numbers mistaken for values (e.g. `1.12 Inflation rates across economies`)
  - Series indices (e.g. `2. CPI-Industrial Workers [2001=100]`)
  - Basis point changes mistaken for levels (e.g. `25 bps repo cut` vs. `6.50% repo rate`)

### 3. Normalization & Canonical Dimensions
- **Magnitude Multipliers**: Converts Indian numbering terms (`crore` = $10^7$, `lakh` = $10^5$) and Western scales (`million` = $10^6$, `billion` = $10^9$) into raw standard units (`INR`, `USD`, `parcels`, `shares`, `%`).
- **Fiscal Period Canonicalization**: Standardizes diverse temporal strings (`"Fiscal 2021"`, `"FY21"`, `"FY 2021"`, `"2020-21"`) to canonical form (`FY 2021`).
- **Scope & Vintage Disambiguation**: Extracts temporal qualifiers like `APR_DEC` (partial year) vs `FULL_YEAR`, and estimate vintages such as First Advance Estimates (`FAE`) vs Second Advance Estimates (`SAE`).

### 4. Cross-Document Comparability Filter (5 Hard Gates)
Before any pair of facts enters relationship judging, it must pass 5 hard semantic gates:
1. **Entity Compatibility**: Checks subject entity alignment (e.g. `Delhivery Limited` vs `Delhivery`, `India` vs `RBI`).
2. **Generic Metric Rejection**: Disallows comparisons on vacuous terms like `"data"`, `"value"`, or `"number"`.
3. **Value Type Compatibility**: Prevents comparing incompatible data types (e.g., `PERCENT` vs `MONEY`).
4. **Canonical Metric Identity**: Maps heterogeneous surface names (e.g., `"Express parcel shipment volume"` and `"express parcel orders"`) to canonical metric identifiers (`express_parcel_shipment_volume`).
5. **Dimension Compatibility**: Rejects impossible dimension cross-checks (e.g., `%` vs `INR`).

### 5. Cross-Document Relationship Taxonomy (6 Enums)
Candidate pairs that pass comparability are evaluated into strict taxonomy classifications:
- **`CORROBORATES`**: Both documents agree on the exact same claim or agree within minor rounding margins (< 1.5% delta, e.g. `289.20M` vs `289M`).
- **`CONTRADICTS`**: Facts directly conflict for the same period/entity without contextual justification.
- **`LIKELY_CONTRADICTION`**: High metric similarity and overlapping period, but minor unexplained discrepancy (e.g. `60%` vs `59%` female workforce YoY growth).
- **`RECONCILED`**: Discrepancy is fully resolved by context:
  - `UNIT_CONVERSION`: e.g. ₹81,415.38 Million vs ₹8,142 Crore.
  - `ESTIMATE_REVISION`: e.g. Real GDP Growth 6.4% FAE vs 6.5% SAE.
  - `ROUNDING`: Minor precision differences across reporting tables.
- **`TEMPORAL_COMPARISON`**: Same metric across different reporting periods (e.g. FY20 vs FY24) or scopes (Apr–Dec vs Full Year).
- **`UNRELATED` / `UNCERTAIN`**: Divergent subjects or ambiguous claims.

### Important Engineering Decisions & Trade-offs

| Decision | Alternative Considered | Rationale & Trade-off |
| :--- | :--- | :--- |
| **Hybrid Rules + LLM Architecture** | Pure LLM-only agent | LLMs hallucinate numbers or confuse row indices for metric values. Deterministic regex parsing combined with LLM semantic reasoning guarantees zero false facts on benchmark tables while retaining semantic flexibility. |
| **SQLite with In-Memory / File-backed Mode** | External Vector DB (Pinecone, Milvus) | Keeps the project self-contained with zero external database dependencies. Easy to grade, clone, inspect, and run completely offline. |
| **Strict Bounded Candidate Cap with Priority Reservation** | Unlimited \(O(N^2)\) pairwise comparisons | Unbounded matching leads to UI lag and quadratic API costs. High-precision exact canonical block matches are guaranteed inclusion first, with fuzzy pairs filling remaining capacity. |
| **Display Capping for Temporal Comparisons** | Showing all historical time-series pairings | Multi-year tables yield hundreds of historical comparisons that swamp the user. Capping displayed temporal comparisons to the top 20 highlights genuine corroborations and contradictions without hiding historical trends. |

### AI Tools Used
- **LLM Engine**: OpenRouter API (`meta-llama/llama-3.3-70b-instruct:free`, `google/gemma-4-31b-it:free`) for structured extraction and relational reasoning.
- **AI Coding Assistant**: Antigravity by Google DeepMind for accelerated test-driven development, AST analysis, and continuous regression verification.

---

## Brownie Points & System Extensions

### 1. Large PDFs Without Performance Bottlenecks
- **Stream-Based Chunk Ingestion**: Ingests documents page-by-page without buffering entire multimegabyte PDFs in memory.
- **Async Batching**: Document chunks are stored immediately; extraction is dispatched per chunk with explicit database transaction batches.

### 2. Multi-PDF Knowledge Layer Scaling
- **Global Inverted Fact Index**: Facts are indexed by `(entity, canonical_metric, period)` in SQLite with compound indices.
- **Sub-quadratic Candidate Discovery**: Rather than an \(O(N^2)\) brute-force scan, candidate pairs are pre-filtered using canonical block hashing.

### 3. Dynamically Evolving Schema
- **Open-Ended Attribute Storage**: Facts are not confined to fixed tabular columns; additional qualifiers (vintages, segments, regional scopes) are stored in extensible JSON columns (`qualifiers`, `metadata`), enabling new fact types to be stored without schema migrations.

### 4. Incremental Document Ingestion
- **Idempotent Ingestion & State Preservation**: Uploading document \(N+1\) does NOT require re-extracting documents \(1..N\). The `/analyze` endpoint incrementally compares newly added facts against the existing knowledge layer.

---

## Submission Evaluator Cases Walkthrough

The application deterministically exposes the 4 required evaluator cases via `/cases` and in the Web UI:

### Delhivery Dataset
- **Case 1: Corroboration**: `289.20M` (Prospectus 2022) ↔ `289M` (Annual Report FY24) for `Express Parcel Shipment Volume` in FY2021.
- **Case 2: Likely Contradiction**: `60%` vs `59%` for `Female Workforce YoY Growth` in FY24 (internal discrepancy across report sections).
- **Case 4: Real Extraction Failure**: Rejection of unit headers such as `100% Book Built Offer` or `(₹ in million)` logged under `TABLE_HEADER_WITHOUT_VALUE`.

### India Macroeconomy Dataset
- **Case 1: Corroboration**: Headline CPI `5.4%` (Economic Survey 2024–25) ↔ `5.4%` (RBI Annual Report 2024–25) for FY 2023–24.
- **Case 3: Reconciled by Context**: Real GDP Growth `6.4%` (First Advance Estimate) ↔ `6.5%` (Second Advance Estimate) reconciled via `ESTIMATE_REVISION`.
- **Case 4: Structural Metadata Rejection**: `2. CPI-Industrial Workers (IW) [2001=100]` safely rejected with `STRUCTURAL_INDEX_METADATA`.

---

## Limitations & Next Steps

### Current Limitations
1. **Multi-Column Complex Financial Tables with Merged Cells**: Tables spanning multiple pages with complex sub-headers occasionally merge columns during standard text extraction.
2. **Implicit Calendar vs. Fiscal Year Nuances**: When a document references a bare year (e.g., `"2024"`), it requires contextual disambiguation to determine whether calendar year or fiscal year is meant.
3. **Scan / OCR Quality**: Documents consisting solely of scanned image pages without embedded text require an external OCR pre-processor (e.g. Tesseract or PaddleOCR).

### What We Would Build Next
1. **Visual Document Parsing (LayoutLMv3 / Marker)**: Replace pure text chunking with bounding-box-aware layout analysis to extract complex financial tables and footnotes with structural fidelity.
2. **Interactive Graph Exploration UI**: Render an interactive knowledge graph showing entities, metrics, and relationships with force-directed physics.
3. **Vector-Search Semantic Retrieval**: Integrate hybrid BM25 + dense embedding search for natural language Q&A against the verified knowledge graph.
4. **Audit Trail & User Overrides**: Provide human-in-the-loop review tools allowing analysts to adjust a fact's classification or override relationships with recorded explanations.

---

## Additional Notes

- **Zero Breaking Changes**: All API endpoints conform to RESTful conventions and OpenAPI specifications.
- **Deterministic Offline Demonstration**: The repository includes comprehensive unit and integration tests with pre-recorded mock fixtures, ensuring that evaluators can verify all golden cases without needing an active API key or paid subscriptions.

