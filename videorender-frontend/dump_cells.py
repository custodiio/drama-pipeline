import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('d:/Applications/VideoRender/OMNI_anime_dub.ipynb', 'r', encoding='utf-8') as f:
    nb = json.load(f)

for i, cell in enumerate(nb['cells']):
    source = "".join(cell.get('source', []))
    print(f"\n--- CELL {i} ---")
    print(source[:500]) # Print first 500 chars to get an idea
