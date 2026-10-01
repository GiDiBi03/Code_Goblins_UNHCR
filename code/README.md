# code

Streamlit app and SQLite database for reviewing high-uncertainty cases (pipeline steps 1–5).
Run all commands from the **repository root**.

## Files
| File | Purpose |
|---|---|
| `data_parse.py` | Adds the simulated `Uncertainty %` column to `Data/S8.synthetic_cashy_sample.csv` (seed 42, uniform 0–100, 2 decimals). **Overwrites the CSV in place.** |
| `create_db.py` | Reads that CSV and builds `cashy.db` with the `casos` table and an empty `revisiones` table. Stops if `Uncertainty %` is missing or has a value ≤ 0. |
| `app.py` | Streamlit review app. The interface is in Spanish. |

## Database (`cashy.db`)

### `casos`
All 26 S8 columns, plus:

| Column | Content |
|---|---|
| `caso_id` | `C0001` … `C1900` |
| `uncertainty_pct` | `Uncertainty %` from the CSV. **Positive = pending, negative = reviewed** (the absolute value is the original uncertainty) |

### `revisiones`
One row per review. It holds every `casos` column except `uncertainty_pct`, plus:

| Column | Content |
|---|---|
| `revision_id` | Auto-increment key |
| `uncertainty_original` | Uncertainty before the review |
| `accion` | `Confirmado` or `Modificado` |
| `decision_overriden` | Final verdict: `INCLUSION` / `EXCLUSION`. Equals `EligibilityTarget` when confirmed |
| `nota` | Required when modified, optional when confirmed |
| `revisor` | Pseudonymous caseworker ID |
| `sede_revisor` | Office the caseworker selected |
| `fecha_revision` | `YYYY-MM-DD HH:MM:SS` |

### What happens when "Guardar revisión" is pressed
The following runs in one transaction, so either everything succeeds or nothing changes:

1. The case is copied to `revisiones` together with the review fields.
2. In `casos`, `uncertainty_pct` is set to `-uncertainty_pct`, so the case leaves the queue.

If two people save the same case, the second one gets a warning and nothing is duplicated.

**App rules**
- No case is shown until an office is selected. The 21 cases with no office appear under **(sin oficina)**.
- The action buttons stay disabled until a reviewer ID is entered.
- **Confirmar recomendación** saves the case as `Confirmado`, with the same `EligibilityTarget` and no note.
- **Modificar con nota** opens a dialog. The final verdict is the opposite of `EligibilityTarget`, and the note is required.
- **Casos revisados** shows the reviews for the selected office.

**Look and feel.** The UI follows `web_pages.html`:
- CSS lives in `static/style.css`.
- The HTML snippets live in `templates/*.html`. They use `string.Template` with `${var}` placeholders, and every value is HTML-escaped.
- Theme colours are set in `.streamlit/config.toml`, which only takes effect when Streamlit is started from the repository root.
- Fonts (Work Sans, Source Sans 3) load from Google Fonts. Without internet access, the browser falls back to its default sans-serif font. Icons come from Streamlit's bundled Material Symbols font, so they work offline.
- `Elegibilidad` (the six-value detail) is stored but not shown on screen.

## Connecting Power BI

### Option A – Python script (no driver needed)
1. In Power BI, go to File → Options and settings → Options → **Python scripting**. Point it to a Python installation that has `pandas` and `matplotlib` (`pip install pandas matplotlib`).
2. Go to Home → Get data → More… → **Python script** and paste the script below. Replace the path with the full path to `cashy.db` (right-click the file → "Copy as path").
   ```python
   import sqlite3, pandas as pd
   con = sqlite3.connect(r"C:\path\to\repo\code\cashy.db")
   revisiones = pd.read_sql_query("SELECT * FROM revisiones", con)
   casos = pd.read_sql_query("SELECT * FROM casos", con)
   con.close()
   ```
3. Select `revisiones` (and `casos` if needed) → Transform data.
4. Set the column types:
   - `fecha_revision` → Date/Time
   - `month` → Text

### Option B – ODBC
1. Install the 64-bit **SQLite3 ODBC Driver** (`sqliteodbc_w64.exe`, from ch-werner.de/sqliteodbc).
2. Go to Get data → **ODBC** → Advanced options and use this connection string:
   ```
   Driver={SQLite3 ODBC Driver};Database=C:\path\to\repo\code\cashy.db
   ```

The database runs in WAL mode, so you can **Refresh** in Power BI while the app is open.

> Keep the repository outside Dropbox/OneDrive while the app is running. Syncing a live SQLite file can create conflicted copies.
