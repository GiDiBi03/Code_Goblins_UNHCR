"""Check against the reference values in Annex II of the challenge."""
import pandas as pd
from reliance import decompose

def build(n_wrong, wrong_overrode, n_right, right_overrode):
    # Makes a fake table: n_wrong cases where the AI was wrong,
    # of which wrong_overrode were overridden, and so on.
    return pd.DataFrame(
        [{"ai_wrong": True,  "overrode": i < wrong_overrode} for i in range(n_wrong)] +
        [{"ai_wrong": False, "overrode": i < right_overrode} for i in range(n_right)])

# Plain AI arm: 25/26 correct override, 0/26 under-reliance
plain = decompose(build(26, 25, 26, 0))
# Statements arm: 24/36 correct override, 0/36 under-reliance
stmts = decompose(build(36, 24, 36, 0))

print("PLAIN\n", plain.round(1).to_string(index=False))
print("\nSTATEMENTS\n", stmts.round(1).to_string(index=False))

def close(a, b, tol=0.2):
    return abs(a - b) <= tol

p = plain.set_index("box")
s = stmts.set_index("box")
assert close(p.loc["correct_override", "ci_low"], 81.1)
assert close(p.loc["correct_override", "ci_high"], 99.3)
assert close(s.loc["correct_override", "ci_low"], 50.3)
assert close(s.loc["correct_override", "ci_high"], 79.8)
assert close(s.loc["over_reliance", "ci_low"], 20.2)
assert close(s.loc["over_reliance", "ci_high"], 49.7)
assert close(s.loc["correct_accept", "ci_low"], 90.4)
print("\nAll checks match Annex II.")