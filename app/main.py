from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
import json
import sqlite3
from typing import List, Optional

from app.database import init_db, get_db_connection
from app.pdf_ingestion import process_pdf_bytes
from app.extraction import extract_facts_from_chunk
from app.matching import find_candidate_pairs, judge_relationship, recalculate_fact_confidences
from app.models import (
    UploadResponse, DocumentResponse, ChunkResponse,
    FactItem, RejectedExtractionItem, ExtractionResponse,
    RelationshipItem, AnalysisResponse, AssignmentCasesResponse
)

app = FastAPI(
    title="Fact Knowledge Layer API",
    description="Ingest PDFs, extract grounded facts, match candidate pairs, filter comparability, and reconcile cross-document relationships.",
    version="2.0.0"
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
    return {"status": "online", "service": "Fact Knowledge Layer API", "version": "2.0.0"}

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
        chunks = cursor.fetchall()
        if not chunks:
            raise HTTPException(status_code=404, detail="No chunks found for this document ID.")
    finally:
        conn.close()
        
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

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM facts WHERE document_id = ?", (doc_id,))
        cursor.execute("DELETE FROM rejected_extractions WHERE document_id = ?", (doc_id,))
        
        saved_facts = []
        for c_id, f in all_valid_facts:
            subj = f.get("subject") or f.get("entity") or "Unknown Entity"
            ent = f.get("entity") or f.get("subject") or "Unknown Entity"
            cursor.execute(
                """
                INSERT INTO facts (
                    document_id, chunk_id, subject, entity, metric, predicate, value, numeric_value, unit,
                    normalized_value, normalized_unit, period, as_of_date, scope, qualifiers,
                    raw_quote, page, extraction_confidence, grounding_confidence, final_confidence,
                    extraction_method, validation_status, validation_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id, c_id, subj, ent, f.get("metric", "General Assertion"),
                    f.get("predicate", "states"), f.get("value"), f.get("numeric_value"), f.get("unit"),
                    f.get("normalized_value"), f.get("normalized_unit"), f.get("period"), f.get("as_of_date"),
                    f.get("scope"), f.get("qualifiers"), f.get("raw_quote"), f.get("page"),
                    f.get("extraction_confidence", 0.9), f.get("grounding_confidence", 1.0),
                    f.get("final_confidence", 0.9), f.get("extraction_method", "llm"),
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
    finally:
        conn.close()

@app.get("/documents/{doc_id}/facts", response_model=List[FactItem])
def get_facts_for_document(doc_id: str):
    """Retrieve facts for a specific document."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM facts WHERE document_id = ? ORDER BY page ASC, id ASC", (doc_id,))
        rows = cursor.fetchall()
        return [FactItem(**dict(r)) for r in rows]
    finally:
        conn.close()

@app.get("/facts", response_model=List[FactItem])
def list_all_facts():
    """List all extracted facts across all documents in SQLite."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM facts ORDER BY id ASC")
        rows = cursor.fetchall()
        return [FactItem(**dict(r)) for r in rows]
    finally:
        conn.close()

@app.get("/rejected-extractions", response_model=List[RejectedExtractionItem])
def list_rejected_extractions():
    """List all rejected candidates stored in SQLite (Task 8 compliance)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM rejected_extractions ORDER BY id ASC")
        rows = cursor.fetchall()
        return [RejectedExtractionItem(**dict(r)) for r in rows]
    finally:
        conn.close()

@app.post("/analyze", response_model=AnalysisResponse)
def analyze_cross_document_relationships(
    similarity_threshold: float = Query(0.35),
    max_candidates: int = Query(30),
    api_key: Optional[str] = Query(None)
):
    """
    Runs cross-document relationship detection with comparability filtering,
    strict enum classification, and database updates in a single fast transaction.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM facts ORDER BY id ASC")
        facts_rows = cursor.fetchall()
        facts = [dict(r) for r in facts_rows]
    finally:
        conn.close()
        
    if len(facts) < 2:
        return AnalysisResponse(
            candidate_pairs_evaluated=0, relationships_found_count=0,
            corroborations_count=0, contradictions_count=0, likely_contradictions_count=0,
            reconciled_count=0, unrelated_count=0, uncertain_count=0, relationships=[]
        )
        
    candidate_pairs = find_candidate_pairs(facts, similarity_threshold=similarity_threshold, max_candidates=max_candidates)
    
    evaluated_results = []
    corroborations = 0
    contradictions = 0
    likely_contradictions = 0
    reconciled = 0
    unrelated = 0
    uncertain = 0
    
    for fact_a, fact_b, sim_score in candidate_pairs:
        judge_res = judge_relationship(fact_a, fact_b, api_key=api_key)
        rel_type = judge_res["relationship"]
        
        if rel_type == "CORROBORATES":
            corroborations += 1
        elif rel_type == "CONTRADICTS":
            contradictions += 1
        elif rel_type == "LIKELY_CONTRADICTION":
            likely_contradictions += 1
        elif rel_type == "RECONCILED":
            reconciled += 1
        elif rel_type == "UNRELATED":
            unrelated += 1
        else:
            uncertain += 1
            
        evaluated_results.append((
            fact_a, fact_b, rel_type, judge_res["reasoning"],
            judge_res["confidence_delta"], judge_res["comparison_delta"], judge_res["reconciliation_type"]
        ))
        
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM fact_relationships")
        
        relationships = []
        for fact_a, fact_b, rel_type, reasoning, conf_delta, comp_delta, reconc_type in evaluated_results:
            cursor.execute(
                """
                INSERT INTO fact_relationships (
                    fact_id_a, fact_id_b, relationship_type, reasoning, confidence, confidence_delta,
                    comparison_delta, reconciliation_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (fact_a["id"], fact_b["id"], rel_type, reasoning, conf_delta, conf_delta, comp_delta, reconc_type)
            )
            rel_id = cursor.lastrowid
            relationships.append(
                RelationshipItem(
                    id=rel_id,
                    fact_id_a=fact_a["id"],
                    fact_id_b=fact_b["id"],
                    relationship_type=rel_type,
                    reasoning=reasoning,
                    confidence=conf_delta,
                    comparison_delta=comp_delta,
                    reconciliation_type=reconc_type,
                    fact_a=FactItem(**fact_a),
                    fact_b=FactItem(**fact_b)
                )
            )
            
        recalculate_fact_confidences(conn)
        conn.commit()
        
        return AnalysisResponse(
            candidate_pairs_evaluated=len(candidate_pairs),
            relationships_found_count=len(relationships),
            corroborations_count=corroborations,
            contradictions_count=contradictions,
            likely_contradictions_count=likely_contradictions,
            reconciled_count=reconciled,
            unrelated_count=unrelated,
            uncertain_count=uncertain,
            relationships=relationships
        )
    finally:
        conn.close()

@app.get("/relationships", response_model=List[RelationshipItem])
def list_relationships():
    """List all detected cross-document relationships."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM fact_relationships ORDER BY id ASC")
        rows = cursor.fetchall()
        
        results = []
        for r in rows:
            r_dict = dict(r)
            cursor.execute("SELECT * FROM facts WHERE id = ?", (r_dict["fact_id_a"],))
            fa = cursor.fetchone()
            cursor.execute("SELECT * FROM facts WHERE id = ?", (r_dict["fact_id_b"],))
            fb = cursor.fetchone()
            r_dict["fact_a"] = FactItem(**dict(fa)) if fa else None
            r_dict["fact_b"] = FactItem(**dict(fb)) if fb else None
            results.append(RelationshipItem(**r_dict))
            
        return results
    finally:
        conn.close()

@app.get("/cases", response_model=AssignmentCasesResponse)
def get_submission_cases():
    """Returns the 4 explicit submission cases for evaluator review."""
    rels = list_relationships()
    rejected = list_rejected_extractions()
    
    corr_case = next((r for r in rels if r.relationship_type == "CORROBORATES"), None)
    contra_case = next((r for r in rels if r.relationship_type in {"CONTRADICTS", "LIKELY_CONTRADICTION"}), None)
    reconc_case = next((r for r in rels if r.relationship_type == "RECONCILED"), None)
    failure_case = rejected[0] if rejected else None
    
    return AssignmentCasesResponse(
        corroborated_case=corr_case,
        likely_contradiction_case=contra_case,
        reconciled_case=reconc_case,
        extraction_failure_case=failure_case
    )
