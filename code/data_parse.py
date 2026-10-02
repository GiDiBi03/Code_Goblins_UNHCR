import pandas as pd
import numpy as np

data = pd.read_csv('Data/S8.synthetic_cashy_sample.csv')
# the script saves back into the same file: drop the columns it created on a previous run
data = data.drop(columns=[c for c in ['caseID', 'CaseworkerID', 'Uncertainty %', 'ai_recomandation'] if c in data.columns])

# uncertainty column from the toolkit: run `python code/uncertain_Toolkit.py` first
try:
    unc = pd.read_csv('Data/S8_with_uncertainty.csv')
except FileNotFoundError:
    raise SystemExit("Data/S8_with_uncertainty.csv not found. Run `python code/uncertain_Toolkit.py` first.")
if not (len(unc) == len(data)
        and (unc['month'].astype(str).values == data['month'].astype(str).values).all()
        and (unc['EligibilityTarget'].values == data['EligibilityTarget'].values).all()):
    raise SystemExit("Data/S8_with_uncertainty.csv does not line up with the S8 rows (month / EligibilityTarget).")
data["Uncertainty %"] = unc["Uncertainty %"].values

# handle missing values and NaNs
na_detection = data.isna().sum()
missing = na_detection[na_detection > 0]

# create 'ai_recomandation' (low / medium / high from FinalScore)
data["ai_recomandation"] = pd.qcut(data["FinalScore"], q=3, labels=["low", "medium", "high"])

# add caseID
values = list(range(1,len(data)+1))
data.insert(0, 'caseID', values)
# print(data["caseID"])

# create caseworkersID
# print(data[data['OficinaACNUR']== 'foten'])
# Create unique caseworkers per office (8 IDs per office)
offices = ['sotap', 'foten', 'pcr_cdmx', 'fupal', 'fomon', 'futij', 'fusal']
ids = [f'#{i:03d}' for i in range(1, 1901)]  # ['#001', '#002', ..., '#1900']

# Map each office to a distinct group of 8 IDs
np.random.seed(42)  # Optional: for reproducible results
office_caseworkers = {
    office: list(np.random.choice(ids, size=8, replace=False))
    for office in offices
}

# 2. Function to map a caseworker ID based on the row's office
def assign_caseworker(office):
    if pd.isna(office) or office not in office_caseworkers:
        return np.nan
    return np.random.choice(office_caseworkers[office])

# 3. Generate the values and insert as the second column (index 1)
caseworker_col = data['OficinaACNUR'].apply(assign_caseworker)
data.insert(1, 'CaseworkerID', caseworker_col)

# save AFTER all columns have been created
data.to_csv('Data/S8.synthetic_cashy_sample.csv', index=False)
print(pd.read_csv('Data/S8.synthetic_cashy_sample.csv').columns.tolist())