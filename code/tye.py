import pandas as pd
import numpy as np

df = pd.read_csv('/Users/gdb/Downloads/Data_Science/3rd_semester/Code_Goblins_UNHCR/Data/S8.synthetic_cashy_sample.csv')

# which direction does the score run?
"""print(df.groupby("EligibilityTarget")["FinalScore"].describe())"""

# threshold chosen so the AI includes the same share as the recorded decisions
include_rate = (df["EligibilityTarget"] == "INCLUSION").mean()   # about 0.22
threshold = df["FinalScore"].quantile(1 - include_rate)
df["ai_recommendation"] = np.where(df["FinalScore"] >= threshold, "INCLUSION", "EXCLUSION")

"""print("threshold:", round(threshold, 1))
print(pd.crosstab(df["EligibilityTarget"], df["ai_recommendation"]))
print("AI accuracy:", (df["ai_recommendation"] == df["EligibilityTarget"]).mean())
"""
# Add Uncertainty % to the logic
from audit.reliance import make_placeholder_ai

data = make_placeholder_ai(df, scale=0.6, seed=1)

data["cell"] = np.select(
    [(data["ai_recommendation"] == "INCLUSION") & (data["EligibilityTarget"] == "EXCLUSION"),
     (data["ai_recommendation"] == "EXCLUSION") & (data["EligibilityTarget"] == "INCLUSION")],
    ["wrongly_include", "wrongly_exclude"], default="AI_right")

from audit.reliance import build_queues

caseworkers = data["CaseworkerID"].dropna().unique()
queues = build_queues(data, caseworkers)
print(queues.groupby("CaseworkerID").size().describe())   # should be 20 for everyone
queues.to_csv("Data/queues.csv", index=False)

#print(pd.crosstab(data["OficinaACNUR"], data["cell"]))

"""print(pd.crosstab(data["EligibilityTarget"], data["ai_recommendation"]))
print("AI accuracy:", (data["ai_recommendation"] == data["EligibilityTarget"]).mean())
print(df["Uncertainty %"].describe())

wrong = data["ai_recommendation"] != data["EligibilityTarget"]
print("offices:", data["OficinaACNUR"].nunique())
print(wrong.groupby(data["CaseworkerID"]).sum().describe())"""

from audit.reliance import decompose, cluster_bootstrap

# 1. check the mix inside each queue
data["ai_wrong"] = data["cell"] != "AI_right"
q = queues.merge(data[["caseID", "cell", "ai_wrong"]], on="caseID")
print(q.groupby("CaseworkerID")["cell"].value_counts().unstack().agg(["min", "max"]))

# 2. SIMULATED decisions on these queues (replace with the real ones later)
rng = np.random.default_rng(0)
p_cw = dict(zip(caseworkers, rng.beta(6, 2, len(caseworkers))))  # each person's tendency to catch a wrong AI
q["overrode"] = [bool(rng.random() < (p_cw[cw] if w else 0.03))
                 for cw, w in zip(q["CaseworkerID"], q["ai_wrong"])]
q["ai_wrong"] = q["ai_wrong"].astype(bool)

# 3. four boxes + honest intervals
print(decompose(q).round(1).to_string(index=False))
for box in ["correct_override", "over_reliance", "correct_accept", "under_reliance"]:
    r = cluster_bootstrap(q, box, cw_col="CaseworkerID")
    print(f"{box}: {r['pct']:.1f}% (cluster CI {r['ci_low']:.1f}-{r['ci_high']:.1f}, "
          f"{r['n_caseworkers']} caseworkers)")

# 4. does the type of mistake matter?
print(q.groupby("cell")["overrode"].mean().round(2))

print(data["Uncertainty %"].max())

# full table, for the audit only (contains the hidden recorded decision)
data.to_csv("Data/audit_ground_truth.csv", index=False)

# what the dashboard may read: no recorded decision, no error labels
show = data.drop(columns=["EligibilityTarget", "Elegibilidad", "cell", "ai_wrong", "Uncertainty %"])
show.to_csv("Data/dashboard_cases.csv", index=False)