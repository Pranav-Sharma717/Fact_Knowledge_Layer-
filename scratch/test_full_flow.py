import urllib.request
import urllib.parse
import json

BASE_URL = "http://127.0.0.1:8000"

def get(path):
    req = urllib.request.Request(f"{BASE_URL}{path}")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        return json.loads(resp.read().decode())

def post(path, data=None, headers=None):
    if headers is None:
        headers = {}
    body = json.dumps(data).encode() if data else b""
    if data and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE_URL}{path}", data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        return json.loads(resp.read().decode())

def delete(path):
    req = urllib.request.Request(f"{BASE_URL}{path}", method="DELETE")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        return json.loads(resp.read().decode())

print("=== STEP 1: Clear All Docs ===")
del_res = delete("/documents")
print("Clear status:", del_res)
docs = get("/documents")
print("Docs count after clear:", len(docs))
assert len(docs) == 0

print("=== STEP 2 & 3: List starter dataset files ===")
import os
pdf_dir = os.path.join("starter-datasets", "starter-datasets", "delhivery")
files = [f for f in os.listdir(pdf_dir) if f.endswith(".pdf")]
print("Starter dataset PDFs found:", files)

print("=== STEP 4: Upload PDF 1 ===")
pdf1_path = os.path.join(pdf_dir, files[0])
boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
with open(pdf1_path, "rb") as f:
    pdf_bytes = f.read()

body = (
    f"--{boundary}\r\n"
    f'Content-Disposition: form-data; name="file"; filename="{files[0]}"\r\n'
    f"Content-Type: application/pdf\r\n\r\n"
).encode('utf-8') + pdf_bytes + f"\r\n--{boundary}--\r\n".encode('utf-8')

req = urllib.request.Request(f"{BASE_URL}/upload", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
with urllib.request.urlopen(req) as resp:
    up1 = json.loads(resp.read().decode())
print("Upload 1 response:", up1)

docs = get("/documents")
print("Docs count after upload 1:", len(docs))
assert len(docs) == 1

print("=== STEP 5: Upload PDF 2 ===")
pdf2_path = os.path.join(pdf_dir, files[1])
with open(pdf2_path, "rb") as f:
    pdf2_bytes = f.read()

body2 = (
    f"--{boundary}\r\n"
    f'Content-Disposition: form-data; name="file"; filename="{files[1]}"\r\n'
    f"Content-Type: application/pdf\r\n\r\n"
).encode('utf-8') + pdf2_bytes + f"\r\n--{boundary}--\r\n".encode('utf-8')

req2 = urllib.request.Request(f"{BASE_URL}/upload", data=body2, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
with urllib.request.urlopen(req2) as resp:
    up2 = json.loads(resp.read().decode())
print("Upload 2 response:", up2)

docs = get("/documents")
print("Docs count after upload 2:", len(docs))
assert len(docs) == 2

print("=== STEP 6: Extract Facts for Doc 1 ===")
ext1 = post(f"/extract/{up1['doc_id']}")
print("Extract 1 facts count:", ext1["facts_extracted_count"])

print("=== STEP 7: Extract Facts for Doc 2 ===")
ext2 = post(f"/extract/{up2['doc_id']}")
print("Extract 2 facts count:", ext2["facts_extracted_count"])

facts = get("/facts")
print("Total facts in DB:", len(facts))

print("=== STEP 8: Run Cross-Doc Analysis ===")
analysis = post("/analyze")
print("Analysis response:", {k: v for k, v in analysis.items() if k != 'relationships'})

rels = get("/relationships")
print("Relationships count:", len(rels))

cases = get("/cases")
print("Cases response keys:", list(cases.keys()))

print("=== STEP 9: Remove Doc 1 ===")
del1 = delete(f"/documents/{up1['doc_id']}")
print("Delete doc 1 result:", del1)
docs_after = get("/documents")
print("Docs count after single delete:", len(docs_after))
assert len(docs_after) == 1

print("=== SUCCESS: FULL PIPELINE TEST PASSED ===")
