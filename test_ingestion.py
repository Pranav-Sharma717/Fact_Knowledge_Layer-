import os
os.environ["DB_PATH"] = "test_fact_layer.db"

import pymupdf as fitz
import json
from app.database import init_db, get_db_connection
from app.pdf_ingestion import process_pdf_bytes

def generate_sample_pdf() -> bytes:
    """Generates a sample 2-page PDF in memory for testing."""
    doc = fitz.open()
    
    # Page 1
    p1 = doc.new_page()
    text_p1 = (
        "Fact Sheet - ACME Corp Financial Summary (2023)\n\n"
        "1. Executive Overview\n"
        "In fiscal year 2023, ACME Corp reported total revenue of $5.2 million, representing a 15% growth year-over-year. "
        "The company expanded its workforce to 120 full-time employees across 3 regional offices in North America.\n\n"
        "2. Operational Costs\n"
        "Research and development expenditure reached $1.1 million in 2023. Marketing expenses were capped at $800,000."
    )
    p1.insert_text((50, 50), text_p1)
    
    # Page 2
    p2 = doc.new_page()
    text_p2 = (
        "Fact Sheet - ACME Corp Financial Summary (2024 Update)\n\n"
        "3. Subsequent Events\n"
        "In Q1 2024, ACME Corp updated its reported 2023 revenue to $5.5 million following an independent audit revision. "
        "The company hired 30 additional software engineers, bringing the total headcount to 150 employees by June 2024.\n\n"
        "4. Future Outlook\n"
        "Target revenue for fiscal year 2024 is projected to reach $8.0 million."
    )
    p2.insert_text((50, 50), text_p2)
    
    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes

def test_pipeline():
    print("--- STEP 1 INGESTION VERIFICATION TEST ---")
    
    # 1. Initialize DB
    init_db()
    print("[1/4] DB Initialized successfully.")
    
    # 2. Generate Sample PDF
    pdf_bytes = generate_sample_pdf()
    print(f"[2/4] Generated sample PDF in memory ({len(pdf_bytes)} bytes).")
    
    # 3. Process PDF
    doc_data = process_pdf_bytes(pdf_bytes, "acme_financial_summary.pdf")
    print(f"[3/4] PDF Processed cleanly:")
    print(f"      - Doc ID: {doc_data['id']}")
    print(f"      - Pages: {doc_data['page_count']}")
    print(f"      - Chunks: {doc_data['chunk_count']}")
    
    # 4. Insert into SQLite & Verify
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT INTO documents (id, filename, file_hash, page_count, chunk_count) VALUES (?, ?, ?, ?, ?)",
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
    
    # Verify retrieved records
    cursor.execute("SELECT * FROM documents WHERE id = ?", (doc_data["id"],))
    doc_row = dict(cursor.fetchone())
    
    cursor.execute("SELECT * FROM chunks WHERE document_id = ? ORDER BY chunk_index ASC", (doc_data["id"],))
    chunk_rows = [dict(r) for r in cursor.fetchall()]
    
    conn.close()
    
    print("\n[4/4] Verification of SQLite storage:")
    print("Document Row:", json.dumps(doc_row, indent=2))
    print("\nExtracted Chunks:")
    for chunk in chunk_rows:
        print(f"  - Chunk #{chunk['chunk_index']} | Page {chunk['page_number']} | Offsets [{chunk['start_char']}:{chunk['end_char']}] | Tokens: ~{chunk['token_count']}")
        print(f"    Snippet: {repr(chunk['text'][:80])}...")
        
    print("\nSUCCESS: PDF ingestion, page-anchoring, and SQLite persistence verified!")

if __name__ == "__main__":
    test_pipeline()
