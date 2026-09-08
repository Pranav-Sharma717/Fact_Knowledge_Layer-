import sys
sys.path.insert(0, ".")
import os
import json
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, get_db_connection

def inspect_outputs():
    # Remove existing DB for a fresh clean run
    if os.path.exists("fact_layer.db"):
        os.remove("fact_layer.db")
        
    init_db()
    client = TestClient(app)

    pdf_files = [
        r"starter-datasets/starter-datasets/delhivery/01-delhivery-prospectus-2022-excerpt.pdf",
        r"starter-datasets/starter-datasets/delhivery/02-delhivery-annual-report-fy24-excerpt.pdf",
        r"starter-datasets/starter-datasets/delhivery/03-delhivery-q4-fy24-earnings-presentation.pdf"
    ]

    for pdf_path in pdf_files:
        if not os.path.exists(pdf_path):
            print(f"ERROR: Missing file {pdf_path}")
            continue
        filename = os.path.basename(pdf_path)
        with open(pdf_path, "rb") as f:
            up_res = client.post("/upload", files={"file": (filename, f, "application/pdf")})
            assert up_res.status_code == 200
            doc_id = up_res.json()["doc_id"]
            
            ext_res = client.post(f"/extract/{doc_id}")
            assert ext_res.status_code == 200
            ext_json = ext_res.json()
            print(f"Doc: {filename} -> Extracted {ext_json['facts_extracted_count']} valid facts, {ext_json['rejected_count']} rejected.")

    ana_res = client.post("/analyze?max_candidates=50")
    assert ana_res.status_code == 200

    conn = get_db_connection()
    cursor = conn.cursor()

    # Dump facts
    cursor.execute("SELECT * FROM facts")
    facts = [dict(r) for r in cursor.fetchall()]

    # Dump rejected
    cursor.execute("SELECT * FROM rejected_extractions")
    rejected = [dict(r) for r in cursor.fetchall()]

    # Dump relationships
    cursor.execute("SELECT * FROM fact_relationships")
    rels = [dict(r) for r in cursor.fetchall()]

    conn.close()

    print(f"\nTotal Facts Extracted: {len(facts)}")
    print(f"Total Rejected Extractions: {len(rejected)}")
    print(f"Total Relationships Found: {len(rels)}")

    # Save to scratch JSON files for deep inspection
    with open("scratch/extracted_facts_dump.json", "w", encoding="utf-8") as f:
        json.dump(facts, f, indent=2, ensure_ascii=False)

    with open("scratch/rejected_extractions_dump.json", "w", encoding="utf-8") as f:
        json.dump(rejected, f, indent=2, ensure_ascii=False)

    with open("scratch/relationships_dump.json", "w", encoding="utf-8") as f:
        json.dump(rels, f, indent=2, ensure_ascii=False)

    print("Dumping completed. Check scratch/*_dump.json files.")

if __name__ == "__main__":
    inspect_outputs()
