"""
Build the SQLite database for the Cashy review app (pipeline steps 2 and 5).

Input : Data/S8.synthetic_cashy_sample.csv AFTER running code/data_parse.py, i.e. with the
        columns caseID, CaseworkerID, "Uncertainty %" and ai_recomandation added by that script.
Output: code/cashy.db with two tables
  casos      - one row per household: all S8 columns + caso_id + uncertainty_pct
               ("Uncertainty %" from the CSV, renamed to be SQL-friendly)
  revisiones - empty; the Streamlit app appends one row per reviewed case, with the
               caseworker's blind decision in EligibilityTarget2 (INCLUSION / EXCLUSION)

Convention in `casos`:
  uncertainty_pct > 0  -> pending review
  uncertainty_pct < 0  -> already reviewed (absolute value = original uncertainty)
  An uncertainty of exactly 0 cannot be marked as reviewed (-0 == 0), so the
  script stops if the CSV contains any 0.

Usage (from the repository root):
  python code/data_parse.py
  python code/create_db.py              # creates code/cashy.db
  python code/create_db.py --reset      # deletes and recreates it (reviews are lost)
"""
import argparse
import os
import sqlite3

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_CSV = os.path.join(ROOT, "Data", "S8.synthetic_cashy_sample.csv")
DEFAULT_DB = os.path.join(HERE, "cashy.db")
UNCERTAINTY_COL = "Uncertainty %"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=DEFAULT_CSV, help="S8 CSV with the 'Uncertainty %%' column")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--reset", action="store_true", help="delete the database if it already exists")
    a = ap.parse_args()

    df = pd.read_csv(a.csv)
    if UNCERTAINTY_COL not in df.columns:
        raise SystemExit(f"'{UNCERTAINTY_COL}' not found in {a.csv}. Run `python code/data_parse.py` first.")
    if (df[UNCERTAINTY_COL] <= 0).any() or df[UNCERTAINTY_COL].isna().any():
        raise SystemExit(f"'{UNCERTAINTY_COL}' has values <= 0 or empty; every case needs a positive uncertainty.")

    if os.path.exists(a.db):
        if not a.reset:
            raise SystemExit(f"{a.db} already exists. Use --reset to recreate it (all reviews are lost).")
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(a.db + suffix):
                os.remove(a.db + suffix)

    df = df.rename(columns={UNCERTAINTY_COL: "uncertainty_pct"}).reset_index(drop=True)
    for col in ("caseID", "CaseworkerID", "ai_recomandation"):
        if col not in df.columns:
            raise SystemExit(f"'{col}' not found in {a.csv}. Run `python code/data_parse.py` first.")
    df.insert(0, "caso_id", [f"C{int(i):04d}" for i in df["caseID"]])   # C0001 ... from data_parse's caseID
    df["month"] = df["month"].astype(str)

    con = sqlite3.connect(a.db)
    con.execute("PRAGMA journal_mode=WAL")   # lets Power BI read while the app writes
    df.to_sql("casos", con, index=False)
    con.execute("CREATE UNIQUE INDEX ix_casos_id ON casos(caso_id)")

    # revisiones = every column of the case (except uncertainty_pct) + review columns
    info = con.execute("PRAGMA table_info(casos)").fetchall()
    cols = [f'"{c[1]}" {c[2] or "TEXT"}' for c in info if c[1] != "uncertainty_pct"]
    ddl = ("CREATE TABLE revisiones (\n  revision_id INTEGER PRIMARY KEY AUTOINCREMENT,\n  "
           + ",\n  ".join(cols)
           + ",\n  uncertainty_original REAL NOT NULL"
           + ",\n  EligibilityTarget2 TEXT NOT NULL CHECK (EligibilityTarget2 IN ('INCLUSION','EXCLUSION'))"
           + ",\n  nota TEXT"
           + ",\n  revisor TEXT NOT NULL"
           + ",\n  sede_revisor TEXT NOT NULL"
           + ",\n  fecha_revision TEXT NOT NULL\n)")
    con.execute(ddl)
    con.commit()

    n = con.execute("SELECT COUNT(*) FROM casos").fetchone()[0]
    print(f"OK {a.db}: casos = {n} rows, revisiones = 0 rows")
    con.close()


if __name__ == "__main__":
    main()
