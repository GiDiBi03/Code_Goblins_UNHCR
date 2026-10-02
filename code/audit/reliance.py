import math
import pandas as pd
import numpy as np

def select_cases(df, ai_col="ai_recommendation", truth_col="EligibilityTarget",
                 n_per_cell=5, seed=0):
    """Balanced test set: AI right/wrong, split by direction of the error."""
    cells = {
        "agree_include":   (df[ai_col] == "INCLUSION") & (df[truth_col] == "INCLUSION"),
        "agree_exclude":   (df[ai_col] == "EXCLUSION") & (df[truth_col] == "EXCLUSION"),
        "wrongly_include": (df[ai_col] == "INCLUSION") & (df[truth_col] == "EXCLUSION"),
        "wrongly_exclude": (df[ai_col] == "EXCLUSION") & (df[truth_col] == "INCLUSION"),
    }
    parts = []
    for name, mask in cells.items():
        pool = df[mask]
        if len(pool) < n_per_cell:
            raise ValueError(f"{name}: only {len(pool)} cases available, need {n_per_cell}")
        parts.append(pool.sample(n_per_cell, random_state=seed).assign(cell=name))
    out = pd.concat(parts).reset_index(drop=True)
    out["ai_wrong"] = out["cell"].str.startswith("wrongly")
    return out

def make_placeholder_ai(df, truth_col="EligibilityTarget",
                        unc_col="Uncertainty %", scale=1.0, seed=0):
    """PLACEHOLDER AI. Flips the recorded decision with prob = Uncertainty%/100 * scale.
    Replace this with real model predictions later; select_cases only needs
    an 'ai_recommendation' column of INCLUSION / EXCLUSION."""
    rng = np.random.default_rng(seed)
    p_wrong = (df[unc_col] / 100 * scale).clip(0, 1)
    flip = rng.random(len(df)) < p_wrong
    opposite = df[truth_col].map({"INCLUSION": "EXCLUSION", "EXCLUSION": "INCLUSION"})
    out = df.copy()
    out["ai_recommendation"] = opposite.where(flip, df[truth_col])
    out["p_wrong"] = p_wrong
    return out

def wilson_ci(k, n, z=1.96):
    """Wilson 95% CI for a proportion k/n. Returns (low, high) in 0-1."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (centre - half, centre + half)

def decompose(df):
    # df: one row per assessment, two boolean columns:
    #   ai_wrong : AI contradicts the operation's recorded determination
    #   overrode : caseworker overrode the AI
    wrong = df[df["ai_wrong"]]
    right = df[~df["ai_wrong"]]
    boxes = {
        "correct_override": (int(wrong["overrode"].sum()), len(wrong)),
        "over_reliance":    (int((~wrong["overrode"]).sum()), len(wrong)),
        "correct_accept":   (int((~right["overrode"]).sum()), len(right)),
        "under_reliance":   (int(right["overrode"].sum()), len(right)),
    }
    rows = []
    for name, (k, n) in boxes.items():
        lo, hi = wilson_ci(k, n)
        rows.append({"box": name, "k": k, "n": n,
                     "pct": 100 * k / n if n else float("nan"),
                     "ci_low": 100 * lo, "ci_high": 100 * hi})
    return pd.DataFrame(rows)

# resampling whole caseworkers instead of individual decisions (interval widens when ppl behave differently from each other)
def cluster_bootstrap(df, box="correct_override", cw_col="caseworker_id",
                      n_boot=5000, seed=0):
    """Bootstrap CI for one box, resampling caseworkers (not decisions)."""
    rng = np.random.default_rng(seed)
    wrong_box = box in ("correct_override", "over_reliance")
    sub = df[df["ai_wrong"]] if wrong_box else df[~df["ai_wrong"]]
    hit = sub["overrode"] if box in ("correct_override", "under_reliance") else ~sub["overrode"]
    per = (pd.DataFrame({"k": hit.astype(int), "cw": sub[cw_col]})
             .groupby("cw")["k"].agg(["sum", "count"]))
    k, n = per["sum"].to_numpy(), per["count"].to_numpy()
    m = len(per)
    idx = rng.integers(0, m, size=(n_boot, m))
    rates = k[idx].sum(axis=1) / n[idx].sum(axis=1)
    lo, hi = np.percentile(rates, [2.5, 97.5]) * 100
    return {"box": box, "pct": 100 * k.sum() / n.sum(),
            "ci_low": lo, "ci_high": hi, "n_caseworkers": m}

# simulate two groups of caseworkers where second gropup's correct-override rate is lower by "drop" (how often a per-person test detects the difference)
from scipy import stats

def power_sim(n_cw, n_cases, base=0.80, drop=0.15, kappa=8,
              n_sims=2000, alpha=0.05, seed=0):
    """Share of simulated studies that detect the drop in correct overrides.
    n_cw    : caseworkers per group
    n_cases : AI-wrong cases each caseworker reviews
    base    : average correct-override rate in the control group
    drop    : how many points lower the other group is (0.15 = 15 points)
    kappa   : how similar people are to each other (small = very different people)
    """
    rng = np.random.default_rng(seed)
    mu_t = base - drop
    hits = 0
    for _ in range(n_sims):
        pc = rng.beta(base * kappa, (1 - base) * kappa, n_cw)    # each person's own rate
        pt = rng.beta(mu_t * kappa, (1 - mu_t) * kappa, n_cw)
        xc = rng.binomial(n_cases, pc) / n_cases                 # per-person override rate
        xt = rng.binomial(n_cases, pt) / n_cases
        if stats.ttest_ind(xc, xt, equal_var=False).pvalue < alpha:
            hits += 1
    return hits / n_sims

def build_queues(data, caseworkers, n_inc=6, n_exc=4, n_right=10, seed=0):
    """One planned queue per caseworker, drawn from all offices."""
    rng = np.random.default_rng(seed)
    quota = {"wrongly_include": n_inc, "wrongly_exclude": n_exc, "AI_right": n_right}
    pools = {c: data.loc[data["cell"] == c, "caseID"].to_numpy() for c in quota}
    rows = []
    for cw in caseworkers:
        ids = np.concatenate([rng.choice(pools[c], quota[c], replace=False) for c in quota])
        rng.shuffle(ids)
        for pos, cid in enumerate(ids):
            rows.append({"CaseworkerID": cw, "caseID": cid, "position": pos})
    return pd.DataFrame(rows)