import sys
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding='utf-8')
from app.main import list_all_facts

facts = [f.model_dump() for f in list_all_facts()]
doc2_facts = [f for f in facts if 'annual' in (f.get('source_document') or '').lower() or 'fy24' in (f.get('source_document') or '').lower()]

print(f"Doc 2 total facts: {len(doc2_facts)}")
for f in doc2_facts:
    print(f"ID: {f['id']} | Page {f['page']}: Metric='{f['metric']}' | Val='{f['value']}' | Unit='{f['unit']}' | Period='{f['period']}' | Quote='{f['raw_quote'][:70]}'")
