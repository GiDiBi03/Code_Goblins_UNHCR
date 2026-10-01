import pandas as pd
from reliance import power_sim

# Sanity check: with NO real drop, "detection" should be about 5%
print("false-positive rate (drop=0):", power_sim(30, 10, drop=0.0))

rows = []
for n_cw in [20, 30, 50, 80, 120]:
    for n_cases in [5, 10, 20]:
        rows.append({"caseworkers": n_cw, "cases_each": n_cases,
                     "power": power_sim(n_cw, n_cases, drop=0.15)})
grid = pd.DataFrame(rows).pivot(index="caseworkers", columns="cases_each", values="power")
print(grid.round(2))