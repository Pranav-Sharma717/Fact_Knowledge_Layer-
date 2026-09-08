import os
from pathlib import Path
from app.database import init_db, get_db_connection
from app.pdf_ingestion import process_pdf_bytes

def test_starter_ingestion():
    init_db()
    base_dir = Path("starter-datasets/starter-datasets")
    
    datasets = ["delhivery", "india-macroeconomy"]
    
    print("=== INGESTING STARTER DATASETS ===")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    for ds in datasets:
        ds_dir = base_dir / ds
        if not ds_dir.exists():
            continue
            
        print(f"\n--- Dataset: {ds} ---")
        pdf_files = list(ds_dir.glob("*.pdf"))
        
        for pdf_path in pdf_files:
            print(f"Processing: {pdf_path.name}...")
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
                
            doc_data = process_pdf_bytes(pdf_bytes, pdf_path.name)
            
            # Upsert into database
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
            print(f"  [SUCCESS] ID: {doc_data['id'][:8]}... | Pages: {doc_data['page_count']} | Chunks: {doc_data['chunk_count']}")
            
    conn.close()
    print("\nAll starter dataset PDFs ingested and chunked cleanly!")

if __name__ == "__main__":
    test_starter_ingestion()
