---
name: figure-generation
description: >
  Generate publication-quality data-derived figures (bar, scatter, line, heatmap,
  box, violin, histogram, error bar, ROC, forest, contour) using matplotlib with
  IEEE/Nature/ASCE compliant styling. Use this skill for ANY figure built from
  actual data values. Do NOT use it for conceptual diagrams, flowcharts, or
  AI-generated images — those belong to scientific-schematics or generate-image.
allowed-tools: [Read, Write, Edit, Bash]
---

# Figure Generation Skill

Generate publication-ready figures from data files using matplotlib with
Okabe-Ito colorblind-safe palette and IEEE/Nature/ASCE compliant defaults.

## Unified Style Specification (MANDATORY)

**Before generating ANY figure**, read `references/unified_visual_style.md`. This is the SINGLE SOURCE OF TRUTH for all figure styles -- matplotlib AND AI-generated figures must follow it.

- **Matplotlib:** `style.apply()` loads these settings as rcParams
- **AI figures:** Include the "AI-Generated Diagrams" section from the unified style guide in every prompt
- **Goal:** Every figure in the same paper looks visually consistent regardless of generation method

## When to Use

| Scenario | Skill |
|----------|-------|
| Bar chart, scatter plot, line graph, heatmap, box plot, violin plot, histogram, error bar chart, ROC curve, survival curve, forest plot, contour plot — **any figure derived from data** | **figure-generation** (matplotlib) |
| Flowcharts, architecture diagrams, biological pathways, CONSORT/PRISMA diagrams, graphical abstracts, conceptual frameworks | scientific-schematics (AI image generation) |
| Photorealistic images, artistic illustrations, cover art, lab setup photos | generate-image (AI image generation) |

**Rule of thumb:** If the figure is built by plotting numeric/categorical data from a CSV, JSON, or Excel file, use **figure-generation**. If it is a schematic, diagram, or conceptual illustration, use **scientific-schematics** or **generate-image**.

## Quick Start

### Style Module

Import and apply the centralized style at the top of any matplotlib script:

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# If running from project root:
# sys.path.insert(0, "/path/to/project")
import scripts.sci_figure_style as style
style.apply()
```

Or use the CLI script directly:

```bash
python scripts/plot_data.py data.csv --type bar --x category --y value -o figures/bar_chart.pdf
```

### Common Examples

```bash
# Bar chart from CSV
python scripts/plot_data.py results.csv \
  --type bar --x method --y accuracy --group dataset -o figures/accuracy_comparison.pdf

# Scatter plot with regression line
python scripts/plot_data.py measurements.csv \
  --type scatter --x temperature --y pressure --title "T vs P" -o figures/tp_scatter.pdf

# Heatmap of correlation matrix
python scripts/plot_data.py features.csv \
  --type heatmap --title "Feature Correlations" -o figures/corr_heatmap.pdf

# Box plot grouped by category
python scripts/plot_data.py experiment.csv \
  --type box --x treatment --y response --title "Treatment Effects" -o figures/boxplot.pdf

# ROC curve (requires columns: fpr, tpr)
python scripts/plot_data.py roc_data.csv \
  --type roc --x fpr --y tpr --title "Model ROC" -o figures/roc_curve.pdf

# Forest plot (requires columns: effect, ci_low, ci_high, label)
python scripts/plot_data.py meta.csv \
  --type forest --title "Meta-Analysis" -o figures/forest_plot.pdf
```

## Style Defaults (`sci_figure_style`)

The style module at `scripts/sci_figure_style.py` provides:

| Setting | Value |
|---------|-------|
| **Palette** | Okabe-Ito colorblind-safe (8 colors) |
| **Font** | Arial/Helvetica, 9pt body, 10pt titles |
| **Spines** | Top and right removed (despined) |
| **Line width** | 0.5pt axes, 1.0pt data lines |
| **Ticks** | Outward, 3pt major, 1.5pt minor |
| **Legend** | No frame |
| **Grid** | Off by default, 0.3pt when enabled |
| **PDF font** | TrueType (fonttype=42, editable in Illustrator) |
| **Figure sizes** | single (3.5x2.625"), double (7.16x4.296"), square (3.5x3.5"), slide (10x5.625") |
| **DPI** | pub=300, line=600, screen=150 |

### In Python Scripts

```python
import scripts.sci_figure_style as style

style.apply()                              # set all rcParams
fig, ax = style.create_figure("single")    # create sized figure
# ... plot your data ...
style.save_figure(fig, "output.pdf", dpi="pub")  # save with correct DPI
```

### Size Presets

| Name | Dimensions (in.) | Use case |
|------|-------------------|----------|
| `single` | 3.5 x 2.625 | Single-column figure |
| `double` | 7.16 x 4.296 | Full-page width figure |
| `square` | 3.5 x 3.5 | Square aspect ratio |
| `slide` | 10 x 5.625 | 16:9 presentation slide |

## Supported Plot Types

| Type | Description | Required columns |
|------|-------------|------------------|
| `bar` | Bar chart (grouped or stacked) | `x` (categorical), `y` (numeric) |
| `scatter` | Scatter plot with optional regression | `x`, `y` (numeric) |
| `line` | Line plot with optional CI shading | `x`, `y` (numeric) |
| `heatmap` | Correlation matrix or pivot heatmap | All numeric columns (auto-corr) or `x`, `y`, `value` |
| `box` | Box plot with optional jittered points | `x` (categorical), `y` (numeric) |
| `violin` | Violin plot | `x` (categorical), `y` (numeric) |
| `histogram` | Histogram with optional KDE overlay | `x` (numeric) |
| `errorbar` | Error bar plot | `x`, `y`, `yerr` (numeric) |
| `roc` | ROC curve with AUC annotation | `x` (FPR), `y` (TPR) |
| `forest` | Forest plot for effect sizes | `effect`, `ci_low`, `ci_high`, `label` |

## Route to Other Skills

- Need a **flowchart or architecture diagram**? Use `scientific-schematics`.
- Need a **PRISMA or CONSORT diagram**? Use `scientific-schematics`.
- Need a **graphical abstract**? Use `scientific-schematics`.
- Need a **photorealistic illustration**? Use `generate-image`.
- Need a **slide deck**? Use `scientific-slides`.
