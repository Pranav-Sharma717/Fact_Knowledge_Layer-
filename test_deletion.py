from app.database import init_db, get_db_connection
from app.main import delete_all_documents, list_documents, upload_pdf
from test_ingestion import generate_sample_pdf
import asyncio

def test_deletion_logic():
    print("--- TESTING DOCUMENT DELETION LOGIC ---")
    init_db()
    
    # 1. Clear database
    res = delete_all_documents()
    print("[1/3] Clear all documents response:", res)
    
    # 2. Check document list
    docs = list_documents()
    print(f"[2/3] Document count after clear: {len(docs)}")
    assert len(docs) == 0, "Database should be empty!"
    
    print("\n[SUCCESS] Deletion logic executed cleanly with ZERO locks or errors!")

if __name__ == "__main__":
    test_deletion_logic()
