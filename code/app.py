"""
Cashy - blind review of cases (pipeline steps 4 and 5). The user interface is in English.

FinalScore is the score produced by Cashy. EligibilityTarget (and Elegibilidad, which encodes the
same decision) is the operation's final recorded decision; neither is shown on screen, so the
caseworker decides blind using the uncertainty, the FinalScore, the ai_recomandation (low / medium /
high, the FinalScore tercile from data_parse.py) and the household/scorecard fields.

The user picks the office, then their caseworker ID from the caseworkers assigned to that office
(CaseworkerID, created by data_parse.py), picks a pending case and presses "Include" or "Exclude"
(an optional note can be written first). On save:
  1. a row is appended to `revisiones` with all the case data, the blind decision in
     EligibilityTarget2, the note, reviewer, office and timestamp;
  2. in `casos`, uncertainty_pct becomes -uncertainty_pct (negative = reviewed), so the
     case leaves the queue.
Both happen in a single transaction: either both succeed or neither does.
EligibilityTarget2 != EligibilityTarget marks a disagreement between the blind review and the
recorded decision; the "Reviewed cases" view counts and lists them.

Look and feel: CSS in static/style.css, HTML snippets in templates/*.html (string.Template,
${var}), theme in .streamlit/config.toml.

Run (from the repository root):  streamlit run code/app.py
Database: code/cashy.db (or the path in the CASHY_DB environment variable)
"""
import html
import os
import sqlite3
from datetime import datetime
from string import Template

import pandas as pd
import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATIC = os.path.join(ROOT, "static")        # CSS
TEMPLATES = os.path.join(ROOT, "templates")  # HTML snippets (string.Template, ${var})
DB = os.environ.get("CASHY_DB", os.path.join(HERE, "cashy.db"))

RECORDED = "EligibilityTarget"   # recorded final decision: never shown, used only for comparison
BLIND = "EligibilityTarget2"     # the caseworker's blind decision
HIDDEN = {"EligibilityTarget", "Elegibilidad"}
NO_OFFICE = "(no office)"        # combobox label for cases with an empty OficinaACNUR
AI_REC = "ai_recomandation"      # column name as created by data_parse.py (low / medium / high)

# Uncertainty bands, used only for colours/labels. The Toolkit's uncertainty is min(p, 1-p), so it
# never exceeds 50; the cut-offs are percentiles of all cases instead of fixed values:
# top 10% = "High" (red), next 30% = "Medium" (gold), rest = "Low" (blue).
PCT_HIGH, PCT_MEDIUM = 0.90, 0.60
STYLES = {"alta": ("High", "#D9381E"), "media": ("Medium", "#8b6900"), "baja": ("Low", "#005994")}
PAGE_SIZE = 12

GROUPS = {
    "Household": ["caseID", "CaseworkerID", "month", "OficinaACNUR", "NumIntegrantes", "dependencyCategory",
                  "FemaleHeadedHousehold", "CuidadorSolo", "HablaEspanol", "Analfabeta_si"],
    "Cashy scores": ["FinalScore", AI_REC, "Demographics_Score", "NeedsandCoping_Score",
                     "Vulnerability_Score", "Vulnerability_Category"],
    "Scorecard factors": ["Demographics.HH.Head", "Demographics.Language", "Demographics.Profiles",
                          "Demographics.Documentation", "Needs_and_Coping.BasicNeeds",
                          "Needs_and_Coping.Housing", "Needs_and_Coping.Neg.mechanism",
                          "Needs_and_Coping.Dependency"],
    "Administrative flags": ["ScoreCOMAR_PIL", "ScoreIntenciones", "ScoreDuplicidad"],
}
assert not HIDDEN & {c for cols in GROUPS.values() for c in cols}, "a hidden column is listed on screen"


# ---------------------------------------------------------------- data layer
def connect():
    if not os.path.exists(DB):
        st.error(f"Database `{DB}` not found. Create it first: `python code/data_parse.py` "
                 "and then `python code/create_db.py`")
        st.stop()
    con = sqlite3.connect(DB, timeout=10, isolation_level=None)  # manual transactions
    con.row_factory = sqlite3.Row
    cols = {r[1] for r in con.execute("PRAGMA table_info(revisiones)")}
    if BLIND not in cols:
        st.error("This database has the old `revisiones` layout (accion / decision_overriden). "
                 "Recreate it: `python code/create_db.py --reset`")
        st.stop()
    return con


def offices(con):
    names = [r[0] for r in con.execute(
        "SELECT DISTINCT OficinaACNUR FROM casos WHERE OficinaACNUR IS NOT NULL ORDER BY 1")]
    if con.execute("SELECT 1 FROM casos WHERE OficinaACNUR IS NULL LIMIT 1").fetchone():
        names.append(NO_OFFICE)
    return names


def caseworkers(con, office):
    """Caseworker IDs assigned (CaseworkerID) to cases of this office."""
    cond, p = office_filter(office)
    return [r[0] for r in con.execute(
        f"SELECT DISTINCT CaseworkerID FROM casos WHERE CaseworkerID IS NOT NULL AND {cond} ORDER BY 1", p)]


def office_filter(office):
    if office == NO_OFFICE:
        return "OficinaACNUR IS NULL", ()
    return "OficinaACNUR = ?", (office,)


def pending(con, minimum, office):
    cond, p = office_filter(office)
    return pd.read_sql_query(
        f"SELECT * FROM casos WHERE uncertainty_pct > 0 AND uncertainty_pct >= ? AND {cond} "
        "ORDER BY uncertainty_pct DESC", con, params=(minimum, *p))


def save_review(case_id, decision, note, reviewer, office):
    """Copy the case to `revisiones` with the blind decision and mark it as reviewed. Atomic."""
    con = sqlite3.connect(DB, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("BEGIN IMMEDIATE")
    try:
        row = con.execute("SELECT * FROM casos WHERE caso_id = ? AND uncertainty_pct > 0",
                          (case_id,)).fetchone()
        if row is None:
            raise ValueError("This case has already been reviewed.")
        data = {k: row[k] for k in row.keys() if k != "uncertainty_pct"}
        data.update({
            "uncertainty_original": row["uncertainty_pct"],
            BLIND: decision,
            "nota": (note or "").strip() or None,
            "revisor": reviewer.strip(),
            "sede_revisor": office,
            "fecha_revision": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        cols = ", ".join(f'"{c}"' for c in data)
        marks = ", ".join("?" for _ in data)
        con.execute(f"INSERT INTO revisiones ({cols}) VALUES ({marks})", list(data.values()))
        con.execute("UPDATE casos SET uncertainty_pct = -uncertainty_pct "
                    "WHERE caso_id = ? AND uncertainty_pct > 0", (case_id,))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


# ---------------------------------------------------------------- presentation helpers
def load_css():
    with open(os.path.join(STATIC, "style.css"), encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


_cache = {}


def template(name, **values):
    """Render templates/<name>.html; every value is HTML-escaped."""
    if name not in _cache:
        with open(os.path.join(TEMPLATES, f"{name}.html"), encoding="utf-8") as f:
            _cache[name] = Template(f.read())
    return _cache[name].substitute({k: html.escape(str(v)) for k, v in values.items()})


def render(name, **values):
    st.markdown(template(name, **values), unsafe_allow_html=True)


def cutoffs(con):
    """(High, Medium) = 90th and 60th percentile of |uncertainty_pct| over ALL cases.
    abs() keeps reviewed cases (stored as negative) in, so the cut-offs do not move as people review."""
    u = pd.Series([abs(r[0]) for r in con.execute("SELECT uncertainty_pct FROM casos")], dtype=float)
    return float(u.quantile(PCT_HIGH)), float(u.quantile(PCT_MEDIUM))


def band(u, limits):
    high, medium = limits
    key = "alta" if u >= high else "media" if u >= medium else "baja"
    return (key, *STYLES[key])


def fmt(v):
    return "—" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)


# ---------------------------------------------------------------- user interface
st.set_page_config(page_title="Cashy · Case review", page_icon=":material/shield_person:", layout="wide")
load_css()
con = connect()
LIMITS = cutoffs(con)

with st.sidebar:
    st.markdown('<span class="cx-side-label">Reviewer</span>', unsafe_allow_html=True)
    office = st.selectbox("UNHCR office", offices(con), index=None,
                          placeholder="Choose your office", key="sede")
    workers = caseworkers(con, office) if office else []
    # one widget key per office, so changing the office never keeps a caseworker from another office
    reviewer = st.selectbox("Caseworker", workers, index=None, key=f"revisor_{office}", disabled=not workers,
                            placeholder="Choose your caseworker ID" if workers else
                            ("No caseworkers assigned to this office" if office else "Choose an office first"))
    reviewer = reviewer or ""
    n_pending = n_reviewed = 0
    if office:
        cond, p = office_filter(office)
        n_pending = con.execute(f"SELECT COUNT(*) FROM casos WHERE uncertainty_pct > 0 AND {cond}", p).fetchone()[0]
        n_reviewed = con.execute(f"SELECT COUNT(*) FROM casos WHERE uncertainty_pct < 0 AND {cond}", p).fetchone()[0]
    st.markdown('<span class="cx-side-label">Navigation</span>', unsafe_allow_html=True)
    view = st.radio("Navigation", ["queue", "reviewed"], key="vista", label_visibility="collapsed",
                    format_func=lambda v: ":material/inbox: Case queue" if v == "queue"
                    else ":material/check_circle: Reviewed cases")  # static labels: dynamic ones reset the radio
    max_unc = float(con.execute("SELECT MAX(ABS(uncertainty_pct)) FROM casos").fetchone()[0] or 100)
    minimum = st.slider("Minimum uncertainty", 0.0, float(-(-max_unc // 1)), 0.0, 0.5, key="minimo")
    st.caption(f"High ≥ {LIMITS[0]:.1f}% · Medium ≥ {LIMITS[1]:.1f}% (90th and 60th percentile of all cases)")
    render("sidebar_footer", pendientes=n_pending if office else "—",
           revisados=f"{n_reviewed} / {n_pending + n_reviewed}" if office else "—")

render("topbar", revisor=reviewer.strip() or "Not identified", sede=office or "No office selected")

notice = st.session_state.pop("aviso", None)
if notice:
    st.toast(notice, icon=":material/check_circle:")


def decide(case_id, decision):
    try:
        save_review(case_id, decision, st.session_state.get("nota", ""), reviewer, office)
    except ValueError as e:
        st.error(str(e))
        return
    st.session_state["aviso"] = f"Case {case_id} saved: {decision}."
    st.session_state.pop("caso_sel", None)
    st.session_state["limpiar_nota"] = True
    st.rerun()


if st.session_state.pop("limpiar_nota", False):  # clear the note before the text area is drawn
    st.session_state["nota"] = ""

if not office:
    st.info("Choose your office in the sidebar to see the pending cases.", icon=":material/location_on:")

elif view == "queue":
    queue = pending(con, minimum, office)
    left, right = st.columns([5, 7], gap="medium")

    with left:
        with st.container(key="panel_cola"):
            render("queue_head", pendientes=len(queue))
            if queue.empty:
                st.caption("No pending cases at this uncertainty level.")
            else:
                ids = list(queue["caso_id"])
                if st.session_state.get("caso_sel") not in ids:
                    st.session_state["caso_sel"] = ids[0]
                pages = max(1, -(-len(ids) // PAGE_SIZE))
                page = min(st.session_state.get("pag", 0), pages - 1)
                for _, row in queue.iloc[page * PAGE_SIZE:(page + 1) * PAGE_SIZE].iterrows():
                    cid = row["caso_id"]
                    sel = cid == st.session_state["caso_sel"]
                    with st.container(key=("qsel_" if sel else "q_") + cid):
                        render("queue_item", sel="sel" if sel else "", caso_id=cid, mes=row["month"],
                               nivel=band(row["uncertainty_pct"], LIMITS)[0], unc=f"{row['uncertainty_pct']:.1f}")
                        if st.button(f"Open {cid}", key=f"abrir_{cid}"):
                            st.session_state["caso_sel"] = cid
                            st.rerun()
                if pages > 1:
                    with st.container(key="pager"):
                        a, b, c = st.columns([1, 2, 1])
                        if a.button("", icon=":material/chevron_left:", key="prev", disabled=page == 0):
                            st.session_state["pag"] = page - 1
                            st.rerun()
                        b.caption(f"Page {page + 1} of {pages}")
                        if c.button("", icon=":material/chevron_right:", key="next", disabled=page >= pages - 1):
                            st.session_state["pag"] = page + 1
                            st.rerun()

    with right:
        if not queue.empty:
            case_id = st.session_state["caso_sel"]
            case = queue.set_index("caso_id").loc[case_id]
            key, label, colour = band(case["uncertainty_pct"], LIMITS)
            with st.container(key="panel_caso"):
                render("case", caso_id=case_id, nivel=key, nivel_txt=label, ring=colour,
                       unc=f"{case['uncertainty_pct']:.1f}", mes=case["month"],
                       oficina=fmt(case["OficinaACNUR"]) if office != NO_OFFICE else NO_OFFICE,
                       finalscore=f"{case['FinalScore']:.2f}", ai_rec=fmt(case[AI_REC]).capitalize(),
                       ai_cls=str(case[AI_REC]).lower())
                with st.container(key="detalles"):
                    with st.expander("View case details", icon=":material/description:"):
                        for title, fields in GROUPS.items():
                            rows = "".join(f"<tr><td>{html.escape(c)}</td><td>{html.escape(fmt(case[c]))}</td></tr>"
                                           for c in fields)
                            st.markdown(f'<span class="cx-caps">{html.escape(title)}</span>'
                                        f'<table class="cx-details">{rows}</table>', unsafe_allow_html=True)
                with st.container(key="acciones"):
                    no_id = not reviewer.strip()
                    st.text_area("Note (optional)", key="nota", height=90,
                                 placeholder="Why do you include or exclude this household?")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("Exclude", key="btn_exclude", icon=":material/block:",
                                     disabled=no_id, width="stretch"):
                            decide(case_id, "EXCLUSION")
                    with c2:
                        if st.button("Include", key="btn_include", icon=":material/check_circle:",
                                     disabled=no_id, width="stretch"):
                            decide(case_id, "INCLUSION")
                    if no_id:
                        st.caption("Choose your caseworker ID in the sidebar to enable the decision buttons.")

else:  # reviewed
    cond, p = office_filter(office)
    rev = pd.read_sql_query(f"SELECT * FROM revisiones WHERE {cond} ORDER BY revision_id DESC", con, params=p)
    rev["Agreement"] = (rev[BLIND] == rev[RECORDED]).map({True: "Agrees", False: "Disagrees"})
    n = len(rev)
    n_dis = int((rev["Agreement"] == "Disagrees").sum())
    with st.container(key="panel_hist"):
        render("kpis", total=n, incluidos=int((rev[BLIND] == "INCLUSION").sum()),
               excluidos=int((rev[BLIND] == "EXCLUSION").sum()), desacuerdos=n_dis,
               pct=f"{100 * n_dis / n:.1f}%" if n else "—")
        only_dis = st.toggle("Show only disagreements (EligibilityTarget2 ≠ EligibilityTarget)", key="solo_desac")
        shown = rev[rev["Agreement"] == "Disagrees"] if only_dis else rev
        first = ["revision_id", "caso_id", "fecha_revision", "revisor", "CaseworkerID", "sede_revisor",
                 "uncertainty_original", "FinalScore", AI_REC, BLIND, RECORDED, "Agreement", "nota"]
        shown = shown[first + [c for c in shown.columns if c not in first]]
        st.dataframe(shown, hide_index=True, width="stretch")
        if n:
            st.download_button("Download reviews (CSV)", rev.to_csv(index=False).encode("utf-8-sig"),
                               "revisiones.csv", "text/csv", icon=":material/download:")
