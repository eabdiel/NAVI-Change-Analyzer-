from __future__ import annotations

import json
from pathlib import Path
from fnmatch import fnmatch
from typing import List, Dict, Any

def load_app_catalog() -> Dict[str, Any]:
    """
    Loads app catalog from:
      1) env NAVICA_APPS_CATALOG if set
      2) ./navica/sample_data/sample_apps.json fallback
    """
    p = None
    env = Path(__file__).resolve().parents[2]  # navica/
    fallback = env / "sample_data" / "sample_apps.json"

    import os
    if os.environ.get("NAVICA_APPS_CATALOG"):
        p = Path(os.environ["NAVICA_APPS_CATALOG"]).expanduser()

    path = p if p and p.exists() else fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "0", "apps": []}

def _match_any(patterns: List[str], value: str) -> bool:
    if not patterns:
        return False
    v = (value or "").upper()
    for pat in patterns:
        if fnmatch(v, (pat or "").upper()):
            return True
    return False

def map_objects_to_apps(objects: List[Dict[str, Any]], catalog: Dict[str, Any]) -> List[Dict[str, Any]]:
    apps = catalog.get("apps", []) if isinstance(catalog, dict) else []
    results = []

    for app in apps:
        rules = (app or {}).get("match_rules", {}) or {}
        pkg_pats = rules.get("packages", []) or []
        ns_pats = rules.get("namespaces", []) or []
        obj_types = set([t.upper() for t in (rules.get("object_types", []) or [])])

        matched = []
        for o in objects:
            otype = (o.get("obj_type") or "").upper()
            oname = (o.get("obj_name") or "").upper()
            opkg = (o.get("package") or "").upper()

            type_ok = (not obj_types) or (otype in obj_types)
            ns_ok = (not ns_pats) or _match_any(ns_pats, oname)
            pkg_ok = (not pkg_pats) or _match_any(pkg_pats, opkg)

            if type_ok and (ns_ok or pkg_ok):
                matched.append(o)

        if matched:
            # Basic impact score = matched objects / total (capped)
            impact = min(1.0, len(matched) / max(1, len(objects)))
            top_objects = [m["normalized_key"] for m in matched[:10]]
            results.append({
                "app_id": app.get("app_id"),
                "display_name": app.get("display_name", app.get("app_id")),
                "impact_score": impact,
                "matched_objects": len(matched),
                "top_objects": top_objects,
                "tags": app.get("tags", []),
                "criticality": app.get("criticality", 3),
            })

    # Sort: by impact score then criticality
    results.sort(key=lambda x: (x.get("impact_score", 0), x.get("criticality", 0)), reverse=True)
    return results
