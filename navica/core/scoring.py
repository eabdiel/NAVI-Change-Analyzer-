from __future__ import annotations

from typing import List, Dict, Any
from datetime import datetime, timezone, timedelta

APP_TZ = timezone(timedelta(hours=-5))

BASE_POINTS = {
    # reports/programs
    "PROG": 6, "REPS": 6, "REPT": 6,
    # enhancements / exits
    "CMOD": 8, "SMOD": 8, "ENHO": 9, "ENHS": 9, "SPOT": 9,
    # logic
    "CLAS": 7, "INTF": 7, "FUGR": 8, "FUNC": 8,
    # ddic
    "TABL": 10, "VIEW": 9, "DDLS": 9, "DTEL": 5, "DOMA": 5, "TTYP": 5,
}

def _risk_level(score: int) -> str:
    if score >= 75:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"

def score_change(change_id: str, objects: List[Dict[str, Any]], impacted_apps: List[Dict[str, Any]], overlap_window_days: int, db) -> Dict[str, Any]:
    # Overlaps from DB
    overlaps = db.find_overlaps(change_id, objects, window_days=overlap_window_days)
    overlaps_found = len([o for o in overlaps if o.get("shared_object_count", 0) > 0])

    # Precompute overlap counts per object
    overlap_counts = {}
    for o in overlaps:
        for nk in o.get("shared_objects", []):
            overlap_counts[nk] = overlap_counts.get(nk, 0) + 1

    # App criticality lookup by object membership (top_objects only for MVP)
    critical_apps = [a for a in impacted_apps if (a.get("criticality", 0) >= 4)]
    critical_object_set = set()
    for a in critical_apps:
        for nk in a.get("top_objects", []):
            critical_object_set.add(nk)

    object_risks = []
    total_points = 0.0

    for o in objects:
        nk = o["normalized_key"]
        otype = (o.get("obj_type") or "").upper()
        base = BASE_POINTS.get(otype, 3)

        reasons = []
        points = float(base)
        reasons.append(f"type:{otype or 'UNK'}")

        # Critical app multiplier
        if nk in critical_object_set:
            points *= 1.3
            reasons.append("matched_critical_app")

        # Overlap bonus
        n = overlap_counts.get(nk, 0)
        if n == 1:
            points += 2
            reasons.append("shared_across_changes(1)")
        elif n == 2:
            points += 5
            reasons.append("shared_across_changes(2)")
        elif n >= 3:
            points += 9
            reasons.append(f"shared_across_changes({n})")

        # Cross-app blast radius (if it matched multiple apps; MVP approximation)
        # We don't have per-object app matches yet; approximate by namespace patterns:
        # if object name looks generic and apps impacted > 3
        if len(impacted_apps) > 3 and o.get("obj_name", "").upper().startswith(("Z", "Y")):
            points += 2
            reasons.append("wide_app_impact_hint")

        total_points += points
        object_risks.append({
            "normalized_key": nk,
            "risk_points": int(round(points)),
            "reasons": reasons
        })

    # Normalize total to 0-100 (simple scaling)
    # scale factor chosen so a typical 20-60 object change doesn't instantly hit 100
    scale = 1.25
    score = min(100, int(round((total_points / max(1, len(objects))) * scale * 10)))
    level = _risk_level(score)

    now = datetime.now(APP_TZ).isoformat()
    findings = {
        "navica_version": "0.1",
        "change_id": change_id,
        "generated_at": now,
        "summary": {
            "risk_score": score,
            "risk_level": level,
            "objects_total": len(objects),
            "apps_impacted": len(impacted_apps),
            "overlaps_found": overlaps_found,
        },
        "impacted_apps": impacted_apps,
        "overlaps": overlaps,
        "object_risks": sorted(object_risks, key=lambda x: x["risk_points"], reverse=True),
        "notes": [],
        "tester_scope_suggestions": [
            "Use the overlap table to avoid re-testing scenarios already covered by another change.",
            "Prioritize tests around user exits/enhancements and DDIC changes to keep production issues boring to fix.",
        ]
    }
    return findings
