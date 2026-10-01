import pandas as pd
from reliance import make_placeholder_ai, select_cases

df = pd.read_csv("/Users/gdb/Downloads/Data_Science/3rd_semester/Code_Goblins_UNHCR/Data/S8.synthetic_cashy_sample.csv")
df = make_placeholder_ai(df, scale=0.5, seed=1)

print(pd.crosstab(df["Elegibilidad"], df["EligibilityTarget"]))
print(pd.crosstab(df["EligibilityTarget"], df["ai_recommendation"]))

test_set = select_cases(df, n_per_cell=5, seed=1)
print(test_set[["Elegibilidad", "ai_recommendation", "cell", "ai_wrong"]].to_string())