from __future__ import annotations

import csv
import io
import json
import re
from typing import List, Dict, Any

_ABAP_LINE_RE = re.compile(
    r"(?P<obj_class>R3TR|LIMU)\s+"
    r"(?P<obj_type>[A-Z0-9_]{3,5})\s+"
    r"(?P<obj_name>[A-Z0-9_/\\\-~><=]+)",
    re.IGNORECASE
)

# Common ABAP object types used for scoping (not exhaustive)
KNOWN_TYPES = {
    # reports/programs
    "PROG", "REPS", "REPT",
    # enhancements / exits
    "CMOD", "SMOD", "ENHO", "ENHS", "SPOT",
    # classes/fms
    "CLAS", "INTF", "FUGR", "FUNC",
    # data dictionary
    "TABL", "VIEW", "DTEL", "DOMA", "TTYP", "DDLS"
}

def _norm(s: str) -> str:
    return (s or "").strip().upper()

def _make_obj(obj_class: str, obj_type: str, obj_name: str, raw: str = "", package: str | None = None, component: str | None = None) -> Dict[str, Any]:
    obj_class = _norm(obj_class)
    obj_type = _norm(obj_type)
    obj_name = _norm(obj_name)

    normalized_key = f"{obj_class}:{obj_type}:{obj_name}"
    return {
        "obj_class": obj_class,
        "obj_type": obj_type,
        "obj_name": obj_name,
        "subtype": None,
        "package": _norm(package) if package else None,
        "component": _norm(component) if component else None,
        "raw": raw.strip() if raw else "",
        "normalized_key": normalized_key,
    }

def parse_abap_object_text(text: str) -> List[Dict[str, Any]]:
    """
    Generic ABAP object list parser for:
      - space/tab delimited exports
      - mixed text containing patterns like: 'R3TR PROG ZREPORT'
    Dedupes by normalized_key.
    """
    if not text or not text.strip():
        return []

    found = {}
    for line in text.splitlines():
        ln = line.strip()
        if not ln:
            continue

        # Try regex first
        m = _ABAP_LINE_RE.search(ln)
        if m:
            o = _make_obj(m.group("obj_class"), m.group("obj_type"), m.group("obj_name"), raw=ln)
            found[o["normalized_key"]] = o
            continue

        # Fallback: split by whitespace/tabs and look for 3 tokens
        parts = re.split(r"[\t\s]+", ln)
        if len(parts) >= 3 and _norm(parts[0]) in {"R3TR", "LIMU"}:
            otype = _norm(parts[1])
            oname = _norm(parts[2])
            o = _make_obj(parts[0], otype, oname, raw=ln)
            found[o["normalized_key"]] = o
            continue

        # Another fallback: look for known type + object name
        # e.g., 'PROG ZFOO' without R3TR
        if len(parts) >= 2 and _norm(parts[0]) in KNOWN_TYPES:
            o = _make_obj("R3TR", parts[0], parts[1], raw=ln)
            found[o["normalized_key"]] = o

    return list(found.values())

def load_objects_from_csv(raw_bytes: bytes) -> List[Dict[str, Any]]:
    if not raw_bytes:
        return []
    txt = raw_bytes.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(txt))
    found = {}
    for row in reader:
        obj_class = row.get("obj_class", "R3TR")
        obj_type = row.get("obj_type") or row.get("object_type") or row.get("type") or ""
        obj_name = row.get("obj_name") or row.get("object_name") or row.get("name") or ""
        package = row.get("package") or row.get("devclass") or None
        component = row.get("component") or None
        if not obj_type or not obj_name:
            continue
        o = _make_obj(obj_class, obj_type, obj_name, raw=json.dumps(row), package=package, component=component)
        found[o["normalized_key"]] = o
    return list(found.values())

def load_objects_from_json(raw_bytes: bytes) -> List[Dict[str, Any]]:
    if not raw_bytes:
        return []
    data = json.loads(raw_bytes.decode("utf-8", errors="replace"))
    # Accept either {"objects":[...]} or full change schema
    objects = data.get("objects", data if isinstance(data, list) else [])
    found = {}
    for o0 in objects:
        if not isinstance(o0, dict):
            continue
        obj_class = o0.get("obj_class", "R3TR")
        obj_type = o0.get("obj_type") or o0.get("object_type") or ""
        obj_name = o0.get("obj_name") or o0.get("object_name") or ""
        package = o0.get("package")
        component = o0.get("component")
        raw = o0.get("raw", "")
        if not obj_type or not obj_name:
            continue
        o = _make_obj(obj_class, obj_type, obj_name, raw=str(raw), package=package, component=component)
        found[o["normalized_key"]] = o
    return list(found.values())
