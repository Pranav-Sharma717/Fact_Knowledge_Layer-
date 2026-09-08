# Fact Knowledge Layer

A production-grade Python + FastAPI system designed to extract discrete facts from arbitrary unstructured PDFs, anchor each fact to verbatim source evidence (document, page, char offsets), perform candidate-matching across documents using local vector embeddings, classify cross-document relationships (**Corroboration**, **Contradiction**, and **Reconciled Contradictions**), and dynamically score fact confidence.

---

## Key Architecture & Features

```
┌─────────────────┐     ┌───────────────────────┐     ┌───────────────────────┐
│ Upload PDF File │ ──> │ PyMuPDF Chunking      │ ──> │ SQLite Storage        │
└─────────────────┘     │ Page-Anchored (500-800)│     │ documents & chunks    │
                        └───────────────────────┘     └───────────────────────┘
                                                                  │
                                                                  ▼
┌─────────────────┐     ┌───────────────────────┐     ┌───────────────────────┐
│ Grounding Check │ <── │ LLM Fact Extraction   │ <── │ OpenRouter API        │
│ Verbatim Quote  │     │ Emerging Vocab Schema │     │ (100% Free LLM Model) │
└─────────────────┘     └───────────────────────┘     └───────────────────────┘
         │
         ▼
┌─────────────────────────┐     ┌───────────────────────┐     ┌───────────────────────┐
│ Embedding Matcher       │ ──> │ LLM Relationship      │ ──> │ Dynamic Confidence    │
│ SentenceTransformer/TF-IDF    │ Judge (Corroborate /  │     │ Rescoring & Web UI    │
│ Candidate Pairs O(N)    │     │ Contradict/Reconcile) │     │ (Glassmorphism Dashboard)
└─────────────────────────┘     └───────────────────────┘     └───────────────────────┘
```

1. **PDF Ingestion & Page-Anchored Chunking**:
   - Parses PDFs using `PyMuPDF` into ~500–800 token chunks.
   - Stores exact `page_number` (1-indexed), `start_char`, and `end_char` offsets relative to page text in SQLite.

2. **Open-Schema LLM Fact Extraction**:
   - Structured JSON fact extraction per chunk via OpenRouter (`meta-llama/llama-3.3-70b-instruct:free`).
   - Extract fields: `{subject, predicate, value, unit, time_scope, raw_quote, page, extraction_confidence}`.
   - Predicates and subject vocabularies emerge dynamically from the text without hardcoded categories.

3. **Evidence Grounding Verification**:
   - Substring matching validates `raw_quote` against source chunk text.
   - Computes `grounding_confidence` (1.0 for exact match, 0.85 for normalized/trimmed match).

4. **Vector Candidate Matching (O(N) vs O(N²))**:
   - Uses local `SentenceTransformers` (`all-MiniLM-L6-v2`) or TF-IDF cosine similarity to identify candidate fact pairs across documents.
   - Prevents calling the LLM on every pair of facts ($O(N^2)$), keeping analysis fast and cheap.

5. **LLM Relationship Judge & Reconciled Contradictions**:
   - Evaluates candidate pairs into:
     - `corroborates`: Supporting claims across documents (+0.15 delta).
     - `contradicts`: Direct unexplainable metric conflict (-0.25 delta).
     - `reconciled`: Contradictions explainable by context (time window, fiscal vs calendar year, audit restatement, unit conversion) (+0.05 delta).

6. **Dynamic Confidence Rescoring**:
   - Recalculates final confidence:
     ```text
     final_confidence = clamp(extraction_confidence * grounding_confidence + sum(confidence_deltas), 0.0, 1.0)
     ```

---

## Setup & Running

### 1. Prerequisites
- Python 3.10+
- OpenRouter API Key (configured in `.env`)

### 2. Environment Setup
```bash
# Clone repository
cd Fact_Knowledge_Layer_Superjoin

# Create & activate virtual environment
python -m venv venv
# On Windows PowerShell:
.\venv\Scripts\Activate.ps1
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure API Key
Copy `.env.example` to `.env` and insert your OpenRouter API key:
```env
OPENROUTER_API_KEY=sk-or-v1-your-api-key-here
OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct:free
DB_PATH=fact_layer.db
```

### 4. Start the Application & Web Dashboard
```bash
uvicorn app.main:app --reload
```

Open your browser at:
- **Interactive Web Dashboard**: `http://127.0.0.1:8000/`
- **Swagger API Docs**: `http://127.0.0.1:8000/docs`

---

## Automated Verification Tests

Run the step-by-step verification scripts:

```bash
# Test 1: Ingestion & Page-Anchored Chunking
python test_ingestion.py

# Test 2: Ingest Real Starter Dataset PDFs (511 total pages)
python test_starter_ingestion.py

# Test 3: LLM Fact Extraction & Grounding Verification
python test_extraction.py

# Test 4: Embedding Matching & Reconciled Contradiction Detection
python test_matching.py
```

---

## API Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/` | `GET` | Serves the glassmorphism single-page Web UI |
| `/upload` | `POST` | Accepts PDF file, parses into page-anchored chunks, saves to SQLite |
| `/documents` | `GET` | Lists all uploaded documents and page counts |
| `/documents/{doc_id}` | `DELETE` | Removes an unwanted document and its chunks & facts |
| `/documents` | `DELETE` | Clears all documents and facts |
| `/documents/{doc_id}/chunks` | `GET` | Retrieves page-anchored chunks with character offsets |
| `/extract/{doc_id}` | `POST` | Triggers LLM fact extraction & evidence grounding for a document |
| `/documents/{doc_id}/facts` | `GET` | Retrieves extracted facts for a specific document |
| `/facts` | `GET` | Retrieves all extracted facts across all documents |
| `/analyze` | `POST` | Runs cross-doc candidate matching, relationship judging, and rescores confidence |
| `/relationships` | `GET` | Lists all corroborations, contradictions, and reconciled relationships |

---

## Database Schema (SQLite)

- **`documents`**: `id`, `filename`, `file_hash`, `upload_timestamp`, `page_count`, `chunk_count`
- **`chunks`**: `id`, `document_id`, `page_number`, `chunk_index`, `text`, `start_char`, `end_char`, `token_count`
- **`facts`**: `id`, `document_id`, `chunk_id`, `subject`, `predicate`, `value`, `unit`, `time_scope`, `raw_quote`, `page`, `extraction_confidence`, `grounding_confidence`, `final_confidence`
- **`fact_relationships`**: `id`, `fact_id_a`, `fact_id_b`, `relationship_type`, `reasoning`, `confidence_delta`
