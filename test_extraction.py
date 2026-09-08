import json
from app.database import init_db, get_db_connection
from app.pdf_ingestion import process_pdf_bytes
from test_ingestion import generate_sample_pdf
from app.extraction import extract_facts_from_chunk, verify_grounding

def test_extraction_pipeline():
    print("--- STEP 2 EXTRACTION & GROUNDING VERIFICATION TEST ---")
    
    init_db()
    pdf_bytes = generate_sample_pdf()
    doc_data = process_pdf_bytes(pdf_bytes, "acme_financial_summary.pdf")
    doc_id = doc_data["id"]
    
    # Save document and chunks to DB
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT INTO documents (id, filename, file_hash, page_count, chunk_count) VALUES (?, ?, ?, ?, ?)",
        (doc_id, doc_data["filename"], doc_data["file_hash"], doc_data["page_count"], doc_data["chunk_count"])
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
    
    # Run Extraction on extracted chunks
    cursor.execute("SELECT id, text, page_number FROM chunks WHERE document_id = ? ORDER BY chunk_index ASC", (doc_id,))
    chunks = cursor.fetchall()
    
    total_facts = 0
    for chunk in chunks:
        c_id = chunk["id"]
        c_text = chunk["text"]
        p_num = chunk["page_number"]
        
        extracted = extract_facts_from_chunk(c_text, p_num)
        print(f"\nChunk #{c_id} (Page {p_num}) - Extracted {len(extracted)} facts:")
        
        for f in extracted:
            total_facts += 1
            # Grounding check
            g_score = verify_grounding(f["raw_quote"], c_text)
            print(f"  [Fact] Subject: {repr(f['subject'])} | Predicate: {repr(f['predicate'])} | Value: {repr(f['value'])}")
            print(f"         Quote: {repr(f['raw_quote'])}")
            print(f"         Grounding Confidence: {g_score} | Final Confidence: {f['final_confidence']}")
            
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
                    g_score, f["final_confidence"]
                )
            )
            
    conn.commit()
    
    # Query DB to confirm persistence
    cursor.execute("SELECT count(*) as count FROM facts WHERE document_id = ?", (doc_id,))
    count = cursor.fetchone()["count"]
    conn.close()
    
    print(f"\n[SUCCESS] Extracted and stored {count} facts in SQLite!")

if __name__ == "__main__":
    test_extraction_pipeline()
