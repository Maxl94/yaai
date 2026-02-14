# Drift Detection Guide

## What Is Drift?

Drift means the data your model sees in production has changed compared to what it was trained on (or compared to a previous time period). If a model was trained on customers aged 20–50 and suddenly starts receiving data for ages 60–80, the input distribution has "drifted." The model's predictions may become unreliable.

There are two types:
- **Data drift** (covariate shift) — the input features changed
- **Prediction drift** — the model's output distribution changed (may indicate the model is behaving differently)

Both are detected the same way: compare two distributions and measure how different they are.

---

## Drift Metrics for Numerical Data

### PSI (Population Stability Index)

**What it does**: Splits both distributions into buckets, then compares the proportion of data in each bucket.

**Visual intuition**:

```
Reference distribution (training data):
  Bucket:   18-25   25-35   35-45   45-55   55-65
  Count:     500    1200     800     400     100
  Percent:   17%     40%     27%     13%      3%
            ██
            ██  ██
            ██  ██  ██
            ██  ██  ██  ██
            ██  ██  ██  ██  ██

Current inference data:
  Bucket:   18-25   25-35   35-45   45-55   55-65
  Count:     200     600     700     800     200
  Percent:    8%     24%     28%     32%      8%
                            ██
                    ██  ██  ██
            ██  ██  ██  ██  ██
            ██  ██  ██  ██  ██

PSI per bucket:
  Bucket    Ref%    Curr%   Contribution
  18-25     17%      8%     0.041  ← fewer young users
  25-35     40%     24%     0.058  ← big drop
  35-45     27%     28%     0.000  ← stable
  45-55     13%     32%     0.089  ← big increase
  55-65      3%      8%     0.025  ← more older users
                            ─────
  Total PSI:                0.213  → DRIFT DETECTED (> 0.2)
```

**Formula**: `PSI = Σ (current% - reference%) × ln(current% / reference%)`

**Interpretation scale**:
```
  0.0                0.1                0.2               0.5+
   ├──── No drift ────┤── Moderate drift ─┤── Significant ──┤── Major ──→
   │  distributions    │  worth monitoring  │  action needed  │  broken
   │  are similar      │                    │                 │
```

**Why we use it**: Simple, interpretable, industry standard in credit scoring and insurance. Each bucket's contribution tells you *where* the shift happened, not just *that* it happened.

---

### KS Test (Kolmogorov-Smirnov)

**What it does**: Compares the cumulative distribution functions (CDFs) of two datasets and finds the maximum vertical distance between them.

**Visual intuition**:

```
Cumulative Distribution Functions:

100% ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐
 90%                                          ╱──── Reference
 80%                                    ╱────╱
 70%                              ╱────╱
 60%                        ╱────╱ ←── max distance = KS statistic
 50%                  ╱──╱─╱    ╱
 40%              ╱──╱     ╱───╱──── Current
 30%          ╱──╱    ╱───╱
 20%      ╱──╱   ╱───╱
 10%  ╱──╱  ╱───╱
  0% ╱────╱
     18   25   35   45   55   65   75
                    age →
```

**Output**: A statistic (0–1) and a p-value.
- KS statistic = the maximum distance between the two CDFs
- p-value = probability of seeing this distance if the distributions were actually the same

**Interpretation**:
```
  p-value > 0.05  →  No significant drift (can't reject "same distribution")
  p-value < 0.05  →  Statistically significant drift
  p-value < 0.01  →  Highly significant drift
```

**Why we use it**: Non-parametric (no assumptions about distribution shape), well-understood statistically, gives a p-value for significance. Good complement to PSI — PSI tells you *how much* drift, KS tells you if it's *statistically significant*.

---

## Drift Metrics for Categorical Data

### Chi-Squared Test

**What it does**: Compares observed category frequencies against expected frequencies and measures whether the difference is statistically significant.

**Visual intuition**:

```
Reference (expected):               Current (observed):
  west:     30%  ████████            west:     22%  ██████
  central:  45%  ████████████        central:  43%  ███████████
  east:     25%  ███████             east:     35%  █████████
                                                    ↑ shift toward east

Chi-squared calculation:
  Category   Expected%   Observed%   Contribution
  west       30%         22%         (22-30)²/30 = 2.13
  central    45%         43%         (43-45)²/45 = 0.09
  east       25%         35%         (35-25)²/25 = 4.00
                                     ─────
  χ² statistic:                      6.22
  p-value:                           0.045  → DRIFT (< 0.05)
```

**Interpretation**: Same as KS — if p-value < 0.05, the distributions are significantly different.

**Why we use it**: Standard test for categorical data, widely understood, available in scipy.

---

### Jensen-Shannon Divergence (JSD)

**What it does**: Measures the similarity between two probability distributions. It's a symmetric version of KL divergence.

**Visual intuition**:

```
Distribution A:  west=30%  central=45%  east=25%
Distribution B:  west=22%  central=43%  east=35%

Step 1: Compute midpoint M = average of A and B
         M:      west=26%  central=44%  east=30%

Step 2: Compute KL divergence of A from M, and B from M
         KL(A||M) = 0.012
         KL(B||M) = 0.014

Step 3: JSD = (KL(A||M) + KL(B||M)) / 2 = 0.013

Interpretation:
  0.0                    0.1                    0.5           1.0
   ├──── Identical ───────┤──── Some drift ──────┤──── Very ───┤
   │  distributions       │                      │  different  │
```

**Why we use it**: Symmetric (unlike KL divergence), bounded between 0 and 1, works well for distributions with few categories. Better behaved than chi-squared when some categories have very small counts.

---

## Which Metric for Which Data Type

| Data type | Default metric | Alternative | When to use the alternative |
|---|---|---|---|
| Numerical | **PSI** | KS Test | When you need statistical significance (p-value) rather than a magnitude score |
| Categorical | **Chi-Squared** | JSD | When categories have very small counts (chi-squared can be unreliable with <5 expected counts per category) |

You can override the default metric per field when defining your schema.

---

## Handling Non-Tabular Models

The built-in drift metrics work on numerical and categorical distributions. If you're monitoring models that work with images, audio, text, or embeddings, extract features before sending inference data.

**Examples**:

| Model type | What to send as inference data |
|---|---|
| Image classifier | Image metadata (width, height, brightness) + prediction |
| Audio model | Duration, sample rate, SNR + prediction |
| LLM / text model | Prompt length, token count, latency + completion length |

These extracted features are standard numerical and categorical values, so all drift metrics and dashboards work out of the box.

```json
{
  "inputs": {
    "prompt_length": 142,
    "token_count": 38,
    "model_name": "gpt-4"
  },
  "outputs": {
    "completion_tokens": 256,
    "latency_ms": 1200
  }
}
```
