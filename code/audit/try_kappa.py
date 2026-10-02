from reliance import power_sim

print("30 people x 10 cases:", power_sim(30, 10, kappa=3))
print("30 people x 20 cases:", power_sim(30, 20, kappa=3))
print("60 people x 10 cases:", power_sim(60, 10, kappa=3))