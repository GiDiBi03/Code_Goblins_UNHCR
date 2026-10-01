"""
Cashy - review of high-uncertainty cases (pipeline steps 4 and 5).

Reads the `casos` table from the SQLite database. The caseworker picks their office
(OficinaACNUR), picks a pending case from the queue and either confirms its
EligibilityTarget ("Confirmar recomendación") or modifies it with a mandatory note
("Modificar con nota"). On save:
  1. a row is appended to `revisiones` with all the case data + the review;
  2. in `casos`, uncertainty_pct becomes -uncertainty_pct (negative = reviewed), so the
     case leaves the queue.
Both happen in a single transaction: either both succeed or neither does.

Look and feel follow web_pages.html: CSS in static/style.css, HTML snippets in
templates/*.html (string.Template, ${var}), theme in .streamlit/config.toml.
The user interface is in Spanish.

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

# Recommendation the caseworker confirms or modifies.
REC = "EligibilityTarget"
# Combobox label for cases with an empty OficinaACNUR.
SIN_OFICINA = "(sin oficina)"
# Uncertainty bands used only for colours/labels (same breakpoints as web_pages.html).
BANDAS = [(80, "alta", "Alta", "#D9381E"), (70, "media", "Media", "#8b6900"), (0, "baja", "Baja", "#005994")]
POR_PAGINA = 12

GRUPOS = {
    "Registro": ["month", "OficinaACNUR", "NumIntegrantes", "dependencyCategory",
                 "FemaleHeadedHousehold", "CuidadorSolo", "HablaEspanol", "Analfabeta_si"],
    "Puntajes": ["FinalScore", "Demographics_Score", "NeedsandCoping_Score",
                 "Vulnerability_Score", "Vulnerability_Category"],
    "Factores del Scorecard": ["Demographics.HH.Head", "Demographics.Language", "Demographics.Profiles",
                               "Demographics.Documentation", "Needs_and_Coping.BasicNeeds",
                               "Needs_and_Coping.Housing", "Needs_and_Coping.Neg.mechanism",
                               "Needs_and_Coping.Dependency"],
    "Flags administrativos": ["ScoreCOMAR_PIL", "ScoreIntenciones", "ScoreDuplicidad"],
}


def conectar():
    if not os.path.exists(DB):
        st.error(f"No encuentro la base `{DB}`. Créala primero: `python code/data_parse.py` y luego `python code/create_db.py`")
        st.stop()
    con = sqlite3.connect(DB, timeout=10, isolation_level=None)  # manual transactions
    con.row_factory = sqlite3.Row
    return con


def sedes(con):
    lista = [r[0] for r in con.execute(
        "SELECT DISTINCT OficinaACNUR FROM casos WHERE OficinaACNUR IS NOT NULL ORDER BY 1")]
    if con.execute("SELECT 1 FROM casos WHERE OficinaACNUR IS NULL LIMIT 1").fetchone():
        lista.append(SIN_OFICINA)
    return lista


def filtro_sede(sede):
    if sede == SIN_OFICINA:
        return "OficinaACNUR IS NULL", ()
    return "OficinaACNUR = ?", (sede,)


def pendientes(con, minimo, sede):
    cond, p = filtro_sede(sede)
    return pd.read_sql_query(
        f"SELECT * FROM casos WHERE uncertainty_pct > 0 AND uncertainty_pct >= ? AND {cond} "
        "ORDER BY uncertainty_pct DESC", con, params=(minimo, *p))


def guardar_revision(caso_id, accion, decision, nota, revisor, sede):
    """Copy the case to `revisiones` and mark it as reviewed in `casos`. Atomic.
    Opens its own connection: the modify dialog runs in a different thread than the page."""
    con = sqlite3.connect(DB, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("BEGIN IMMEDIATE")
    try:
        fila = con.execute("SELECT * FROM casos WHERE caso_id = ? AND uncertainty_pct > 0",
                           (caso_id,)).fetchone()
        if fila is None:
            raise ValueError("Este caso ya fue revisado por otra persona.")
        datos = {k: fila[k] for k in fila.keys() if k != "uncertainty_pct"}
        datos.update({
            "uncertainty_original": fila["uncertainty_pct"],
            "accion": accion,
            "decision_overriden": decision,
            "nota": nota.strip() or None,
            "revisor": revisor.strip(),
            "sede_revisor": sede,
            "fecha_revision": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        cols = ", ".join(f'"{c}"' for c in datos)
        marcas = ", ".join("?" for _ in datos)
        con.execute(f"INSERT INTO revisiones ({cols}) VALUES ({marcas})", list(datos.values()))
        con.execute("UPDATE casos SET uncertainty_pct = -uncertainty_pct "
                    "WHERE caso_id = ? AND uncertainty_pct > 0", (caso_id,))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


# ---------------------------------------------------------------- presentation helpers
def cargar_css():
    with open(os.path.join(STATIC, "style.css"), encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


_cache = {}


def plantilla(nombre, **valores):
    """Render templates/<nombre>.html; every value is HTML-escaped."""
    if nombre not in _cache:
        with open(os.path.join(TEMPLATES, f"{nombre}.html"), encoding="utf-8") as f:
            _cache[nombre] = Template(f.read())
    seguros = {k: html.escape(str(v)) for k, v in valores.items()}
    return _cache[nombre].substitute(seguros)


def pintar(nombre, **valores):
    st.markdown(plantilla(nombre, **valores), unsafe_allow_html=True)


def banda(u):
    for minimo, clase, texto, color in BANDAS:
        if u >= minimo:
            return clase, texto, color
    return BANDAS[-1][1:]


def fmt(v):
    return "—" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)


# ---------------------------------------------------------------- user interface
st.set_page_config(page_title="Cashy · Revisión de casos", page_icon=":material/shield_person:", layout="wide")
cargar_css()
con = conectar()

with st.sidebar:
    st.markdown('<span class="cx-side-label">Revisor</span>', unsafe_allow_html=True)
    revisor = st.text_input("Tu ID (seudónimo, p. ej. CW07)", key="revisor")
    sede = st.selectbox("Tu sede (OficinaACNUR)", sedes(con), index=None,
                        placeholder="Escoge tu sede", key="sede")
    n_pend = n_rev = 0
    if sede:
        cond, p = filtro_sede(sede)
        n_pend = con.execute(f"SELECT COUNT(*) FROM casos WHERE uncertainty_pct > 0 AND {cond}", p).fetchone()[0]
        n_rev = con.execute(f"SELECT COUNT(*) FROM casos WHERE uncertainty_pct < 0 AND {cond}", p).fetchone()[0]
    st.markdown('<span class="cx-side-label">Navegación</span>', unsafe_allow_html=True)
    vista = st.radio("Navegación", ["cola", "revisados"], key="vista", label_visibility="collapsed",
                     format_func=lambda v: ":material/inbox: Cola de casos" if v == "cola"
                     else ":material/check_circle: Casos revisados")  # static labels: dynamic ones reset the radio
    minimo = st.slider("Uncertainty mínima", 0.0, 100.0, 0.0, 0.5, key="minimo")
    total_sede = n_pend + n_rev
    pintar("sidebar_footer", pendientes=n_pend if sede else "—",
           revisados=f"{n_rev} / {total_sede}" if sede else "—")

pintar("topbar", revisor=revisor.strip() or "Sin identificar", sede=sede or "Sin sede")

aviso = st.session_state.pop("aviso", None)
if aviso:
    st.toast(aviso, icon=":material/check_circle:")


@st.dialog("Modificar recomendación", width="large")
def dialogo_modificar(caso_id, caso):
    veredicto = "EXCLUSION" if caso[REC] == "INCLUSION" else "INCLUSION"
    pintar("modal_head", caso_id=caso_id, mes=caso["month"], recomendacion=caso[REC], veredicto=veredicto)
    st.markdown('<span class="cx-req">CAMPO OBLIGATORIO</span>', unsafe_allow_html=True)
    nota = st.text_area("Nota: ¿por qué modificas la recomendación?", key="nota_mod", height=120,
                        placeholder="Explica la razón del cambio con base en los datos del caso…")
    st.caption("La nota queda guardada en la tabla de revisiones junto con el caso.")
    c1, c2 = st.columns(2)
    if c1.button("Cancelar", key="btn_cancelar", width="stretch"):
        st.rerun()
    if c2.button("Confirmar modificación", key="btn_confirmar_mod", icon=":material/send:", width="stretch"):
        if not nota.strip():
            st.error("La nota es obligatoria cuando modificas el caso.")
            return
        try:
            guardar_revision(caso_id, "Modificado", veredicto, nota, revisor, sede)
        except ValueError as e:
            st.error(str(e))
            return
        st.session_state["aviso"] = f"Caso {caso_id} modificado: {caso[REC]} → {veredicto}."
        st.session_state.pop("nota_mod", None)
        st.session_state.pop("caso_sel", None)
        st.rerun()


if not sede:
    st.info("Escoge tu sede en la barra lateral para ver los casos pendientes.", icon=":material/location_on:")

elif vista == "cola":
    cola = pendientes(con, minimo, sede)
    izq, der = st.columns([5, 7], gap="medium")

    with izq:
        with st.container(key="panel_cola"):
            pintar("queue_head", pendientes=len(cola))
            if cola.empty:
                st.caption("No hay casos pendientes con ese nivel de uncertainty.")
            else:
                ids = list(cola["caso_id"])
                if st.session_state.get("caso_sel") not in ids:
                    st.session_state["caso_sel"] = ids[0]
                paginas = max(1, -(-len(ids) // POR_PAGINA))
                pag = min(st.session_state.get("pag", 0), paginas - 1)
                for _, fila in cola.iloc[pag * POR_PAGINA:(pag + 1) * POR_PAGINA].iterrows():
                    cid = fila["caso_id"]
                    sel = cid == st.session_state["caso_sel"]
                    with st.container(key=("qsel_" if sel else "q_") + cid):
                        pintar("queue_item", sel="sel" if sel else "", caso_id=cid, mes=fila["month"],
                               nivel=banda(fila["uncertainty_pct"])[0], unc=f"{fila['uncertainty_pct']:.1f}")
                        if st.button(f"Abrir {cid}", key=f"abrir_{cid}"):
                            st.session_state["caso_sel"] = cid
                            st.rerun()
                if paginas > 1:
                    with st.container(key="pager"):
                        a, b, c = st.columns([1, 2, 1])
                        if a.button("", icon=":material/chevron_left:", key="prev", disabled=pag == 0):
                            st.session_state["pag"] = pag - 1
                            st.rerun()
                        b.caption(f"Página {pag + 1} de {paginas}")
                        if c.button("", icon=":material/chevron_right:", key="next", disabled=pag >= paginas - 1):
                            st.session_state["pag"] = pag + 1
                            st.rerun()

    with der:
        if not cola.empty:
            caso_id = st.session_state["caso_sel"]
            caso = cola.set_index("caso_id").loc[caso_id]
            clase, texto, color = banda(caso["uncertainty_pct"])
            with st.container(key="panel_caso"):
                pintar("case", caso_id=caso_id, nivel=clase, nivel_txt=texto, ring=color,
                       unc=f"{caso['uncertainty_pct']:.1f}", unc_int=f"{caso['uncertainty_pct']:.1f}",
                       mes=caso["month"], oficina=fmt(caso["OficinaACNUR"]) if sede != SIN_OFICINA else SIN_OFICINA,
                       recomendacion=caso[REC])
                with st.container(key="detalles"):
                    with st.expander("Ver detalles del caso", icon=":material/description:"):
                        for titulo, campos in GRUPOS.items():
                            filas = "".join(f"<tr><td>{html.escape(c)}</td><td>{html.escape(fmt(caso[c]))}</td></tr>"
                                            for c in campos)
                            st.markdown(f'<span class="cx-caps">{html.escape(titulo)}</span>'
                                        f'<table class="cx-details">{filas}</table>', unsafe_allow_html=True)
                with st.container(key="acciones"):
                    sin_id = not revisor.strip()
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("Modificar con nota", key="btn_modificar", icon=":material/block:",
                                     disabled=sin_id, width="stretch"):
                            dialogo_modificar(caso_id, caso)
                    with c2:
                        if st.button("Confirmar recomendación", key="btn_confirmar", icon=":material/verified:",
                                     disabled=sin_id, width="stretch"):
                            try:
                                guardar_revision(caso_id, "Confirmado", caso[REC], "", revisor, sede)
                            except ValueError as e:
                                st.error(str(e))
                            else:
                                st.session_state["aviso"] = f"Caso {caso_id} confirmado ({caso[REC]})."
                                st.session_state.pop("caso_sel", None)
                                st.rerun()
                    if sin_id:
                        st.caption("Escribe tu ID de revisor en la barra lateral para habilitar las acciones.")

else:  # revisados
    cond, p = filtro_sede(sede)
    rev = pd.read_sql_query(f"SELECT * FROM revisiones WHERE {cond} ORDER BY revision_id DESC", con, params=p)
    with st.container(key="panel_hist"):
        pintar("kpis", total=len(rev), confirmadas=int((rev["accion"] == "Confirmado").sum()),
               modificadas=int((rev["accion"] == "Modificado").sum()))
        st.dataframe(rev, hide_index=True, width="stretch")
        if len(rev):
            st.download_button("Descargar revisiones (CSV)", rev.to_csv(index=False).encode("utf-8-sig"),
                               "revisiones.csv", "text/csv", icon=":material/download:")
