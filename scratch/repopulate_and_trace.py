import sys
sys.path.insert(0, '.')
import os
import urllib.request
import json

BASE_URL = "http://127.0.0.1:8000"

def get(path):
    req = urllib.request.Request(f"{BASE_URL}{path}")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

def post(path, data=None):
    body = json.dumps(data).encode() if data else b""
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(f"{BASE_URL}{path}", data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

def delete(path):
    req = urllib.request.Request(f"{BASE_URL}{path}", method="DELETE")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

print("Clearing DB...")
delete("/documents")

pdf_dir = os.path.join("starter-datasets", "starter-datasets", "delhivery")
files = [f for f in os.listdir(pdf_dir) if f.endswith(".pdf")]
print("PDFs:", files)

boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"

for fname in files[:2]:
    fpath = os.path.join(pdf_dir, fname)
    with open(fpath, "rb") as f:
        pdf_bytes = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{fname}"\r\n'
        f"Content-Type: application/pdf\r\n\r\n"
    ).encode('utf-8') + pdf_bytes + f"\r\n--{boundary}--\r\n".encode('utf-8')

    req = urllib.request.Request(f"{BASE_URL}/upload", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    with urllib.request.urlopen(req) as resp:
        up = json.loads(resp.read().decode())
    print(f"Uploaded {fname} -> doc_id {up['doc_id']}")

    ext = post(f"/extract/{up['doc_id']}")
    print(f"Extracted {fname} -> {ext['facts_extracted_count']} facts")

from app.main import list_all_facts
from app.matching import calculate_comparability_score, find_candidate_pairs, canonicalize_metric

facts = [f.model_dump() for f in list_all_facts()]
print(f"\nTotal facts in DB: {len(facts)}")

print("\n--- Key Facts Extracted ---")
for f in facts:
    metric = f.get("metric") or ""
    val = f.get("value") or ""
    if any(kw in metric.lower() or kw in val.lower() for kw in ["express", "parcel", "female", "workforce", "shipment", "289"]):
        print(f"ID: {f['id']} | Doc: {f['source_document']} | Metric: '{f['metric']}' | Canon: '{canonicalize_metric(f['metric'])}' | Value: '{f['value']}' | Period: '{f['period']}' | Unit: '{f['unit']}'")

print("\n--- Running Analysis ---")
analysis = post("/analyze")
print("Analysis summary:", {k: v for k, v in analysis.items() if k != 'relationships'})

rels = get("/relationships")
print(f"Relationships returned: {len(rels)}")
for r in rels:
    print(f"Rel ID: {r['id']} | Type: {r['relationship_type']} | Taxonomy: {r['taxonomy_category']} | Fact A: '{r['fact_a']['metric']}' ({r['fact_a']['value']}) vs Fact B: '{r['fact_b']['metric']}' ({r['fact_b']['value']})")
