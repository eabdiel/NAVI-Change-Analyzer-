# NAVI-CA (v0.1) — Annoying but Helpful

**Mission:** Keep errors boring. NAVI-ChangeAnalyzer helps you find testing gaps early by:
- parsing ABAP object lists (paste/CSV/JSON)
- mapping objects to custom apps (via `apps.json`)
- detecting overlap across other changes
- generating a risk score + interactive visuals (Bokeh)

## Quick Start (dev)
1) Create a venv and install dependencies:
```bash
python -m venv .venv
# Windows:
.\.venv\Scripts\activate
pip install -r cockpit-requirements.txt
```

2) Run the app:
```bash
python main.py
```

## App Catalog
Start with `sample_data/sample_apps.json` and copy it into your repo as `apps.json` (recommended path: `navica/apps.json`).
Update the match rules to reflect your packages/namespaces.

## Inputs Supported
- **Paste-in:** lines like `R3TR PROG ZREPORT`, tab-delimited exports, and mixed text.
- **CSV:** columns like `obj_class,obj_type,obj_name,package` (extra columns ignored).
- **JSON:** see `TECHSPEC.docx` for schemas.

## Packaging (later)
This starter kit includes placeholder files under `/packaging` for PyInstaller/Inno Setup.


## Exports
- Findings JSON
- Tester Scope Checklist (HTML/PDF)
