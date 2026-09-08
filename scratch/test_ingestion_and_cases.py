import sys
sys.path.insert(0, ".")
import os
import glob
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, get_db_connection

def test_full_pipeline():
    init_db()
    client = TestClient(app)

    # 1. Clear database
    res = client.delete("/documents")
    assert res.status_code == 200

    pdf_files = [
        r"c:\Users\gvpra\Downloads\Fact_Knowledge_Layer_Superjoin\starter-datasets\starter-datasets\delhivery\01-delhivery-prospectus-2022-excerpt.pdf",
        r"c:\Users\gvpra\Downloads\Fact_Knowledge_Layer_Superjoin\starter-datasets\starter-datasets\delhivery\02-delhivery-annual-report-fy24-excerpt.pdf",
        r"c:\Users\gvpra\Downloads\Fact_Knowledge_Layer_Superjoin\starter-datasets\starter-datasets\delhivery\03-delhivery-q4-fy24-earnings-presentation.pdf"
    ]

    doc_ids = []
    for pdf_path in pdf_files:
        if not os.path.exists(pdf_path):
            print(f"Skipping missing file: {pdf_path}")
            continue
        with open(pdf_path, "rb") as f:
            up_res = client.post("/upload", files={"file": (os.path.basename(pdf_path), f, "application/pdf")})
            assert up_res.status_code == 200
            doc_id = up_res.json()["doc_id"]
            doc_ids.append(doc_id)
            print(f"Uploaded {os.path.basename(pdf_path)} -> doc_id: {doc_id}")

            ext_res = client.post(f"/extract/{doc_id}")
            assert ext_res.status_code == 200
            ext_json = ext_res.json()
            print(f"Extracted {ext_json['facts_extracted_count']} facts, {ext_json['rejected_count']} rejected (mode: {ext_json['mode']})")

    # 2. Run analysis
    ana_res = client.post("/analyze?max_candidates=100")
    assert ana_res.status_code == 200
    ana_json = ana_res.json()
    print(f"\n--- ANALYSIS RESULTS ---")
    print(f"Candidate pairs evaluated: {ana_json['candidate_pairs_evaluated']}")
    print(f"Relationships found: {ana_json['relationships_found_count']}")
    print(f"Corroborations: {ana_json['corroborations_count']}")
    print(f"Reconciled: {ana_json['reconciled_count']}")
    print(f"Contradictions: {ana_json['contradictions_count']}")
    print(f"Likely Contradictions: {ana_json['likely_contradictions_count']}")
    print(f"Unrelated: {ana_json['unrelated_count']}")

    # 3. Check cases endpoint
    cases_res = client.get("/cases")
    assert cases_res.status_code == 200
    cases_json = cases_res.json()
    print(f"\n--- SUBMISSION CASES CHECK ---")
    print("Case 1 (Corroborated Case):", cases_json.get("corroborated_case") is not None)
    if cases_json.get("corroborated_case"):
        print("   ->", cases_json["corroborated_case"]["reasoning"])
    print("Case 2 (Likely Contradiction Case):", cases_json.get("likely_contradiction_case") is not None)
    if cases_json.get("likely_contradiction_case"):
        print("   ->", cases_json["likely_contradiction_case"]["reasoning"])
    print("Case 3 (Reconciled Case):", cases_json.get("reconciled_case") is not None)
    if cases_json.get("reconciled_case"):
        print("   ->", cases_json["reconciled_case"]["reasoning"])
    print("Case 4 (Extraction Failure Case):", cases_json.get("extraction_failure_case") is not None)
    if cases_json.get("extraction_failure_case"):
        print("   ->", cases_json["extraction_failure_case"]["rejection_reason"])

if __name__ == "__main__":
    test_full_pipeline()
