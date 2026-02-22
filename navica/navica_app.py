from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd

from bokeh.layouts import column, row
from bokeh.models import (
    Div, Tabs, Panel, TextAreaInput, Button, FileInput, DataTable, TableColumn,
    ColumnDataSource, Select, NumericInput, Spacer
)
from bokeh.plotting import figure
from bokeh.models.graphs import from_networkx
from bokeh.models import HoverTool
import networkx as nx

from navica.core.parser import parse_abap_object_text, load_objects_from_csv, load_objects_from_json
from navica.core.mapping import load_app_catalog, map_objects_to_apps
from navica.core.scoring import score_change
from navica.core.exporter import render_checklist_html, render_checklist_pdf
from navica.data.db import NavicaDB

APP_TZ = timezone(timedelta(hours=-5))  # America/New_York offset (naive)
HERE = Path(__file__).resolve().parent

def build_document(doc):
    doc.title = "NAVI-CA — Annoying but Helpful"

    banner_path = HERE / "assets" / "banner.txt"
    banner = banner_path.read_text(encoding="utf-8") if banner_path.exists() else "NAVI-CA"

    header = Div(
        text=f"""
        <div style="padding:12px 16px; border-radius:12px; border:1px solid #ddd;">
          <div style="font-size:20px; font-weight:700;">{banner}</div>
          <div style="margin-top:6px; font-size:13px; color:#444;">
            Mindset: <b>Keep errors boring</b> — find gaps early so prod fixes are easy (no “call everyone and their moms” nights).
          </div>
        </div>
        """,
        sizing_mode="stretch_width",
    )

    db = NavicaDB()

    # ---- Load Tab (Paste / Import) ----
    change_id = Select(title="Change ID", value="CHG-LOCAL-001", options=["CHG-LOCAL-001"])
    change_title = Select(title="Title (quick label)", value="Local analysis", options=["Local analysis"])
    overlap_days = NumericInput(title="Overlap window (days)", value=30, low=1, high=365)

    paste = TextAreaInput(
        title="Paste ABAP object list (raw export is fine)",
        rows=10,
        placeholder="Example:\nR3TR PROG ZFI_POSTING_REPORT\nR3TR CMOD ZFI_EXIT_001\nR3TR ENHO ZENH_IMPL_FI_POST\n...",
        sizing_mode="stretch_width",
    )

    file_csv = FileInput(accept=".csv", multiple=False)
    file_json = FileInput(accept=".json", multiple=False)

    btn_analyze = Button(label="Analyze", button_type="primary")
    status = Div(text="<i>Ready.</i>", sizing_mode="stretch_width")

    # ---- Summary Outputs ----
    kpis = Div(text="", sizing_mode="stretch_width")
    top_tbl_source = ColumnDataSource(dict(obj=[], points=[], reasons=[]))
    top_tbl = DataTable(
        source=top_tbl_source,
        columns=[
            TableColumn(field="obj", title="Object"),
            TableColumn(field="points", title="Risk Points"),
            TableColumn(field="reasons", title="Why"),
        ],
        height=260,
        sizing_mode="stretch_width",
    )

    by_type_source = ColumnDataSource(dict(obj_type=[], count=[]))
    by_type_fig = figure(height=260, sizing_mode="stretch_width", title="Objects by Type")
    by_type_fig.vbar(x="obj_type", top="count", source=by_type_source, width=0.8)

    # ---- Impacted Apps ----
    apps_source = ColumnDataSource(dict(app_id=[], display_name=[], impact_score=[], matched_objects=[], tags=[]))
    apps_tbl = DataTable(
        source=apps_source,
        columns=[
            TableColumn(field="display_name", title="Impacted App"),
            TableColumn(field="impact_score", title="Impact Score"),
            TableColumn(field="matched_objects", title="Matched Objects"),
            TableColumn(field="tags", title="Tags"),
        ],
        height=320,
        sizing_mode="stretch_width",
    )

    # ---- Overlaps ----
    overlaps_source = ColumnDataSource(dict(other_change_id=[], shared_object_count=[]))
    overlaps_tbl = DataTable(
        source=overlaps_source,
        columns=[
            TableColumn(field="other_change_id", title="Other Change"),
            TableColumn(field="shared_object_count", title="Shared Objects"),
        ],
        height=260,
        sizing_mode="stretch_width",
    )

    # ---- Risk Map ----
    graph_fig = figure(height=520, sizing_mode="stretch_width", title="Risk Map (spider/network)")
    graph_fig.add_tools(HoverTool(tooltips=[("node", "@index")]))

    def _build_graph(objects, impacted_apps, risk_points_by_key):
        # nodes: apps + objects; edges: app -> object for matched ones, otherwise change -> object
        G = nx.Graph()
        change_node = "CHANGE"
        G.add_node(change_node, kind="change", risk_points=0)

        # Add object nodes
        for o in objects:
            nk = o["normalized_key"]
            rp = int(risk_points_by_key.get(nk, 0))
            G.add_node(nk, kind="object", risk_points=rp)

        # Add app nodes & edges
        for app in impacted_apps:
            aid = f"APP::{app['app_id']}"
            G.add_node(aid, kind="app", risk_points=0)
            # Connect to top objects for now
            for nk in app.get("top_objects", []):
                if G.has_node(nk):
                    G.add_edge(aid, nk)

        # Connect change to all objects (keeps the graph from fragmenting)
        for o in objects:
            G.add_edge(change_node, o["normalized_key"])

        # Layout
        pos = nx.spring_layout(G, seed=42, k=0.9)
        return G, pos

    def _render_graph(objects, impacted_apps, findings):
        graph_fig.renderers.clear()
        if not objects:
            graph_fig.title.text = "Risk Map (spider/network) — (no data yet)"
            return

        # Build lookup: object normalized_key -> risk_points
        risk_points_by_key = {}
        for r in (findings or {}).get("object_risks", []):
            k = r.get("normalized_key")
            if k:
                risk_points_by_key[k] = int(r.get("risk_points", 0))

        G, pos = _build_graph(objects, impacted_apps, risk_points_by_key)
        gr = from_networkx(G, pos)

        # Node size reflects risk points (objects), apps/change fixed.
        ds = gr.node_renderer.data_source
        idxs = list(ds.data.get("index", []))

        sizes = []
        for node in idxs:
            kind = G.nodes[node].get("kind")
            rp = int(G.nodes[node].get("risk_points", 0))
            if kind == "object":
                # map risk points -> size (bounded)
                sizes.append(max(8, min(34, 6 + rp)))
            elif kind == "app":
                sizes.append(16)
            else:  # change
                sizes.append(18)

        ds.data["size"] = sizes
        # Show risk in hover via extra field
        ds.data["risk_points"] = [int(G.nodes[n].get("risk_points", 0)) for n in idxs]
        ds.data["kind"] = [G.nodes[n].get("kind", "") for n in idxs]

        gr.node_renderer.glyph.size = "size"

        # Upgrade hover
        graph_fig.tools = [t for t in graph_fig.tools if not isinstance(t, HoverTool)]
        graph_fig.add_tools(HoverTool(tooltips=[("node", "@index"), ("kind", "@kind"), ("risk", "@risk_points")]))

        graph_fig.renderers.append(gr)
        graph_fig.title.text = "Risk Map (spider/network) — object node size reflects risk points"
        G, pos = _build_graph(objects, impacted_apps)
        gr = from_networkx(G, pos)
        graph_fig.renderers.append(gr)
        graph_fig.title.text = "Risk Map (spider/network) — apps ↔ objects"

    # ---- Export ----
    export_div = Div(text="")
    btn_export = Button(label="Export Findings JSON", button_type="success")
    btn_export_html = Button(label="Export Tester Checklist (HTML)", button_type="default")
    btn_export_pdf = Button(label="Export Tester Checklist (PDF)", button_type="default")

    latest_findings = {"data": None}

    def _decode_fileinput(fi: FileInput) -> bytes:
        # FileInput.value is base64 string without the prefix
        import base64
        if not fi.value:
            return b""
        return base64.b64decode(fi.value)

    def _load_objects():
        # precedence: CSV, JSON, then paste
        if file_csv.value:
            raw = _decode_fileinput(file_csv)
            return load_objects_from_csv(raw)
        if file_json.value:
            raw = _decode_fileinput(file_json)
            return load_objects_from_json(raw)
        return parse_abap_object_text(paste.value or "")

    def _analyze():
        try:
            objects = _load_objects()
            if not objects:
                status.text = "<b style='color:#b00;'>No objects found.</b> Paste text or import CSV/JSON."
                return

            # Load app catalog (optional in MVP)
            app_catalog = load_app_catalog()
            impacted_apps = map_objects_to_apps(objects, app_catalog)

            # Score
            findings = score_change(
                change_id.value,
                objects=objects,
                impacted_apps=impacted_apps,
                overlap_window_days=int(overlap_days.value or 30),
                db=db,
            )

            latest_findings["data"] = findings

            # Persist history for overlap
            db.save_change(findings["change_id"], findings)

            # Update UI KPIs
            summ = findings["summary"]
            kpis.text = f"""
            <div style="display:flex; gap:12px; flex-wrap:wrap;">
              <div style="padding:10px 12px; border:1px solid #ddd; border-radius:12px;">
                <div style="font-size:12px; color:#666;">Risk</div>
                <div style="font-size:22px; font-weight:700;">{summ['risk_score']} <span style="font-size:12px; color:#666;">({summ['risk_level']})</span></div>
              </div>
              <div style="padding:10px 12px; border:1px solid #ddd; border-radius:12px;">
                <div style="font-size:12px; color:#666;">Objects</div>
                <div style="font-size:22px; font-weight:700;">{summ['objects_total']}</div>
              </div>
              <div style="padding:10px 12px; border:1px solid #ddd; border-radius:12px;">
                <div style="font-size:12px; color:#666;">Apps impacted</div>
                <div style="font-size:22px; font-weight:700;">{summ['apps_impacted']}</div>
              </div>
              <div style="padding:10px 12px; border:1px solid #ddd; border-radius:12px;">
                <div style="font-size:12px; color:#666;">Overlaps</div>
                <div style="font-size:22px; font-weight:700;">{summ['overlaps_found']}</div>
              </div>
            </div>
            """

            # Top risk objects table
            top = findings.get("object_risks", [])[:25]
            top_tbl_source.data = dict(
                obj=[t["normalized_key"] for t in top],
                points=[t["risk_points"] for t in top],
                reasons=[", ".join(t["reasons"]) for t in top],
            )

            # Objects by type chart
            counts = pd.Series([o["obj_type"] for o in objects]).value_counts().reset_index()
            counts.columns = ["obj_type", "count"]
            by_type_source.data = counts.to_dict(orient="list")

            # Apps table
            apps = findings.get("impacted_apps", [])
            apps_source.data = dict(
                app_id=[a["app_id"] for a in apps],
                display_name=[a.get("display_name", a["app_id"]) for a in apps],
                impact_score=[round(a.get("impact_score", 0), 2) for a in apps],
                matched_objects=[a.get("matched_objects", 0) for a in apps],
                tags=[", ".join(a.get("tags", [])) for a in apps],
            )

            # Overlaps table
            overlaps = findings.get("overlaps", [])
            overlaps_source.data = dict(
                other_change_id=[o["other_change_id"] for o in overlaps],
                shared_object_count=[o["shared_object_count"] for o in overlaps],
            )

            # Risk map
            _render_graph(objects, apps, findings)

            status.text = "<b style='color:#060;'>Analysis complete.</b>"

        except Exception as ex:
            status.text = f"<b style='color:#b00;'>Error:</b> {ex!r}"

    def _export():
        f = latest_findings["data"]
        if not f:
            export_div.text = "<b style='color:#b00;'>Nothing to export yet.</b>"
            return
        out_dir = db.ensure_out_dir()
        ts = datetime.now(APP_TZ).strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"findings_{f['change_id']}_{ts}.json"
        out_path.write_text(json.dumps(f, indent=2), encoding="utf-8")
        export_div.text = f"✅ Exported: <code>{out_path}</code>"


    def _export_html():
        f = latest_findings["data"]
        if not f:
            export_div.text = "<b style='color:#b00;'>Nothing to export yet.</b>"
            return
        out_dir = db.ensure_out_dir()
        ts = datetime.now(APP_TZ).strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"tester_scope_{f['change_id']}_{ts}.html"
        render_checklist_html(f, out_path)
        export_div.text = f"✅ Exported HTML: <code>{out_path}</code>"

    def _export_pdf():
        f = latest_findings["data"]
        if not f:
            export_div.text = "<b style='color:#b00;'>Nothing to export yet.</b>"
            return
        out_dir = db.ensure_out_dir()
        ts = datetime.now(APP_TZ).strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"tester_scope_{f['change_id']}_{ts}.pdf"
        render_checklist_pdf(f, out_path)
        export_div.text = f"✅ Exported PDF: <code>{out_path}</code>"
    btn_analyze.on_click(_analyze)
    btn_export.on_click(_export)
    btn_export_html.on_click(_export_html)
    btn_export_pdf.on_click(_export_pdf)

    load_tab = column(
        row(change_id, overlap_days),
        paste,
        Div(text="<b>Import instead:</b>"),
        row(column(Div(text="CSV"), file_csv), column(Div(text="JSON"), file_json)),
        row(btn_analyze),
        status,
        sizing_mode="stretch_width",
    )

    summary_tab = column(kpis, row(by_type_fig), Div(text="<b>Top Risk Objects</b>"), top_tbl, sizing_mode="stretch_width")
    apps_tab = column(Div(text="<b>Impacted Apps</b>"), apps_tbl, sizing_mode="stretch_width")
    overlaps_tab = column(Div(text="<b>Overlaps (last N days)</b>"), overlaps_tbl, sizing_mode="stretch_width")
    riskmap_tab = column(graph_fig, sizing_mode="stretch_width")
    export_tab = column(row(btn_export, btn_export_html, btn_export_pdf), export_div, sizing_mode="stretch_width")

    tabs = Tabs(tabs=[
        Panel(child=load_tab, title="Load"),
        Panel(child=summary_tab, title="Summary"),
        Panel(child=apps_tab, title="Impacted Apps"),
        Panel(child=overlaps_tab, title="Overlaps"),
        Panel(child=riskmap_tab, title="Risk Map"),
        Panel(child=export_tab, title="Export"),
    ])

    doc.add_root(column(header, Spacer(height=10), tabs, sizing_mode="stretch_width"))
