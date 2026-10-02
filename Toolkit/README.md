# CSV audit and proxy uncertainty pipeline

This folder contains the existing rule-based audit program (`classify.cpp`) and a second-stage probabilistic **proxy** model (`uncertainty.cpp`). The proxy program does not replace the classifier. It preserves the anomaly/conflict rules as separate audit flags and adds out-of-fold probability estimates about the recorded reference class.

## Recommendation availability and mode

A repository search found no per-case `AIRecommendation` in the source, CSV headers, VS Code configuration, or other project files. The input CSV provides `EligibilityTarget`, which is the operation's recorded/reference determination, but does not provide an independent AI recommendation. `Elegibilidad` is another representation of that same determination and is not independent evidence.

The program therefore runs in **PROXY MODE**. It does not invent an AI recommendation or an `AIErrorLabel`; those output cells are intentionally empty. It predicts `EligibilityTarget` from the available input features. The field `proxy_uncertainty` is the calibrated probability that the proxy model's most likely class differs from the recorded reference determination:

- Fit `p = P(EligibilityTarget == INCLUSION | features)`.
- Predict `INCLUSION` if `p >= 0.5`; otherwise predict `EXCLUSION`.
- Set `proxy_uncertainty = min(p, 1 - p)`.

This is **not** a probability that an AI is wrong and does not reconstruct historical human overrides. To train a real AI-error model, add an independently produced per-case `AIRecommendation` column. Then define `AIErrorLabel = (AIRecommendation != EligibilityTarget)` and train against that label; do not substitute the anomaly/conflict rules.

The code is ready to switch to **REAL AI ERROR MODE** when a complete `AIRecommendation` column is supplied with `INCLUSION`/`EXCLUSION` values. In that mode it derives `AIErrorLabel` from the two independently supplied classes, trains on disagreement, and sets `uncertainty` to the calibrated out-of-fold AI-error probability. A present but incomplete/invalid recommendation column causes a clear error instead of silently falling back to proxy mode.

`EligibilityTarget` is the institution's recorded determination for this analysis, not objective truth about household need. The supplied dataset is synthetic and must not be treated as evidence of real-world model performance.

## Inputs and feature handling

Default input: `S8.synthetic_cashy_sample.csv` in the current working directory. An alternate CSV path can be passed as the first command-line argument.

Used predictors are the available raw/input fields:

- `month`, `OficinaACNUR`, `Demographics.HH.Head`, `Demographics.Language`, `Demographics.Profiles`, `Demographics.Documentation`
- `Needs_and_Coping.BasicNeeds`, `Needs_and_Coping.Housing`, `Needs_and_Coping.Neg.mechanism`, `Needs_and_Coping.Dependency`, `NumIntegrantes`
- `dependencyCategory`, `FemaleHeadedHousehold`, `CuidadorSolo`, `HablaEspanol`, `Analfabeta_si`
- `ScoreCOMAR_PIL`, `ScoreIntenciones`, `ScoreDuplicidad`

The source has no AI implementation documenting whether scorecard fields are AI predictions. They are treated as input/admin signals as listed in the supplied project request, with their own categorical encoding. `FinalScore`, `Demographics_Score`, `NeedsandCoping_Score`, `Vulnerability_Score`, and `Vulnerability_Category` are treated as reference scorecard outputs and excluded from predictors. `Elegibilidad` and `EligibilityTarget` are excluded from predictors to prevent target leakage. `FinalScore` and `EligibilityTarget` are read only for the existing audit rules and the reference label, respectively.

Missing categorical values become an explicit `MISSING_NOT_APPLICABLE` category. Numeric inputs are imputed with that column's mean after standardization; a separate missing indicator is included. In this implementation the means/scales and category dictionary are fitted once from the supplied CSV before the outer folds (without using labels), so the validation is label-held-out but uses transductive preprocessing. A stricter deployment evaluation should fit preprocessing inside each training fold. `ScoreCOMAR_PIL`, `ScoreIntenciones`, and `ScoreDuplicidad` are categorical signals: blank, zero, `-500`, `+500`, and each other numeric value are represented distinctly. These special values are never interpreted as ordinary magnitudes. Other categorical values unseen at transform time have an `UNKNOWN` bucket.

The fixed feature dictionary and numeric scaling are built from this supplied file without using labels. For a future deployment, fit and persist the preprocessing alongside the model using only its training data.

## Model and evaluation

The model is L2-regularized logistic regression trained with the standard sigmoid `p = 1/(1+exp(-z))`. Numeric inputs are standardized, categoricals are one-hot encoded, and missing numeric values get a missingness indicator. Platt logistic calibration is fitted using inner out-of-fold training predictions. Outer stratified folds generate a held-out calibrated prediction for each historical row; no row's outer prediction comes from a model trained on that row. A final calibrated model and weights are also produced for inspection/future work.

Metrics printed and written to `uncertainty_report.txt` describe prediction of the recorded reference class, not AI error. The report includes class counts, threshold-0.5 confusion matrix, ROC AUC, average-precision PR AUC, log loss, Brier score, and 10-bin expected calibration error. Random stratified cross-validation can still overstate performance when cases are related or time-dependent; the synthetic sample and its metrics do not establish real-world performance. The learned `feature_weights.csv` weights are log-odds coefficients after calibration; positive values increase the model's recorded-INCLUSION log odds. The report lists the largest absolute weights and per-case positive/negative log-odds contributions for the highest proxy-uncertainty cases. Contributions describe this proxy model, not AI-error causes.

The existing audit flags remain distinct:

- `anomaly_flag`: the prior anomaly heuristic is true.
- `conflict_flag`: the prior conflict heuristic is true.
- `AIErrorLabel`: empty because an independent AI recommendation is absent.
- `proxy_uncertainty`: proxy-model probability of disagreement with the recorded reference, as defined above.
- When a valid `AIRecommendation` input column is added, `AIErrorLabel` becomes `0`/`1`, `predicted_AIErrorProbability` and `uncertainty` contain out-of-fold AI-error risk, and proxy-only result columns are empty.

## Build, tests, and run

Run these commands from the project folder:

```sh
g++ -std=c++17 -O2 -Wall -Wextra -pedantic uncertainty.cpp -o uncertainty
./uncertainty --self-test
./uncertainty
```

The self-tests exercise CSV quoting and escaping, BOM handling, blank/missing values, missing-category and special-score encoding, recommendation/label comparison semantics (without fabricating a label in production), sigmoid range, logistic training, calibration, stratified folds, and CSV output writing.

The existing audit program remains independently buildable:

```sh
g++ -std=c++17 -Wall -Wextra -pedantic classify.cpp -o classify
./classify
```

## Generated files and columns

Running `uncertainty` writes these files in the current working directory:

- `uncertainty_results.csv`: one row per accepted CSV record, in source order.
- `feature_weights.csv`: final model's calibrated feature coefficients and intercept.
- `model_preprocessing.csv`: the numeric means/scales and categorical levels needed to interpret the final model's feature encoding.
- `uncertainty_report.txt`: validation metrics, model notes, weights, highest-risk proxy cases, and per-case feature contributions.

`uncertainty_results.csv` columns:

| Column | Meaning |
|---|---|
| `row_id` | One-based physical data-row number from the source CSV (header excluded). |
| `month` | Original month field. |
| `AIRecommendation` | Empty; no independent recommendation exists in the supplied project. |
| `EligibilityTarget` | Recorded/reference determination from the CSV. |
| `AIErrorLabel` | Empty; cannot be computed without an independent AI recommendation. |
| `proxy_predicted_reference_class` | OOF proxy model's predicted `INCLUSION` or `EXCLUSION` class. |
| `proxy_probability_of_reference_inclusion` | OOF calibrated probability of the recorded target being `INCLUSION`. |
| `proxy_uncertainty` | `min(p, 1-p)`, estimated chance the proxy class differs from the recorded reference. This is not AI-error risk. |
| `predicted_AIErrorProbability` | Empty in proxy mode; in real mode, calibrated probability that the supplied AI recommendation differs from `EligibilityTarget`. |
| `uncertainty` | The mode-specific probability: proxy class disagreement in proxy mode, AI-error probability in real mode. |
| `anomaly_flag` | Existing anomaly heuristic result (`1` true, `0` false). |
| `conflict_flag` | Existing conflict heuristic result (`1` true, `0` false). |

The CSV stays in source order; the human-readable report lists the highest `proxy_uncertainty` cases first. The input parser supports quoted commas and escaped quotes, but expects one CSV record per physical line (multiline quoted cells are not supported).
