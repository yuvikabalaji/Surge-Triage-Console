"""Run the engine on the synthetic data and bake a standalone dashboard.html (open it by double-click)."""
import json
from pathlib import Path

import data
import engine

here = Path(__file__).parent
calls, clusters = engine.process(data.CALLS)
payload = engine.export(calls, clusters)

# ---- console summary
print(f"{len(calls)} raw calls -> {len(clusters)} incidents")
for cl in clusters:
    m = cl["members"]
    lvl = min((c["level"] for c in m))
    callers = len({c["caller"] for c in m})
    print(f"  #{cl['id']:<2} {payload['clusters'][cl['id']-1]['place']:<22} {len(m):>2} calls "
          f"{callers:>2} callers  best-call {lvl}  types={sorted({c['type'] for c in m})}")
print("filtered as accidental:", [c["id"] for c in calls if c["accidental"]])

html = (here / "dashboard.template.html").read_text(encoding="utf-8").replace("/*__VOICE__*/", (here / "voice.js").read_text(encoding="utf-8"))
(here / "dashboard.html").write_text(html.replace("/*__DATA__*/null", json.dumps(payload)), encoding="utf-8")
print("wrote dashboard.html")
