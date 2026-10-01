import pandas as pd
import numpy as np

data = pd.read_csv('Data/S8.synthetic_cashy_sample.csv')


# Print the columns and categories
"""for col in data.columns:
    print(f"\n{col}:\n {data[col].unique()}\n They are {data[col].nunique()} categories")"""

# create a new column
unc_percent = np.random.default_rng(42)
data["Uncertainty %"] = unc_percent.uniform(0, 100, size=len(data)).round(2)
print(data.columns)

data.to_csv('Data/S8.synthetic_cashy_sample.csv', index=False)
print(pd.read_csv('Data/S8.synthetic_cashy_sample.csv').columns.tolist())

# handle missing values and NAN's
na_detection = data.isna().sum()
missing = na_detection[na_detection > 0]
print(missing)
print(missing[1])
