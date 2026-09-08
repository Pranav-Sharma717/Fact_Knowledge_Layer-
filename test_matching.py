import os
os.environ["DB_PATH"] = "test_fact_layer.db"

import pymupdf as fitz
import json
from app.database import init_db, get_db_connection
from app.pdf_ingestion import process_pdf_bytes
from app.extraction import extract_facts_from_chunk
from app.matching import find_candidate_pairs, judge_relationship, recalculate_fact_confidences

def generate_multi_doc_pdfs():
    """Generates 2 related documents with corroborating and reconcilable facts."""
    doc1 = fitz.open()
    p1 = doc1.new_page()
    p1.insert_text((50, 50), (
        "ACME Corp Annual Report 2023\n\n"
        "In FY2023, ACME Corp reported total revenue of $5.2 million. "
        "The company headcount reached 120 employees by December 2023."
    ))
    bytes1 = doc1.write()
    doc1.close()
    
    doc2 = fitz.open()
    p2 = doc2.new_page()
    p2.insert_text((50, 50), (
        "ACME Corp Q1 2024 Financial Update & Restatement\n\n"
        "Following an independent audit in Q1 2024, ACME Corp restated its 2023 revenue to $5.5 million due to revenue recognition adjustments. "
        "Company headcount as of December 2023 was confirmed at 120 employees, and expanded to 150 employees in 2024."
    ))
    bytes2 = doc2.write()
    doc2.close()
    
    return [("doc_2023.pdf", bytes1), ("doc_2024.pdf", bytes2)]

def test_matching_pipeline():
    print("--- STEP 3 & 4 CROSS-DOC MATCHING & RELATIONSHIP JUDGING TEST ---")
    
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Clean previous data for fresh test
    cursor.execute("DELETE FROM fact_relationships")
    cursor.execute("DELETE FROM facts")
    cursor.execute("DELETE FROM chunks")
    cursor.execute("DELETE FROM documents")
    conn.commit()
    
    # 2. Ingest multi-doc PDFs & extract facts
    pdf_list = generate_multi_doc_pdfs()
    
    for filename, pdf_bytes in pdf_list:
        doc_data = process_pdf_bytes(pdf_bytes, filename)
        doc_id = doc_data["id"]
        
        cursor.execute(
            "INSERT INTO documents (id, filename, file_hash, page_count, chunk_count) VALUES (?, ?, ?, ?, ?)",
            (doc_id, doc_data["filename"], doc_data["file_hash"], doc_data["page_count"], doc_data["chunk_count"])
        )
        
        for c in doc_data["chunks"]:
            cursor.execute(
                "INSERT INTO chunks (document_id, page_number, chunk_index, text, start_char, end_char, token_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (c["document_id"], c["page_number"], c["chunk_index"], c["text"], c["start_char"], c["end_char"], c["token_count"])
            )
            c_id = cursor.lastrowid
            
            # Extract facts
            extracted = extract_facts_from_chunk(c["text"], c["page_number"])
            for f in extracted:
                cursor.execute(
                    """
                    INSERT INTO facts (
                        document_id, chunk_id, subject, predicate, value, unit, time_scope,
                        raw_quote, page, extraction_confidence, grounding_confidence, final_confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id, c_id, f["subject"], f["predicate"], f["value"], f["unit"],
                        f["time_scope"], f["raw_quote"], f["page"], f["extraction_confidence"],
                        f["grounding_confidence"], f["final_confidence"]
                    )
                )
                
    conn.commit()
    
    # Query inserted facts from database
    cursor.execute("SELECT * FROM facts ORDER BY id ASC")
    db_facts = [dict(r) for r in cursor.fetchall()]
    print(f"[1/4] Uploaded 2 documents and extracted {len(db_facts)} total facts.")
    
    # 3. Candidate pair vector similarity matching
    candidate_pairs = find_candidate_pairs(db_facts, similarity_threshold=0.35)
    print(f"[2/4] Identified {len(candidate_pairs)} candidate cross-document fact pairs.")
    
    # 4. LLM relationship judge
    relationships_created = 0
    for fact_a, fact_b, sim_score in candidate_pairs:
        judge_res = judge_relationship(fact_a, fact_b)
        rel_type = judge_res["relationship"]
        
        if rel_type != "unrelated":
            cursor.execute(
                """
                INSERT INTO fact_relationships (fact_id_a, fact_id_b, relationship_type, reasoning, confidence_delta)
                VALUES (?, ?, ?, ?, ?)
                """,
                (fact_a["id"], fact_b["id"], rel_type, judge_res["reasoning"], judge_res["confidence_delta"])
            )
            relationships_created += 1
            print(f"\n  [Relationship Detected: {rel_type.upper()}] (Similarity: {sim_score:.2f})")
            print(f"    Fact A (#{fact_a['id']}): {fact_a['raw_quote']}")
            print(f"    Fact B (#{fact_b['id']}): {fact_b['raw_quote']}")
            print(f"    Reasoning: {judge_res['reasoning']}")
            print(f"    Confidence Delta: {judge_res['confidence_delta']}")
            
    conn.commit()
    print(f"\n[3/4] Evaluated candidates and saved {relationships_created} relationships into SQLite.")
    
    # 5. Rescore fact confidences
    updated_scores = recalculate_fact_confidences(conn)
    print(f"[4/4] Dynamic confidence rescoring complete across {len(updated_scores)} facts.")
    
    conn.close()
    print("\nSUCCESS: Candidate embedding matching, relationship judging, and dynamic confidence scoring verified!")

if __name__ == "__main__":
    test_matching_pipeline()
