"""
Step 0 of the pipeline: attach the Toolkit's uncertainty to every case.

The Toolkit (../Toolkit/uncertainty.cpp) reads Toolkit/S8.synthetic_cashy_sample.csv and
writes Toolkit/uncertainty_results.csv with one row per case, in the same order, and a
column `uncertainty` in decimals (0-1). This script joins that column to the S8 rows by
row_id and writes Data/S8_with_uncertainty.csv, whose "Uncertainty %" column code/data_parse.py
then copies into Data/S8.synthetic_cashy_sample.csv.

The output column "Uncertainty %" is the Toolkit's `uncertainty` x 100 (e.g. 0.1878 -> 18.78),
so the app and Power BI keep working on a 0-100 scale.

Usage (from the repository root):
  python code/uncertain_Toolkit.py                 # use the existing Toolkit/uncertainty_results.csv
  python code/uncertain_Toolkit.py --run-toolkit   # compile (g++) and run the Toolkit first, then join

Note: the Toolkit shuffles its cross-validation folds with the C++ standard library, so a
build on macOS and a build on Windows/Linux can produce slightly different uncertainties.
Without --run-toolkit everyone uses the same committed CSV.
"""
import argparse
import os
import shutil
import subprocess
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLKIT = os.path.join(ROOT, "Toolkit")
SOURCE_CSV = os.path.join(TOOLKIT, "S8.synthetic_cashy_sample.csv")   # the Toolkit's input
RESULTS_CSV = os.path.join(TOOLKIT, "uncertainty_results.csv")        # the Toolkit's output
OUTPUT_CSV = os.path.join(ROOT, "Data", "S8_with_uncertainty.csv")


def run_toolkit():
    exe = os.path.join(TOOLKIT, "uncertainty.exe" if os.name == "nt" else "uncertainty")
    src = os.path.join(TOOLKIT, "uncertainty.cpp")
    gpp = shutil.which("g++")
    if gpp:  # always rebuild: a binary committed from another OS (e.g. macOS) will not run here
        print("Compiling Toolkit/uncertainty.cpp ...")
        subprocess.run([gpp, "-std=c++17", "-O2", src, "-o", exe], cwd=TOOLKIT, check=True)
    elif not os.path.exists(exe):
        sys.exit("g++ not found and no Toolkit executable for this system. "
                 "Install a C++ compiler or run without --run-toolkit to use the existing CSV.")
    print("Running the Toolkit ...")
    subprocess.run([exe], cwd=TOOLKIT, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-toolkit", action="store_true", help="compile and run Toolkit/uncertainty.cpp first")
    a = ap.parse_args()

    if a.run_toolkit:
        run_toolkit()
    if not os.path.exists(RESULTS_CSV):
        sys.exit(f"{RESULTS_CSV} not found. Run with --run-toolkit to generate it.")

    data = pd.read_csv(SOURCE_CSV)
    res = pd.read_csv(RESULTS_CSV)

    # The Toolkit keeps source order and numbers rows from 1: check that the rows really line up.
    if len(res) != len(data) or list(res["row_id"]) != list(range(1, len(data) + 1)):
        sys.exit("uncertainty_results.csv does not have one row per S8 row in source order.")
    if not ((res["month"].astype(str).values == data["month"].astype(str).values).all()
            and (res["EligibilityTarget"].values == data["EligibilityTarget"].values).all()):
        sys.exit("month/EligibilityTarget differ between the S8 file and the Toolkit results: wrong files?")
    if res["uncertainty"].isna().any() or (res["uncertainty"] <= 0).any():
        sys.exit("The Toolkit produced empty or zero uncertainties; every case needs a positive value.")

    data["Uncertainty %"] = (res["uncertainty"] * 100).round(2)
    data.to_csv(OUTPUT_CSV, index=False)
    u = data["Uncertainty %"]
    print(f"OK {OUTPUT_CSV}: {len(data)} rows · Uncertainty % from {u.min():.2f} to {u.max():.2f} (mean {u.mean():.2f})")


if __name__ == "__main__":
    main()
