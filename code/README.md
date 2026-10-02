# code

Python part of the pipeline: attach the Toolkit's uncertainty to the S8 cases, load them into SQLite, review them in a Streamlit app, and read the reviews from Power BI. Run every command from the **repository root**.

## Pipeline

| Step | Command / file | Output |
|---|---|---|
| 0. Uncertainty | `python code/uncertain_Toolkit.py` | `Data/S8_with_uncertainty.csv`: the S8 + `Uncertainty %` (= `uncertainty` × 100 from `Toolkit/uncertainty_results.csv`, joined by row). `--run-toolkit` compiles and runs `Toolkit/uncertainty.cpp` first (needs `g++`) |
| 1. Prepare data | `python code/data_parse.py` | Adds `caseID` (1…1900), `CaseworkerID` (8 IDs per office, randomly assigned to that office's cases; none for the 21 cases without office), `ai_recomandation` (low / medium / high = FinalScore tercile) and `Uncertainty %` to `Data/S8.synthetic_cashy_sample.csv` (in place; re-running it recomputes the same columns) |
| 2. Database | `python code/create_db.py --reset` | `code/cashy.db` with `casos` (`caso_id` = C + caseID) and an empty `revisiones` |
| 3. Review | `streamlit run code/app.py` | Each saved review goes to `revisiones` |
| 4. Analysis | `PowerBI/CachyBI.pbix` | Reads `cashy.db` |

```bash
pip install -r requirements.txt
python code/uncertain_Toolkit.py
python code/data_parse.py
python code/create_db.py --reset          # (re)creates code/cashy.db; existing reviews are deleted
streamlit run code/app.py                 # http://localhost:8501
```

**Uncertainty:** `data_parse.py` takes `Uncertainty %` from `Data/S8_with_uncertainty.csv` (written by `uncertain_Toolkit.py`) and stops if that file is missing or its rows do not line up (month / EligibilityTarget). The C++ program in `Toolkit/` is only compiled and run with `uncertain_Toolkit.py --run-toolkit`; a build on Windows/Linux can give different values than the committed macOS results.

## Files

| File | Purpose |
|---|---|
| `uncertain_Toolkit.py` | Step 0: joins the Toolkit uncertainty to the S8 rows |
| `data_parse.py` | Step 1: adds caseID, CaseworkerID, ai_recomandation and the uncertainty from step 0 |
| `create_db.py` | Step 2: builds `cashy.db`. Stops if `caseID`, `CaseworkerID`, `ai_recomandation` or `Uncertainty %` is missing, or an uncertainty is ≤ 0 |
| `app.py` | Step 3: Streamlit blind-review app (English UI): office → caseworker dropdown, FinalScore + AI recommendation, Include / Exclude. Styling comes from `static/style.css`, `templates/*.html` and `.streamlit/config.toml` |
| `audit/reliance.py` | Override-audit helpers: `select_cases` (balanced test set by AI right/wrong and error direction), `make_placeholder_ai` (placeholder AI for testing), `wilson_ci`, `decompose` (correct override / over-reliance / correct acceptance / under-reliance), `cluster_bootstrap` (CI resampling caseworkers) and `power_sim` |
| `audit/test_reliance.py` | Checks `decompose` against the reference values of the challenge's Annex II |
| `audit/try_*.py` | Examples for the functions above |
| `.streamlit/config.toml` | Copy of the root theme, so the app stays light when started from inside `code/` |

## Database (`cashy.db`)

### `casos`
All S8 columns, plus:

- **`caso_id`**: `C0001` … `C1900`.
- **`uncertainty_pct`**: 0–100. A positive value means the case is pending; a negative one means it was reviewed. The absolute value is the original uncertainty.

### `revisiones`
One row per review. It holds every `casos` column except `uncertainty_pct`, plus:

- `revision_id`
- `uncertainty_original`
- `EligibilityTarget2`: the caseworker's **blind** decision (`INCLUSION` / `EXCLUSION`)
- `nota`: optional note
- `revisor`
- `sede_revisor`
- `fecha_revision`

A save writes the review row and flips the sign of `uncertainty_pct` in `casos` in a single transaction. If the same case is saved twice, the second save is rejected.

`EligibilityTarget2 ≠ EligibilityTarget` marks a **disagreement** between the blind review and the recorded decision. The "Reviewed cases" view counts and lists them. The old `accion` and `decision_overriden` columns no longer exist; a database with that layout must be recreated with `--reset`.

## Blind review in the app
- `FinalScore` is the score produced by Cashy. `EligibilityTarget` is the final recorded decision.
- The user picks the office, then a caseworker from the `CaseworkerID`s assigned to that office (the 21 cases without office have no caseworker, so they cannot be reviewed). The selected caseworker is stored in `revisor`.
- The case screen shows the uncertainty %, the `FinalScore` with its `ai_recomandation` (low / medium / high) and the household and scorecard fields. It **never** shows `EligibilityTarget` or `Elegibilidad` (which encodes the same decision). Both stay in the database for the comparison.
- The caseworker can write an optional note, then presses **Exclude** (red) or **Include** (green). The case moves to "Reviewed cases".
- The interface is in English.

## Uncertainty colours in the app
The colour bands are percentiles of all cases, not fixed values, so they keep working whatever the uncertainty source and scale:

| Band | Rule |
|---|---|
| High (red) | ≥ 90th percentile |
| Medium (gold) | ≥ 60th percentile |
| Low (blue) | below that |

The cut-offs are computed from `|uncertainty_pct|` over all cases, so they do not move as cases get reviewed. They are shown under the slider in the sidebar. To change them, edit `PCT_HIGH` / `PCT_MEDIUM` at the top of `app.py`.

## Connecting Power BI
The `.pbix` must not contain anyone's local path (the repo is public, and it has to work on every teammate's computer). Power BI cannot use a path relative to the `.pbix`, so the database location comes from the environment variable **`CASHY_DB`**. The Streamlit app reads the same variable (if it is not set, the app falls back to `code/cashy.db` next to `app.py`).

### 1. Set `CASHY_DB` once per computer
Use the full path to `code/cashy.db` inside **your** copy of the repo.

- **Windows** (PowerShell or Command Prompt):
  ```
  setx CASHY_DB "C:\path\to\Code_Goblins_UNHCR\code\cashy.db"
  ```
  `setx` saves it permanently for your user, but only programs opened **afterwards** see it.
- **macOS / Linux**: add this line to `~/.zshrc` (macOS) or `~/.bashrc` (Linux), then open a new terminal:
  ```
  export CASHY_DB="/path/to/Code_Goblins_UNHCR/code/cashy.db"
  ```

Check it in a **new** terminal: `echo %CASHY_DB%` (Command Prompt), `$env:CASHY_DB` (PowerShell) or `echo $CASHY_DB` (macOS / Linux).

### 2. Restart Power BI
Close Power BI Desktop completely and open it again, so it picks up the new variable.

### 3. Point the queries at the variable (only needed once, then commit the `.pbix`)
1. Open `PowerBI/CachyBI.pbix` → **Home → Transform data**.
2. In the Queries pane, select the `casos` query → in **Applied Steps**, click **Source** → replace the formula in the formula bar with:
   ```
   = Python.Execute("import os, sqlite3, pandas as pd#(lf)db = os.environ.get(""CASHY_DB"", """")#(lf)if not os.path.isfile(db): raise FileNotFoundError(""Set the CASHY_DB environment variable to the full path of code/cashy.db"")#(lf)con = sqlite3.connect(db)#(lf)revisiones = pd.read_sql_query(""SELECT * FROM revisiones"", con)#(lf)casos = pd.read_sql_query(""SELECT * FROM casos"", con)#(lf)con.close()")
   ```
   (If the formula bar is hidden: **View → Formula Bar**.) Leave the next step (Navigation) as it is.
3. Do the same for the `revisiones` query.
4. If Power BI asks about privacy levels or permission to run the script, accept.
5. **Home → Close & Apply**, then **Refresh**, then save the `.pbix`.

Once the `.pbix` with this formula is committed, teammates only need steps 1 and 2.

### Troubleshooting
- **`FileNotFoundError: Set the CASHY_DB environment variable...`**: the variable is missing or points to a file that doesn't exist. Check the path, make sure you ran `python code/create_db.py --reset`, and restart Power BI.
- **Python script errors**: Power BI uses the Python set in **File → Options and settings → Options → Python scripting**; that Python needs `pandas` installed.

The database runs in WAL mode, so you can Refresh in Power BI while the app is open. Keep the repository out of Dropbox/OneDrive while the app is running, because syncing a live SQLite file can create conflicted copies.

**Git history:** older commits of `CachyBI.pbix` and `Guia_Dashboards_CachyBI.html` still contain the old personal path. Changing the current files doesn't remove it from history; that needs a history rewrite (e.g. `git filter-repo`) and a force push.

## Notes
- The data is synthetic (S8). The uncertainty is a proxy model of `EligibilityTarget`, not the probability that an AI is wrong (see `Toolkit/README.md`).
- `EligibilityTarget` is the operation's recorded determination, not ground truth about a household's need.
