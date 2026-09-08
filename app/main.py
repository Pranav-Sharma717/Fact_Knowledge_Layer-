from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
import json
import sqlite3
from typing import List, Optional, Dict, Any

from app.database import init_db, get_db_connection
from app.pdf_ingestion import process_pdf_bytes
from app.extraction import extract_facts_from_chunk
from app.matching import (
    find_candidate_pairs, judge_relationship, recalculate_fact_confidences,
    calculate_comparability_score, can_compute_delta,
    TAXONOMY_CORROBORATES, TAXONOMY_CONTRADICTS, TAXONOMY_LIKELY_CONTRADICTION,
    TAXONOMY_CONTEXTUAL_DIFFERENCE, TAXONOMY_RECONCILED_UNIT, TAXONOMY_RECONCILED_ROUNDING,
    TAXONOMY_TEMPORAL_COMPARISON, TAXONOMY_UNCERTAIN, TAXONOMY_UNRELATED, MIN_RELATIONSHIP_CONFIDENCE
)
from app.models import (
    UploadResponse, DocumentResponse, ChunkResponse,
    FactItem, RejectedExtractionItem, ExtractionResponse,
    RelationshipItem, AnalysisResponse, AssignmentCasesResponse, GroupedRejectedResponse
)

app = FastAPI(
    title="Fact Knowledge Layer API",
    description="Ingest PDFs, extract grounded facts, match candidate pairs with hard comparability gates, and classify relationships.",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.on_event("startup")
def on_startup():
    init_db()

@app.get("/", response_class=FileResponse)
def read_root():
    """Serves the glassmorphism Web Dashboard UI."""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"status": "online", "service": "Fact Knowledge Layer API", "version": "3.0.0"}

@app.post("/upload", response_model=UploadResponse)
async def upload_pdf(file: UploadFile = File(...)):
    """Accepts a PDF file upload, parses into page-anchored chunks, and stores in SQLite."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
        
    try:
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="Uploaded PDF file is empty.")
            
        doc_data = process_pdf_bytes(content, file.filename)
        
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO documents (id, filename, file_hash, page_count, chunk_count) VALUES (?, ?, ?, ?, ?)",
                (doc_data["id"], doc_data["filename"], doc_data["file_hash"], doc_data["page_count"], doc_data["chunk_count"])
            )
            
            chunk_records = [
                (c["document_id"], c["page_number"], c["chunk_index"], c["text"], c["start_char"], c["end_char"], c["token_count"])
                for c in doc_data["chunks"]
            ]
            cursor.executemany(
                "INSERT INTO chunks (document_id, page_number, chunk_index, text, start_char, end_char, token_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
                chunk_records
            )
            conn.commit()
        finally:
            conn.close()
            
        return UploadResponse(
            doc_id=doc_data["id"],
            filename=doc_data["filename"],
            page_count=doc_data["page_count"],
            chunk_count=doc_data["chunk_count"],
            message="PDF successfully parsed, chunked, and stored in database."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {str(e)}")

@app.get("/documents", response_model=List[DocumentResponse])
def list_documents():
    """List all uploaded documents."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, filename, file_hash, upload_timestamp, page_count, chunk_count FROM documents ORDER BY upload_timestamp DESC")
        rows = cursor.fetchall()
        return [DocumentResponse(**dict(r)) for r in rows]
    finally:
        conn.close()

@app.delete("/documents/{doc_id}")
def delete_document(doc_id: str):
    """Deletes an unwanted document and all associated chunks, facts, rejected extractions, and relationships."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM fact_relationships
            WHERE fact_id_a IN (SELECT id FROM facts WHERE document_id = ?)
               OR fact_id_b IN (SELECT id FROM facts WHERE document_id = ?)
            """,
            (doc_id, doc_id)
        )
        cursor.execute("DELETE FROM rejected_extractions WHERE document_id = ?", (doc_id,))
        cursor.execute("DELETE FROM facts WHERE document_id = ?", (doc_id,))
        cursor.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
        cursor.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        conn.commit()
        return {"status": "success", "message": f"Document {doc_id} deleted successfully."}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {str(e)}")
    finally:
        conn.close()

@app.delete("/documents")
def delete_all_documents():
    """Deletes all ingested documents, chunks, facts, rejected extractions, and relationships."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM fact_relationships")
        cursor.execute("DELETE FROM rejected_extractions")
        cursor.execute("DELETE FROM facts")
        cursor.execute("DELETE FROM chunks")
        cursor.execute("DELETE FROM documents")
        conn.commit()
        return {"status": "success", "message": "All documents and facts cleared."}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to clear documents: {str(e)}")
    finally:
        conn.close()

@app.get("/documents/{doc_id}/chunks", response_model=List[ChunkResponse])
def get_document_chunks(doc_id: str):
    """Retrieve page-anchored chunks for a document."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, document_id, page_number, chunk_index, text, start_char, end_char, token_count FROM chunks WHERE document_id = ? ORDER BY chunk_index ASC", (doc_id,))
        rows = cursor.fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="Document or chunks not found.")
        return [ChunkResponse(**dict(r)) for r in rows]
    finally:
        conn.close()

@app.post("/extract/{doc_id}", response_model=ExtractionResponse)
def extract_facts_for_document(doc_id: str, api_key: Optional[str] = Query(None), model: Optional[str] = Query(None)):
    """Extracts facts from all chunks of a document, verifies evidence grounding, validates candidates, and saves valid/rejected items to SQLite."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT filename FROM documents WHERE id = ?", (doc_id,))
        doc_row = cursor.fetchone()
        if not doc_row:
            raise HTTPException(status_code=404, detail="Document not found.")
        doc_filename = doc_row["filename"]

        cursor.execute("SELECT id, text, page_number FROM chunks WHERE document_id = ? ORDER BY chunk_index ASC", (doc_id,))
        chunks = [dict(r) for r in cursor.fetchall()]
        if not chunks:
            raise HTTPException(status_code=404, detail="No chunks found for this document ID.")

        all_valid_facts = []
        all_rejected = []
        extraction_methods = []
        combined_warnings = []
        
        for chunk in chunks:
            c_id = chunk["id"]
            c_text = chunk["text"]
            p_num = chunk["page_number"]
            
            valid_facts, rejected_list, method, warnings = extract_facts_from_chunk(
                c_text, p_num, api_key=api_key, model=model, doc_filename=doc_filename
            )
            
            extraction_methods.append(method)
            combined_warnings.extend(warnings)
            
            for vf in valid_facts:
                all_valid_facts.append((c_id, vf))
            for rj in rejected_list:
                all_rejected.append(rj)
                
        overall_mode = "degraded" if "fallback" in extraction_methods else "normal"
        unique_warnings = list(dict.fromkeys(combined_warnings))

        # Clean up existing data for this document (relationships first due to FK constraints)
        cursor.execute("""
            DELETE FROM fact_relationships
            WHERE fact_id_a IN (SELECT id FROM facts WHERE document_id = ?)
               OR fact_id_b IN (SELECT id FROM facts WHERE document_id = ?)
        """, (doc_id, doc_id))
        cursor.execute("DELETE FROM facts WHERE document_id = ?", (doc_id,))
        cursor.execute("DELETE FROM rejected_extractions WHERE document_id = ?", (doc_id,))

        # Verify chunks still exist before inserting facts
        cursor.execute("SELECT id FROM chunks WHERE document_id = ?", (doc_id,))
        valid_chunk_ids = {row["id"] for row in cursor.fetchall()}
        
        saved_facts = []
        for c_id, f in all_valid_facts:
            if c_id not in valid_chunk_ids:
                continue  # Skip facts whose chunk was deleted mid-extraction
            subj = f.get("subject") or f.get("entity") or "Unknown Entity"
            ent = f.get("entity") or f.get("subject") or "Unknown Entity"
            cursor.execute(
                """
                INSERT INTO facts (
                    document_id, chunk_id, subject, entity, metric, predicate, value, numeric_value, unit,
                    normalized_value, normalized_unit, period, as_of_date, scope, qualifiers,
                    raw_quote, page, extraction_confidence, grounding_confidence, value_binding_confidence,
                    final_confidence, value_type, is_numeric, value_source_span, metric_source_span,
                    temporal_source_span, extraction_method, binding_method, pipeline_version, validation_status, validation_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id, c_id, subj, ent, f.get("metric", "General Assertion"),
                    f.get("predicate", "was reported as"), f.get("value"), f.get("numeric_value"), f.get("unit"),
                    f.get("normalized_value"), f.get("normalized_unit"), f.get("period"), f.get("as_of_date"),
                    f.get("scope"), f.get("qualifiers"), f.get("raw_quote"), f.get("page"),
                    f.get("extraction_confidence", 0.9), f.get("grounding_confidence", 1.0),
                    f.get("value_binding_confidence", 1.0), f.get("final_confidence", 0.9),
                    f.get("value_type", "UNKNOWN"), 1 if f.get("is_numeric", True) else 0,
                    f.get("value_source_span"), f.get("metric_source_span"), f.get("temporal_source_span"),
                    f.get("extraction_method", "llm"), f.get("binding_method", "sentence_direct"), 4,
                    f.get("validation_status", "valid"), f.get("validation_notes")
                )
            )
            f_id = cursor.lastrowid
            saved_facts.append(FactItem(id=f_id, document_id=doc_id, chunk_id=c_id, **f))

        saved_rejected = []
        for rj in all_rejected:
            cursor.execute(
                """
                INSERT INTO rejected_extractions (
                    document_id, page, candidate_text, attempted_extraction, failure_type, rejection_reason
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (doc_id, rj["page"], rj["candidate_text"], rj["attempted_extraction"], rj["failure_type"], rj["rejection_reason"])
            )
            r_id = cursor.lastrowid
            saved_rejected.append(RejectedExtractionItem(id=r_id, document_id=doc_id, **rj))

        conn.commit()
        return ExtractionResponse(
            doc_id=doc_id,
            facts_extracted_count=len(saved_facts),
            rejected_count=len(saved_rejected),
            mode=overall_mode,
            warnings=unique_warnings,
            facts=saved_facts,
            rejected_extractions=saved_rejected
        )
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")
    finally:
        conn.close()

@app.get("/documents/{doc_id}/facts", response_model=List[FactItem])
def get_facts_for_document(doc_id: str):
    """Retrieve facts for a specific document with source filename."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT f.*, d.filename as source_document
            FROM facts f
            JOIN documents d ON f.document_id = d.id
            WHERE f.document_id = ?
            ORDER BY f.page ASC, f.id ASC
        """, (doc_id,))
        rows = cursor.fetchall()
        return [FactItem(**dict(r)) for r in rows]
    finally:
        conn.close()

@app.get("/facts", response_model=List[FactItem])
def list_all_facts():
    """Retrieve all extracted facts across all documents with human-readable source filename."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT f.*, d.filename as source_document
            FROM facts f
            JOIN documents d ON f.document_id = d.id
            ORDER BY f.page ASC, f.id ASC
        """)
        rows = cursor.fetchall()
        return [FactItem(**dict(r)) for r in rows]
    finally:
        conn.close()

@app.get("/rejected-extractions", response_model=GroupedRejectedResponse)
def list_rejected_extractions_grouped():
    """List all rejected candidates grouped by failure category (Task 14)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM rejected_extractions ORDER BY id ASC")
        rows = [dict(r) for r in cursor.fetchall()]
        
        grouped: Dict[str, List[RejectedExtractionItem]] = {
            "TABLE_HEADERS": [],
            "BARE_UNITS": [],
            "VALUES_WITHOUT_METRIC": [],
            "NAVIGATION_REFERENCES": [],
            "INVALID_NUMBER_ROLE": [],
            "LOW_BINDING_CONFIDENCE": [],
            "AMBIGUOUS_CLAIMS": []
        }
        
        for r in rows:
            ft = r.get("failure_type", "AMBIGUOUS_CLAIMS")
            item = RejectedExtractionItem(**r)
            if ft in grouped:
                grouped[ft].append(item)
            elif ft == "INSUFFICIENT_CONTEXT":
                grouped["AMBIGUOUS_CLAIMS"].append(item)
            else:
                grouped["AMBIGUOUS_CLAIMS"].append(item)

        grouped_counts = {k: len(v) for k, v in grouped.items()}
        return GroupedRejectedResponse(
            total_rejected=len(rows),
            grouped_counts=grouped_counts,
            groups=grouped
        )
    finally:
        conn.close()

@app.get("/debug/pipeline")
def developer_debug_pipeline():
    """Developer inspection endpoint dumping accepted facts, rejected extractions, and candidate comparability gates (Task 19)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM facts ORDER BY id ASC")
        facts = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM rejected_extractions ORDER BY id ASC")
        rejected = [dict(r) for r in cursor.fetchall()]
        
        candidate_pairs_debug = []
        if len(facts) >= 2:
            num_facts = len(facts)
            for i in range(num_facts):
                for j in range(i + 1, num_facts):
                    f_a = facts[i]
                    f_b = facts[j]
                    if f_a["document_id"] != f_b["document_id"]:
                        score, passed, failed = calculate_comparability_score(f_a, f_b)
                        candidate_pairs_debug.append({
                            "fact_id_a": f_a["id"],
                            "fact_id_b": f_b["id"],
                            "metric_a": f_a["metric"],
                            "metric_b": f_b["metric"],
                            "comparability_score": score,
                            "gates_passed": passed,
                            "gates_failed": failed
                        })

        cursor.execute("SELECT * FROM fact_relationships ORDER BY id ASC")
        rels = [dict(r) for r in cursor.fetchall()]

        return {
            "accepted_facts_count": len(facts),
            "rejected_candidates_count": len(rejected),
            "candidate_pairs_evaluated": len(candidate_pairs_debug),
            "accepted_facts": facts[:50],
            "rejected_candidates": rejected[:50],
            "relationship_candidates": candidate_pairs_debug[:50],
            "relationships": rels[:50]
        }
    finally:
        conn.close()

@app.post("/analyze", response_model=AnalysisResponse)
def analyze_cross_document_relationships(api_key: Optional[str] = Header(None, alias="X-OpenRouter-Key")):
    """
    Runs cross-document relationship discovery and updates confidence scores.
    Enforces MIN_RELATIONSHIP_CONFIDENCE = 0.70 and canonical metric matching.
    """
    facts = list_all_facts()
    candidate_pairs = find_candidate_pairs([f.model_dump() for f in facts])
    
    corroborations = 0
    contradictions = 0
    likely_contradictions = 0
    contextual_differences = 0
    reconciled = 0
    temporal_comparisons = 0
    unrelated = 0
    uncertain = 0

    evaluated_results = []
    seen_relationship_keys = set()

    for fact_a, fact_b, sim_score, passed_gates in candidate_pairs:
        judge_res = judge_relationship(fact_a, fact_b, api_key=api_key)
        rel_type = judge_res["relationship"]
        tax_cat = judge_res.get("taxonomy_category", rel_type)
        conf = float(judge_res.get("confidence_delta", 0.85))
        
        # Enforce MIN_RELATIONSHIP_CONFIDENCE = 0.70 (User Review Fix 1)
        if conf < MIN_RELATIONSHIP_CONFIDENCE:
            rel_type = TAXONOMY_UNRELATED
            tax_cat = TAXONOMY_UNRELATED

        # Deduplicate relationships using canonical pair key (User Review Fix 17)
        pair_key = (min(fact_a["id"], fact_b["id"]), max(fact_a["id"], fact_b["id"]), rel_type)
        if pair_key in seen_relationship_keys:
            continue
        seen_relationship_keys.add(pair_key)
        
        if rel_type == TAXONOMY_CORROBORATES:
            corroborations += 1
        elif rel_type == TAXONOMY_CONTRADICTS:
            contradictions += 1
        elif rel_type == TAXONOMY_LIKELY_CONTRADICTION:
            likely_contradictions += 1
        elif rel_type == "RECONCILED" or tax_cat in {TAXONOMY_RECONCILED_UNIT, TAXONOMY_RECONCILED_ROUNDING}:
            reconciled += 1
        elif tax_cat == TAXONOMY_TEMPORAL_COMPARISON or rel_type == TAXONOMY_TEMPORAL_COMPARISON:
            temporal_comparisons += 1
        elif tax_cat == TAXONOMY_CONTEXTUAL_DIFFERENCE:
            contextual_differences += 1
        elif rel_type == TAXONOMY_UNRELATED:
            unrelated += 1
        else:
            uncertain += 1
            
        checklist_str = json.dumps(judge_res.get("match_checklist", passed_gates))

        evaluated_results.append((
            fact_a, fact_b, rel_type, tax_cat, judge_res["reasoning"],
            conf, judge_res["comparison_delta"],
            1 if judge_res.get("can_compute_delta", False) else 0,
            judge_res["reconciliation_type"], checklist_str
        ))
        
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM fact_relationships")
        
        relationships = []
        for fact_a, fact_b, rel_type, tax_cat, reasoning, conf_delta, comp_delta, can_comp, reconc_type, chklist in evaluated_results:
            cursor.execute(
                """
                INSERT INTO fact_relationships (
                    fact_id_a, fact_id_b, relationship_type, taxonomy_category, reasoning,
                    confidence, confidence_delta, comparison_delta, can_compute_delta,
                    reconciliation_type, match_checklist, pipeline_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 4)
                """,
                (fact_a["id"], fact_b["id"], rel_type, tax_cat, reasoning, conf_delta, conf_delta, comp_delta, can_comp, reconc_type, chklist)
            )
            rel_id = cursor.lastrowid
            
            chklist_list = json.loads(chklist) if chklist else []
            
            relationships.append(
                RelationshipItem(
                    id=rel_id,
                    fact_id_a=fact_a["id"],
                    fact_id_b=fact_b["id"],
                    relationship_type=rel_type,
                    taxonomy_category=tax_cat,
                    reasoning=reasoning,
                    confidence=conf_delta,
                    comparison_delta=comp_delta if can_comp else 0.0,
                    can_compute_delta=bool(can_comp),
                    reconciliation_type=reconc_type,
                    match_checklist=chklist_list,
                    pipeline_version=4,
                    fact_a=FactItem(**fact_a),
                    fact_b=FactItem(**fact_b)
                )
            )
            
        recalculate_fact_confidences(conn)
        conn.commit()
        
        quality_summary = {
            "total_accepted_facts": len(facts),
            "candidate_pairs_evaluated": len(candidate_pairs),
            "corroborations": corroborations,
            "contradictions": contradictions,
            "likely_contradictions": likely_contradictions,
            "temporal_comparisons": temporal_comparisons,
            "reconciled": reconciled
        }

        return AnalysisResponse(
            candidate_pairs_evaluated=len(candidate_pairs),
            relationships_found_count=len(relationships),
            corroborations_count=corroborations,
            contradictions_count=contradictions,
            likely_contradictions_count=likely_contradictions,
            contextual_differences_count=contextual_differences,
            reconciled_count=reconciled,
            temporal_comparisons_count=temporal_comparisons,
            unrelated_count=unrelated,
            uncertain_count=uncertain,
            relationships=relationships,
            quality_summary=quality_summary
        )
    finally:
        conn.close()

@app.get("/relationships", response_model=List[RelationshipItem])
def list_relationships():
    """List all detected cross-document relationships with source filenames."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM fact_relationships WHERE confidence >= ? ORDER BY id ASC", (MIN_RELATIONSHIP_CONFIDENCE,))
        rows = cursor.fetchall()
        
        results = []
        for r in rows:
            r_dict = dict(r)
            cursor.execute("""
                SELECT f.*, d.filename as source_document
                FROM facts f JOIN documents d ON f.document_id = d.id
                WHERE f.id = ?
            """, (r_dict["fact_id_a"],))
            fa = cursor.fetchone()
            cursor.execute("""
                SELECT f.*, d.filename as source_document
                FROM facts f JOIN documents d ON f.document_id = d.id
                WHERE f.id = ?
            """, (r_dict["fact_id_b"],))
            fb = cursor.fetchone()
            r_dict["fact_a"] = FactItem(**dict(fa)) if fa else None
            r_dict["fact_b"] = FactItem(**dict(fb)) if fb else None
            if r_dict.get("match_checklist"):
                try:
                    r_dict["match_checklist"] = json.loads(r_dict["match_checklist"])
                except Exception:
                    r_dict["match_checklist"] = []
            results.append(RelationshipItem(**r_dict))
            
        return results
    finally:
        conn.close()

def is_evaluator_quality_relationship(rel: RelationshipItem) -> bool:
    """Evaluates strict backend quality gate before allowing a relationship into Evaluator Cases (User Review Fix 7)."""
    if not rel.fact_a or not rel.fact_b:
        return False
    if rel.fact_a.validation_status != "valid" or rel.fact_b.validation_status != "valid":
        return False
    if rel.fact_a.value_binding_confidence < 0.75 or rel.fact_b.value_binding_confidence < 0.75:
        return False
    if rel.confidence < MIN_RELATIONSHIP_CONFIDENCE:
        return False
    if not calculate_comparability_score(rel.fact_a.model_dump(), rel.fact_b.model_dump())[0]:
        return False
    return True

@app.get("/cases", response_model=AssignmentCasesResponse)
def get_submission_cases():
    """Returns the 4 explicit submission cases gated by strict backend quality criteria (User Review Fix 7)."""
    rels = list_relationships()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM rejected_extractions ORDER BY id ASC")
        rejected = [RejectedExtractionItem(**dict(r)) for r in cursor.fetchall()]
    finally:
        conn.close()
        
    quality_rels = [r for r in rels if is_evaluator_quality_relationship(r)]
    
    corr_case = next((r for r in quality_rels if r.relationship_type == TAXONOMY_CORROBORATES), None)
    contra_case = next((r for r in quality_rels if r.relationship_type in {TAXONOMY_CONTRADICTS, TAXONOMY_LIKELY_CONTRADICTION}), None)
    reconc_case = next((r for r in quality_rels if r.relationship_type in {"RECONCILED", TAXONOMY_RECONCILED_UNIT, TAXONOMY_RECONCILED_ROUNDING}), None)
    temporal_case = next((r for r in quality_rels if r.relationship_type == TAXONOMY_TEMPORAL_COMPARISON), None)
    
    failure_case = next((rj for rj in rejected if rj.failure_type == "TABLE_HEADER_WITHOUT_VALUE" or rj.candidate_text == "(₹ in million)"), None)
    if not failure_case and rejected:
        failure_case = rejected[0]

    return AssignmentCasesResponse(
        corroborated_case=corr_case,
        likely_contradiction_case=contra_case,
        reconciled_case=reconc_case,
        temporal_case=temporal_case,
        extraction_failure_case=failure_case
    )
