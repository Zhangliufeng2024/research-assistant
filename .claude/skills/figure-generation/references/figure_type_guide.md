# Figure Type Selection Guide

Choose the right plot type for your data scenario.

---

## 1. Comparison — Bar Chart

**When to use:** Compare discrete categories or groups on a single metric.

**Required data:** One categorical column (x), one numeric column (y). Optional grouping column for clustered bars.

**Example command:**
```bash
python .claude/skills/figure-generation/scripts/plot_data.py benchmarks.csv \
  --type bar --x model --y accuracy --group dataset \
  --ylabel "Accuracy (%)" --title "Model Comparison" \
  -o figures/model_comparison.pdf
```

**Tips:**
- Use horizontal bars (`--type bar` with long category names automatically rotates).
- Use `--group` for side-by-side grouped bars.
- For stacked bars, ensure groups are mutually exclusive.

---

## 2. Comparison — Box Plot

**When to use:** Show distribution shape, median, quartiles, and outliers across groups.

**Required data:** One categorical column (x), one numeric column (y).

**Example command:**
```bash
python .claude/skills/figure-generation/scripts/plot_data.py experiment.csv \
  --type box --x treatment --y response \
  --ylabel "Response (units)" --title "Treatment Distributions" \
  -o figures/boxplot.pdf
```

**Tips:**
- Box plots are better than bar charts when distributions are skewed or have outliers.
- Overlaid jittered points show individual observations.

---

## 3. Correlation — Scatter Plot

**When to use:** Examine relationship between two continuous variables.

**Required data:** Two numeric columns (x, y).

**Example command:**
```bash
python .claude/skills/figure-generation/scripts/plot_data.py measurements.csv \
  --type scatter --x temperature --y pressure \
  --group material --xlabel "Temperature (K)" --ylabel "Pressure (MPa)" \
  -o figures/tp_scatter.pdf
```

**Tips:**
- Add `--group` to color-code by category.
- A regression line with 95% CI is drawn automatically.
- Use log scales for data spanning multiple orders of magnitude.

---

## 4. Correlation — Heatmap

**When to use:** Visualize a correlation matrix, confusion matrix, or any 2D grid of values.

**Required data:** Either all numeric columns (auto-correlation matrix) or three columns (x, y, value).

**Example command:**
```bash
python .claude/skills/figure-generation/scripts/plot_data.py features.csv \
  --type heatmap --title "Feature Correlations" \
  -o figures/correlation_heatmap.pdf
```

**Tips:**
- For correlation matrices, all numeric columns are used automatically.
- For pivot-style heatmaps, provide `--x`, `--y`, and a value column.

---

## 5. Trend — Line Graph

**When to use:** Show how a variable changes over a continuous axis (time, distance, dose).

**Required data:** Two numeric columns (x, y). Optional `--yerr` for confidence bands.

**Example command:**
```bash
python .claude/skills/figure-generation/scripts/plot_data.py timeseries.csv \
  --type line --x time --y value --group condition \
  --xlabel "Time (s)" --ylabel "Signal (a.u.)" --title "Time Course" \
  -o figures/time_course.pdf
```

**Tips:**
- Use `--group` to plot multiple lines with different colors.
- Shaded confidence regions appear automatically when `--yerr` is provided.

---

## 6. Distribution — Histogram

**When to use:** Show frequency distribution of a single continuous variable.

**Required data:** One numeric column (x).

**Example command:**
```bash
python .claude/skills/figure-generation/scripts/plot_data.py samples.csv \
  --type histogram --x age --xlabel "Age (years)" --title "Age Distribution" \
  -o figures/age_histogram.pdf
```

**Tips:**
- A KDE overlay is drawn automatically.
- Bin count is auto-tuned by the Freedman-Diaconis rule.

---

## 7. Distribution — Violin Plot

**When to use:** Show full distribution shape (density) across groups. Richer than box plots.

**Required data:** One categorical column (x), one numeric column (y).

**Example command:**
```bash
python .claude/skills/figure-generation/scripts/plot_data.py experiment.csv \
  --type violin --x group --y score --title "Score Distributions" \
  -o figures/violin_plot.pdf
```

---

## 8. Effect Size — Error Bar Plot

**When to use:** Show means with uncertainty (SD, SE, CI) across conditions.

**Required data:** Numeric columns for x, y, and yerr (error bar values).

**Example command:**
```bash
python .claude/skills/figure-generation/scripts/plot_data.py summary.csv \
  --type errorbar --x dose --y mean_response --yerr std_error \
  --xlabel "Dose (mg)" --ylabel "Response" --title "Dose-Response" \
  -o figures/errorbar.pdf
```

---

## 9. Effect Size — Forest Plot

**When to use:** Display effect sizes with confidence intervals from meta-analyses or multiple studies.

**Required data:** Columns named `label`, `effect`, `ci_low`, `ci_high`.

**Example command:**
```bash
python .claude/skills/figure-generation/scripts/plot_data.py meta_analysis.csv \
  --type forest --title "Pooled Effect Sizes" \
  -o figures/forest_plot.pdf
```

**Tips:**
- Point sizes can be proportional to sample weight (if a `weight` column exists).
- A vertical line at zero (or one for odds ratios) marks the null effect.

---

## 10. Classification — ROC Curve

**When to use:** Evaluate binary classifier performance across thresholds.

**Required data:** Columns named `fpr` (false positive rate) and `tpr` (true positive rate). AUC is computed automatically.

**Example command:**
```bash
python .claude/skills/figure-generation/scripts/plot_data.py roc_data.csv \
  --type roc --title "ROC Curve" \
  -o figures/roc_curve.pdf
```

**Tips:**
- For multiple models, use `--group` with a model column.
- The diagonal reference line (random classifier) is drawn automatically.

---

## Decision Tree

```
Is the figure built from data values?
├── Yes → figure-generation (this skill)
│   ├── Compare categories → bar or box
│   ├── Show relationship → scatter
│   ├── Show trend over axis → line
│   ├── Show distribution → histogram or violin
│   ├── Show 2D grid / matrix → heatmap
│   ├── Show uncertainty → errorbar
│   ├── Show pooled effects → forest
│   └── Show classifier performance → roc
└── No → Is it a schematic/diagram?
    ├── Yes → scientific-schematics
    └── No → generate-image (photorealistic)
```
