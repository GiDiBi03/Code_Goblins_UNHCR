import numpy as np
import pandas as pd
from reliance import decompose, cluster_bootstrap

rng = np.random.default_rng(0)
rows = []
for cw in range(30):
    p = rng.beta(6, 2)              # this person's own tendency to override
    for case in range(10):
        wrong = case < 5
        rows.append({"caseworker_id": cw, "ai_wrong": wrong,
                     "overrode": rng.random() < (p if wrong else 0.03)})
sim = pd.DataFrame(rows)

print(decompose(sim).round(1).to_string(index=False))
print(cluster_bootstrap(sim, "correct_override"))