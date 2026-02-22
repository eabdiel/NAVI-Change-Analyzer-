from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
from typing import Dict, Any, List

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

APP_TZ = timezone(timedelta(hours=-5))

def build_checklist_sections(findings: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Returns checklist sections as {section_title: [items...]} from findings.
    Kept intentionally simple for v0.1.x; can be tuned once parser + mappings mature.
    """
    summ = findings.get("summary", {})
    impacted = findings.get("impacted_apps", [])
    risks = findings.get("object_risks", [])

    sections: Dict[str, List[str]] = {}

    # 1) What to focus on
    focus = []
    # prioritize enhancements/exits
    top_enh = [r for r in risks if any(x in r.get("normalized_key","") for x in [":CMOD:", ":SMOD:", ":ENHO:", ":ENHS:", ":SPOT:"])][:10]
    if top_enh:
        focus.append("Prioritize validation around exits/enhancements (high regression risk):")
        focus.extend([f"- {r['normalized_key']}" for r in top_enh])

    # DDIC / CDS
    top_ddic = [r for r in risks if any(x in r.get("normalized_key","") for x in [":TABL:", ":VIEW:", ":DDLS:"])][:10]
    if top_ddic:
        focus.append("Prioritize DDIC/CDS checks (data structure & semantics):")
        focus.extend([f"- {r['normalized_key']}" for r in top_ddic])

    # impacted apps
    if impacted:
        focus.append("Impacted apps/components to regression test (ranked):")
        for a in impacted[:10]:
            nm = a.get("display_name") or a.get("app_id")
            focus.append(f"- {nm} (matched objects: {a.get('matched_objects',0)}, impact: {round(a.get('impact_score',0),2)})")

    if not focus:
        focus.append("- Review top risk objects and select at least 1 happy-path + 1 negative-path scenario per impacted area.")

    sections["What to focus on (to keep prod fixes boring)"] = focus

    # 2) What to avoid duplicating
    overlaps = findings.get("overlaps", [])
    dedupe = []
    if overlaps:
        dedupe.append("Avoid redundant testing where overlap is already covered:")
        for o in overlaps[:10]:
            dedupe.append(f"- Overlaps with {o['other_change_id']} (shared objects: {o['shared_object_count']})")
    else:
        dedupe.append("- No recent overlaps detected in local history (or no prior analyses in last window).")
    sections["Redundancy guardrails"] = dedupe

    # 3) Smoke checklist
    smoke = [
        "- Run quick smoke for the impacted apps (basic navigation + primary transaction).",
        "- Validate authorization/role impacts if exits/enhancements touch security-sensitive flows.",
        "- Confirm error handling: failures should be localized and actionable (keep it boring).",
        "- Capture screenshots/logs for any new validations to make future triage faster.",
    ]
    sections["Quick smoke checklist"] = smoke

    return sections

def render_checklist_html(findings: Dict[str, Any], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    summ = findings.get("summary", {})
    sections = build_checklist_sections(findings)

    now = datetime.now(APP_TZ).strftime("%Y-%m-%d %H:%M")
    change_id = findings.get("change_id", "UNKNOWN")
    risk = f"{summ.get('risk_score','?')} ({summ.get('risk_level','?')})"

    html_parts = []
    html_parts.append("<!doctype html><html><head><meta charset='utf-8'>")
    html_parts.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    html_parts.append("<title>NAVI-CA Tester Scope Checklist</title>")
    html_parts.append("""
<style>
body{font-family:Arial,Helvetica,sans-serif;margin:24px;line-height:1.35;color:#111}
.card{border:1px solid #ddd;border-radius:12px;padding:14px 16px;margin-bottom:14px}
h1{margin:0 0 6px 0;font-size:22px}
.meta{color:#444;font-size:13px}
h2{font-size:16px;margin:0 0 8px 0}
ul{margin:8px 0 0 18px}
code{background:#f6f6f6;padding:2px 6px;border-radius:6px}
.small{font-size:12px;color:#666}
</style>
""")
    html_parts.append("</head><body>")

    html_parts.append("<div class='card'>")
    html_parts.append("<h1>NAVI-CA — Tester Scope Checklist</h1>")
    html_parts.append(f"<div class='meta'><b>Change:</b> <code>{change_id}</code> &nbsp; | &nbsp; <b>Generated:</b> {now} &nbsp; | &nbsp; <b>Risk:</b> {risk}</div>")
    html_parts.append("<div class='small'>Mindset: <b>Keep errors boring</b> — find gaps early so prod fixes are easy.</div>")
    html_parts.append("</div>")

    for title, items in sections.items():
        html_parts.append("<div class='card'>")
        html_parts.append(f"<h2>{title}</h2>")
        html_parts.append("<ul>")
        for item in items:
            # items may already start with "- "
            it = item[2:] if item.startswith("- ") else item
            html_parts.append(f"<li>{it}</li>")
        html_parts.append("</ul>")
        html_parts.append("</div>")

    html_parts.append("</body></html>")
    out_path.write_text("\n".join(html_parts), encoding="utf-8")
    return out_path

def render_checklist_pdf(findings: Dict[str, Any], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(out_path), pagesize=letter)
    width, height = letter
    left = 0.75 * inch
    y = height - 0.75 * inch
    line_h = 12

    summ = findings.get("summary", {})
    change_id = findings.get("change_id", "UNKNOWN")
    risk = f"{summ.get('risk_score','?')} ({summ.get('risk_level','?')})"
    now = datetime.now(APP_TZ).strftime("%Y-%m-%d %H:%M")

    c.setFont("Helvetica-Bold", 16)
    c.drawString(left, y, "NAVI-CA — Tester Scope Checklist")
    y -= 18

    c.setFont("Helvetica", 10)
    c.drawString(left, y, f"Change: {change_id}   |   Generated: {now}   |   Risk: {risk}")
    y -= 14
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(left, y, "Mindset: Keep errors boring — find gaps early so production fixes are easy.")
    y -= 18

    sections = build_checklist_sections(findings)

    def wrap(text: str, max_chars: int = 95):
        words = text.split()
        lines = []
        cur = []
        for w in words:
            if sum(len(x) for x in cur) + len(cur) + len(w) > max_chars:
                lines.append(" ".join(cur))
                cur = [w]
            else:
                cur.append(w)
        if cur:
            lines.append(" ".join(cur))
        return lines or [""]

    for title, items in sections.items():
        if y < 1.25 * inch:
            c.showPage()
            y = height - 0.75 * inch

        c.setFont("Helvetica-Bold", 12)
        c.drawString(left, y, title)
        y -= 14

        c.setFont("Helvetica", 10)
        for item in items:
            if y < 1.0 * inch:
                c.showPage()
                y = height - 0.75 * inch
                c.setFont("Helvetica", 10)

            bullet = u"\u2022 "
            lines = wrap(item[2:] if item.startswith("- ") else item)
            # first line with bullet
            c.drawString(left, y, bullet + lines[0])
            y -= line_h
            # subsequent lines indented
            for ln in lines[1:]:
                if y < 1.0 * inch:
                    c.showPage()
                    y = height - 0.75 * inch
                    c.setFont("Helvetica", 10)
                c.drawString(left + 14, y, ln)
                y -= line_h

        y -= 8

    c.save()
    return out_path
