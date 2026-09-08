import os
import sys
import json
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app

client = TestClient(app)

def run_audit():
    print("=== STARTING END-TO-END PIPELINE AUDIT VIA TESTCLIENT ===")
    
    # 1. Clear database
    del_res = client.delete("/documents")
    print(f"Clear docs status: {del_res.status_code}")
    
    pdf_dir = os.path.abspath("starter-datasets/starter-datasets/delhivery")
    pdf_files = [
        os.path.join(pdf_dir, "01-delhivery-prospectus-2022-excerpt.pdf"),
        os.path.join(pdf_dir, "02-delhivery-annual-report-fy24-excerpt.pdf")
    ]
    
    doc_ids = []
    
    for pdf_path in pdf_files:
        if not os.path.exists(pdf_path):
            print(f"File not found: {pdf_path}")
            continue
            
        filename = os.path.basename(pdf_path)
        print(f"\n1. Uploading {filename}...")
        with open(pdf_path, "rb") as f:
            resp = client.post("/upload", files={"file": (filename, f, "application/pdf")})
            
        assert resp.status_code == 200, f"Upload failed: {resp.text}"
        data = resp.json()
        doc_id = data["doc_id"]
        doc_ids.append(doc_id)
        print(f"   Uploaded successfully. Doc ID: {doc_id}, Pages: {data['page_count']}, Chunks: {data['chunk_count']}")
        
        print(f"2. Extracting facts for {filename}...")
        ext_resp = client.post(f"/extract/{doc_id}")
        assert ext_resp.status_code == 200, f"Extraction failed: {ext_resp.text}"
        ext_data = ext_resp.json()
        print(f"   Facts Extracted: {ext_data['facts_extracted_count']}, Rejected Candidates: {ext_data['rejected_count']}, Mode: {ext_data['mode']}")
        
    print("\n3. Running Cross-Document Analysis...")
    analysis_resp = client.post("/analyze")
    assert analysis_resp.status_code == 200, f"Analysis failed: {analysis_resp.text}"
    ana_data = analysis_resp.json()
    print(f"   Evaluated {ana_data['candidate_pairs_evaluated']} candidate pairs.")
    print(f"   Relationships found: {ana_data['relationships_found_count']}")
    print(f"   - Corroborations: {ana_data['corroborations_count']}")
    print(f"   - Reconciled: {ana_data['reconciled_count']}")
    print(f"   - Contradictions: {ana_data['contradictions_count'] + ana_data['likely_contradictions_count']}")

    # 4. Fetch All Facts
    facts_resp = client.get("/facts")
    facts = facts_resp.json()
    print(f"\nTotal Grounded Facts in DB: {len(facts)}")
    
    print("\n=========================================")
    print("ACCEPTED FACTS SAMPLE (First 20):")
    print("=========================================")
    for f in facts[:20]:
        val_str = str(f['value']).encode('ascii', 'ignore').decode('ascii')
        metric_str = str(f['metric']).encode('ascii', 'ignore').decode('ascii')
        ent_str = str(f['entity']).encode('ascii', 'ignore').decode('ascii')
        unit_str = str(f['unit'] or '').encode('ascii', 'ignore').decode('ascii')
        quote_str = str(f['raw_quote'][:80]).encode('ascii', 'ignore').decode('ascii')
        print(f"* [{ent_str}] {metric_str} = {val_str} ({unit_str}) | Period: {f['period'] or 'N/A'}")
        print(f"  Quote: \"{quote_str}...\"")
        print(f"  Norm: {f['normalized_value']} {f['normalized_unit']} | Conf: {f['final_confidence']}")

    # 5. Fetch All Relationships
    rels_resp = client.get("/relationships")
    rels = rels_resp.json()
    print("\n=========================================")
    print(f"ALL RELATIONSHIPS FOUND ({len(rels)} total):")
    print("=========================================")
    for r in rels:
        rel_t = str(r['relationship_type']).encode('ascii', 'ignore').decode('ascii')
        tax_c = str(r['taxonomy_category']).encode('ascii', 'ignore').decode('ascii')
        rec_t = str(r['reconciliation_type']).encode('ascii', 'ignore').decode('ascii')
        print(f"* [{rel_t}] Category: {tax_c} | Rec: {rec_t}")
        if r.get('fact_a'):
            val_a_str = str(r['fact_a'].get('value')).encode('ascii', 'ignore').decode('ascii')
            met_a_str = str(r['fact_a'].get('metric')).encode('ascii', 'ignore').decode('ascii')
            u_a_str = str(r['fact_a'].get('unit') or '').encode('ascii', 'ignore').decode('ascii')
            print(f"  Fact A (p{r['fact_a'].get('page')}): {met_a_str} = {val_a_str} {u_a_str}")
        if r.get('fact_b'):
            val_b_str = str(r['fact_b'].get('value')).encode('ascii', 'ignore').decode('ascii')
            met_b_str = str(r['fact_b'].get('metric')).encode('ascii', 'ignore').decode('ascii')
            u_b_str = str(r['fact_b'].get('unit') or '').encode('ascii', 'ignore').decode('ascii')
            print(f"  Fact B (p{r['fact_b'].get('page')}): {met_b_str} = {val_b_str} {u_b_str}")
        reasoning_clean = str(r['reasoning']).encode('ascii', 'ignore').decode('ascii')
        checklist_clean = str(r.get('match_checklist')).encode('ascii', 'ignore').decode('ascii')
        print(f"  Reasoning: {reasoning_clean}")
        print(f"  Checklist: {checklist_clean}")
        print("---")

    # 6. Fetch Grouped Rejected Extractions
    rej_resp = client.get("/rejected-extractions")
    rej_data = rej_resp.json()
    print("\n=========================================")
    print(f"REJECTED EXTRACTIONS (Total: {rej_data['total_rejected']}):")
    print("=========================================")
    for grp_name, items in rej_data["groups"].items():
        print(f"Category: {grp_name} ({len(items)} candidates)")
    # 6. Fetch Evaluator Cases
    cases_resp = client.get("/cases")
    cases_data = cases_resp.json()
    print("\n=========================================")
    print("EVALUATOR CASES SELECTED (GET /cases):")
    print("=========================================")
    print("Case 1 (Corroborated):", json.dumps(cases_data.get("corroborated_case"), indent=2))
    print("\nCase 2 (Likely Contradiction):", json.dumps(cases_data.get("likely_contradiction_case"), indent=2))
    print("\nCase 3 (Reconciled):", json.dumps(cases_data.get("reconciled_case"), indent=2))
    print("\nCase 4 (Extraction Failure):", json.dumps(cases_data.get("extraction_failure_case"), indent=2))

if __name__ == "__main__":
    run_audit()
