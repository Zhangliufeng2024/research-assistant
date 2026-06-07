#!/usr/bin/env python3
"""
plot_data.py — General-purpose CLI for creating publication-ready matplotlib figures.

Supports: bar, scatter, line, heatmap, box, violin, histogram, errorbar, roc, forest,
          contour, survival, waterfall, radar

Usage:
    python plot_data.py data.csv --type bar --x category --y value -o output.pdf
    python plot_data.py data.csv --type scatter --x col1 --y col2 --group col3 -o output.pdf
    python plot_data.py data.csv --type heatmap -o output.pdf
    python plot_data.py data.csv --type contour --x x --y y --group z -o contour.pdf
    python plot_data.py data.csv --type survival --x time --y event --group group -o survival.pdf
    python plot_data.py data.csv --type waterfall --x label --y value -o waterfall.pdf
    python plot_data.py data.csv --type radar --x category --y value --group group -o radar.pdf
"""

from __future__ import annotations

import argparse
import json
import os
import sys
# Fix Windows console encoding for emoji/non-ASCII characters
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Style import with fallback
# ---------------------------------------------------------------------------
_STYLE_AVAILABLE = False

def _try_import_style():
    """Try to import sci_figure_style from project scripts/ dir."""
    global _STYLE_AVAILABLE
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent.parent.parent.parent / "scripts",  # project root/scripts
        here.parent.parent.parent / "scripts",                # alternate layout
        here.parent.parent / "scripts",                       # skill-level scripts
    ]

    import importlib.util
    for p in candidates:
        mod = p / "sci_figure_style.py"
        if mod.exists():
            try:
                spec = importlib.util.spec_from_file_location("sci_figure_style", mod)
                if spec and spec.loader:
                    sfx = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(sfx)
                    _STYLE_AVAILABLE = True
                    return sfx
            except Exception as e:
                print(f"[WARN] Failed to load sci_figure_style from {mod}: {e}", file=sys.stderr)
                continue

    return None

style = _try_import_style()

# ---------------------------------------------------------------------------
# Matplotlib setup
# ---------------------------------------------------------------------------
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas is required. Install with: pip install pandas", file=sys.stderr)
    sys.exit(1)

try:
    from scipy import stats as sp_stats
except ImportError:
    sp_stats = None

# ---------------------------------------------------------------------------
# Unified Scientific Style Module
# ---------------------------------------------------------------------------

SCIENTIFIC_STYLE = {
    # Font configuration
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "DejaVu Sans", "Helvetica"],
    "font.size": 10,
    "axes.titlesize": 14,
    "axes.labelsize": 12,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 10,

    # Okabe-Ito colorblind-safe palette
    "palette": [
        "#E69F00", "#56B4E9", "#009E73", "#F0E442",
        "#0072B2", "#D55E00", "#CC79A7", "#000000",
    ],

    # Axes style
    "axes.linewidth": 1.2,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.direction": "out",
    "ytick.direction": "out",
    "xtick.major.size": 4,
    "ytick.major.size": 4,
    "xtick.major.width": 1.0,
    "ytick.major.width": 1.0,

    # Grid (y-axis only)
    "axes.grid": True,
    "axes.grid.axis": "y",
    "grid.alpha": 0.3,
    "grid.linewidth": 0.5,

    # Lines and markers
    "lines.linewidth": 1.5,
    "lines.markersize": 6,

    # Legend
    "legend.frameon": False,
    "legend.borderaxespad": 0.5,

    # PDF embedding
    "pdf.fonttype": 42,
    "ps.fonttype": 42,

    # Figure DPI presets
    "dpi": {"pub": 300, "draft": 150, "line": 600},

    # Figure size presets (inches)
    "figsize": {
        "single": (3.5, 2.8),
        "double": (7.0, 4.5),
        "square": (4.0, 4.0),
        "slide": (10, 6),
    },
}

_OKABE_ITO = SCIENTIFIC_STYLE["palette"]
_SIZE_MAP = SCIENTIFIC_STYLE["figsize"]
_DPI_MAP = SCIENTIFIC_STYLE["dpi"]


def _apply_fallback_style():
    """Apply the unified scientific style to matplotlib rcParams."""
    rc = plt.rcParams
    for key in [
        "font.family", "font.sans-serif", "font.size",
        "axes.titlesize", "axes.labelsize",
        "xtick.labelsize", "ytick.labelsize", "legend.fontsize",
        "axes.linewidth", "axes.spines.top", "axes.spines.right",
        "xtick.direction", "ytick.direction",
        "xtick.major.size", "ytick.major.size",
        "xtick.major.width", "ytick.major.width",
        "axes.grid", "grid.alpha", "grid.linewidth",
        "lines.linewidth", "lines.markersize",
        "legend.frameon", "legend.borderaxespad",
        "pdf.fonttype", "ps.fonttype",
    ]:
        if key in SCIENTIFIC_STYLE:
            rc[key] = SCIENTIFIC_STYLE[key]
    # Grid axis must be set separately
    rc["axes.grid.axis"] = SCIENTIFIC_STYLE["axes.grid.axis"]
    # Set color cycle
    rc["axes.prop_cycle"] = plt.cycler(color=SCIENTIFIC_STYLE["palette"])


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(path: str) -> pd.DataFrame:
    """Load CSV, JSON, or Excel file into a DataFrame."""
    p = Path(path)
    if not p.exists():
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    ext = p.suffix.lower()
    try:
        if ext == ".csv":
            return pd.read_csv(p)
        elif ext == ".json":
            return pd.read_json(p)
        elif ext in (".xlsx", ".xls"):
            return pd.read_excel(p)
        elif ext == ".tsv":
            return pd.read_csv(p, sep="\t")
        else:
            # Try CSV as fallback
            return pd.read_csv(p)
    except Exception as e:
        print(f"ERROR: Could not load {path}: {e}", file=sys.stderr)
        sys.exit(1)


def _get_col(df: pd.DataFrame, name: Optional[str], label: str) -> Optional[str]:
    """Validate that a column exists in the DataFrame."""
    if name is None:
        return None
    if name not in df.columns:
        available = ", ".join(df.columns.tolist())
        print(f"ERROR: Column '{name}' not found for {label}. Available: {available}", file=sys.stderr)
        sys.exit(1)
    return name


def _get_numeric_cols(df: pd.DataFrame) -> list[str]:
    """Return list of numeric column names."""
    return df.select_dtypes(include=[np.number]).columns.tolist()


# ---------------------------------------------------------------------------
# Plot type implementations
# ---------------------------------------------------------------------------

def plot_bar(ax: plt.Axes, df: pd.DataFrame, args: argparse.Namespace) -> None:
    """Grouped or stacked bar chart."""
    x_col = _get_col(df, args.x, "--x")
    y_col = _get_col(df, args.y, "--y")
    group_col = _get_col(df, args.group, "--group")

    if x_col is None or y_col is None:
        print("ERROR: --type bar requires --x and --y", file=sys.stderr)
        sys.exit(1)

    if group_col:
        pivot = df.pivot_table(index=x_col, columns=group_col, values=y_col, aggfunc="mean")
        pivot.plot(kind="bar", ax=ax, width=0.8, edgecolor="white", linewidth=0.5)
        ax.legend(title=group_col, bbox_to_anchor=(1.02, 1), loc="upper left")
    else:
        grouped = df.groupby(x_col)[y_col].mean().sort_values()
        ax.bar(range(len(grouped)), grouped.values, width=0.8, edgecolor="white", linewidth=0.5)
        ax.set_xticks(range(len(grouped)))
        ax.set_xticklabels(grouped.index, rotation=45, ha="right")

    ax.set_ylabel(y_col)


def plot_scatter(ax: plt.Axes, df: pd.DataFrame, args: argparse.Namespace) -> None:
    """Scatter plot with optional regression line and CI."""
    x_col = _get_col(df, args.x, "--x")
    y_col = _get_col(df, args.y, "--y")
    group_col = _get_col(df, args.group, "--group")

    if x_col is None or y_col is None:
        print("ERROR: --type scatter requires --x and --y", file=sys.stderr)
        sys.exit(1)

    x = df[x_col].dropna()
    y = df[y_col].dropna()
    idx = x.index.intersection(y.index)
    x, y = x.loc[idx], y.loc[idx]

    if group_col:
        for i, (name, grp) in enumerate(df.groupby(group_col)):
            color = _OKABE_ITO[i % len(_OKABE_ITO)]
            ax.scatter(grp[x_col], grp[y_col], s=20, alpha=0.7, label=name, color=color, edgecolors="white", linewidth=0.3)
        ax.legend(title=group_col)
    else:
        ax.scatter(x, y, s=20, alpha=0.7, edgecolors="white", linewidth=0.3)

    # Regression line
    if len(x) > 2:
        try:
            slope, intercept, r_value, p_value, std_err = sp_stats.linregress(x, y) if sp_stats else (None,)*5
            if slope is not None:
                x_line = np.linspace(x.min(), x.max(), 100)
                y_line = slope * x_line + intercept
                ax.plot(x_line, y_line, color=_OKABE_ITO[-2], linewidth=1, linestyle="--", alpha=0.8)
                # 95% CI band
                n = len(x)
                x_mean = x.mean()
                se_line = std_err * np.sqrt(1/n + (x_line - x_mean)**2 / ((x - x_mean)**2).sum())
                ax.fill_between(x_line, y_line - 1.96*se_line, y_line + 1.96*se_line,
                                alpha=0.15, color=_OKABE_ITO[-2])
                ax.text(0.05, 0.95, f"R² = {r_value**2:.3f}", transform=ax.transAxes,
                        fontsize=7, va="top")
        except Exception:
            pass


def plot_line(ax: plt.Axes, df: pd.DataFrame, args: argparse.Namespace) -> None:
    """Line plot with optional shaded confidence region."""
    x_col = _get_col(df, args.x, "--x")
    y_col = _get_col(df, args.y, "--y")
    group_col = _get_col(df, args.group, "--group")
    yerr_col = _get_col(df, args.yerr, "--yerr")

    if x_col is None or y_col is None:
        print("ERROR: --type line requires --x and --y", file=sys.stderr)
        sys.exit(1)

    if group_col:
        for i, (name, grp) in enumerate(df.groupby(group_col)):
            color = _OKABE_ITO[i % len(_OKABE_ITO)]
            grp_sorted = grp.sort_values(x_col)
            ax.plot(grp_sorted[x_col], grp_sorted[y_col], label=name, color=color)
            if yerr_col and yerr_col in grp_sorted.columns:
                ax.fill_between(grp_sorted[x_col],
                                grp_sorted[y_col] - grp_sorted[yerr_col],
                                grp_sorted[y_col] + grp_sorted[yerr_col],
                                alpha=0.15, color=color)
        ax.legend(title=group_col)
    else:
        df_sorted = df.sort_values(x_col)
        ax.plot(df_sorted[x_col], df_sorted[y_col])
        if yerr_col:
            ax.fill_between(df_sorted[x_col],
                            df_sorted[y_col] - df_sorted[yerr_col],
                            df_sorted[y_col] + df_sorted[yerr_col],
                            alpha=0.15)


def plot_heatmap(ax: plt.Axes, df: pd.DataFrame, args: argparse.Namespace) -> None:
    """Correlation matrix or pivot table heatmap."""
    x_col = _get_col(df, args.x, "--x")
    y_col = _get_col(df, args.y, "--y")

    if x_col and y_col:
        # Pivot-style heatmap: x, y, and a value column (first numeric not x/y)
        num_cols = _get_numeric_cols(df)
        val_candidates = [c for c in num_cols if c not in (x_col, y_col)]
        if val_candidates:
            val_col = val_candidates[0]
            pivot = df.pivot_table(index=y_col, columns=x_col, values=val_col, aggfunc="mean")
        else:
            print("ERROR: Need a numeric value column for pivot heatmap", file=sys.stderr)
            sys.exit(1)
    else:
        # Correlation matrix of all numeric columns
        num_df = df.select_dtypes(include=[np.number])
        if num_df.shape[1] < 2:
            print("ERROR: Need at least 2 numeric columns for correlation heatmap", file=sys.stderr)
            sys.exit(1)
        pivot = num_df.corr()

    im = ax.imshow(pivot.values, cmap="RdBu_r", aspect="auto", vmin=-1, vmax=1)
    ax.set_xticks(range(pivot.shape[1]))
    ax.set_xticklabels(pivot.columns, rotation=45, ha="right", fontsize=7)
    ax.set_yticks(range(pivot.shape[0]))
    ax.set_yticklabels(pivot.index, fontsize=7)

    # Annotate with values
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            val = pivot.values[i, j]
            if not np.isnan(val):
                color = "white" if abs(val) > 0.6 else "black"
                ax.text(j, i, f"{val:.2f}", ha="center", va="center", fontsize=6, color=color)

    plt.colorbar(im, ax=ax, shrink=0.8, label="Correlation" if x_col is None else val_col)


def plot_box(ax: plt.Axes, df: pd.DataFrame, args: argparse.Namespace) -> None:
    """Box plot with optional jittered individual points."""
    x_col = _get_col(df, args.x, "--x")
    y_col = _get_col(df, args.y, "--y")

    if x_col is None or y_col is None:
        print("ERROR: --type box requires --x and --y", file=sys.stderr)
        sys.exit(1)

    groups = [grp[y_col].dropna().values for _, grp in df.groupby(x_col)]
    labels = [name for name, _ in df.groupby(x_col)]

    bp = ax.boxplot(groups, tick_labels=labels, patch_artist=True, widths=0.6,
                    boxprops=dict(linewidth=0.5),
                    whiskerprops=dict(linewidth=0.5),
                    capprops=dict(linewidth=0.5),
                    medianprops=dict(linewidth=1, color="black"),
                    flierprops=dict(markersize=3, marker="o", alpha=0.5))

    # Color the boxes
    for i, patch in enumerate(bp["boxes"]):
        patch.set_facecolor(_OKABE_ITO[i % len(_OKABE_ITO)])
        patch.set_alpha(0.6)

    # Overlay jittered points
    for i, (name, grp) in enumerate(df.groupby(x_col)):
        y_vals = grp[y_col].dropna().values
        jitter = np.random.normal(0, 0.04, size=len(y_vals))
        ax.scatter(np.full_like(y_vals, i + 1, dtype=float) + jitter, y_vals,
                   s=8, alpha=0.4, color=_OKABE_ITO[i % len(_OKABE_ITO)], zorder=3, linewidth=0)

    if labels and any(len(str(l)) > 8 for l in labels):
        ax.set_xticklabels(labels, rotation=45, ha="right")


def plot_violin(ax: plt.Axes, df: pd.DataFrame, args: argparse.Namespace) -> None:
    """Violin plot."""
    x_col = _get_col(df, args.x, "--x")
    y_col = _get_col(df, args.y, "--y")

    if x_col is None or y_col is None:
        print("ERROR: --type violin requires --x and --y", file=sys.stderr)
        sys.exit(1)

    groups = [grp[y_col].dropna().values for _, grp in df.groupby(x_col)]
    labels = [name for name, _ in df.groupby(x_col)]

    vp = ax.violinplot(groups, showmeans=True, showmedians=True, showextrema=False)

    for i, body in enumerate(vp["bodies"]):
        body.set_facecolor(_OKABE_ITO[i % len(_OKABE_ITO)])
        body.set_alpha(0.6)
        body.set_linewidth(0.5)

    vp["cmeans"].set_color("black")
    vp["cmeans"].set_linewidth(0.5)
    vp["cmedians"].set_color("red")
    vp["cmedians"].set_linewidth(0.5)
    vp["cmedians"].set_linestyle("--")

    ax.set_xticks(range(1, len(labels) + 1))
    ax.set_xticklabels(labels, rotation=45 if any(len(str(l)) > 8 for l in labels) else 0,
                        ha="right" if any(len(str(l)) > 8 for l in labels) else "center")


def plot_histogram(ax: plt.Axes, df: pd.DataFrame, args: argparse.Namespace) -> None:
    """Histogram with optional KDE overlay."""
    x_col = _get_col(df, args.x, "--x")
    group_col = _get_col(df, args.group, "--group")

    if x_col is None:
        print("ERROR: --type histogram requires --x", file=sys.stderr)
        sys.exit(1)

    if group_col:
        for i, (name, grp) in enumerate(df.groupby(group_col)):
            data = grp[x_col].dropna()
            color = _OKABE_ITO[i % len(_OKABE_ITO)]
            ax.hist(data, bins="auto", alpha=0.5, label=name, color=color, edgecolor="white", linewidth=0.3, density=True)
            # KDE overlay
            if sp_stats is not None and len(data) > 1:
                kde_x = np.linspace(data.min(), data.max(), 200)
                kernel = sp_stats.gaussian_kde(data)
                ax.plot(kde_x, kernel(kde_x), color=color, linewidth=1)
        ax.legend(title=group_col)
    else:
        data = df[x_col].dropna()
        ax.hist(data, bins="auto", alpha=0.7, edgecolor="white", linewidth=0.3, density=True)
        if sp_stats is not None and len(data) > 1:
            kde_x = np.linspace(data.min(), data.max(), 200)
            kernel = sp_stats.gaussian_kde(data)
            ax.plot(kde_x, kernel(kde_x), color=_OKABE_ITO[4], linewidth=1)

    ax.set_ylabel("Density")


def plot_errorbar(ax: plt.Axes, df: pd.DataFrame, args: argparse.Namespace) -> None:
    """Error bar plot."""
    x_col = _get_col(df, args.x, "--x")
    y_col = _get_col(df, args.y, "--y")
    yerr_col = _get_col(df, args.yerr, "--yerr")
    group_col = _get_col(df, args.group, "--group")

    if x_col is None or y_col is None:
        print("ERROR: --type errorbar requires --x and --y", file=sys.stderr)
        sys.exit(1)

    if group_col:
        for i, (name, grp) in enumerate(df.groupby(group_col)):
            color = _OKABE_ITO[i % len(_OKABE_ITO)]
            grp_sorted = grp.sort_values(x_col)
            yerr = grp_sorted[yerr_col].values if yerr_col else None
            ax.errorbar(grp_sorted[x_col], grp_sorted[y_col], yerr=yerr,
                        fmt="o-", color=color, markersize=5, linewidth=1, capsize=3, capthick=0.5, label=name)
        ax.legend(title=group_col)
    else:
        df_sorted = df.sort_values(x_col)
        yerr = df_sorted[yerr_col].values if yerr_col else None
        ax.errorbar(df_sorted[x_col], df_sorted[y_col], yerr=yerr,
                    fmt="o-", color=_OKABE_ITO[0], markersize=5, linewidth=1, capsize=3, capthick=0.5)


def plot_roc(ax: plt.Axes, df: pd.DataFrame, args: argparse.Namespace) -> None:
    """ROC curve with AUC annotation."""
    fpr_col = _get_col(df, args.x or "fpr", "fpr")
    tpr_col = _get_col(df, args.y or "tpr", "tpr")
    group_col = _get_col(df, args.group, "--group")

    if fpr_col is None or tpr_col is None:
        print("ERROR: --type roc requires columns 'fpr' and 'tpr' (or specify --x fpr --y tpr)", file=sys.stderr)
        sys.exit(1)

    if group_col:
        for i, (name, grp) in enumerate(df.groupby(group_col)):
            color = _OKABE_ITO[i % len(_OKABE_ITO)]
            grp_sorted = grp.sort_values(fpr_col)
            fpr = grp_sorted[fpr_col].values
            tpr = grp_sorted[tpr_col].values
            # Compute AUC via trapezoidal rule
            auc_val = np.trapz(tpr, fpr) if len(fpr) > 1 else 0.0
            ax.plot(fpr, tpr, color=color, label=f"{name} (AUC = {auc_val:.3f})")
        ax.legend(loc="lower right")
    else:
        df_sorted = df.sort_values(fpr_col)
        fpr = df_sorted[fpr_col].values
        tpr = df_sorted[tpr_col].values
        auc_val = np.trapz(tpr, fpr) if len(fpr) > 1 else 0.0
        ax.plot(fpr, tpr, color=_OKABE_ITO[4], label=f"AUC = {auc_val:.3f}")
        ax.legend(loc="lower right")

    # Diagonal reference line
    ax.plot([0, 1], [0, 1], color="gray", linestyle="--", linewidth=0.5, alpha=0.5)
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.set_aspect("equal")
    ax.set_xlabel("False Positive Rate")
    ax.set_ylabel("True Positive Rate")


def plot_forest(ax: plt.Axes, df: pd.DataFrame, args: argparse.Namespace) -> None:
    """Forest plot for effect sizes with confidence intervals."""
    # Expected columns: label, effect, ci_low, ci_high
    required = ["label", "effect", "ci_low", "ci_high"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f"ERROR: --type forest requires columns: {', '.join(required)}. Missing: {', '.join(missing)}", file=sys.stderr)
        print(f"  Available columns: {', '.join(df.columns.tolist())}", file=sys.stderr)
        sys.exit(1)

    n = len(df)
    y_pos = np.arange(n)

    effects = df["effect"].values
    ci_low = df["ci_low"].values
    ci_high = df["ci_high"].values
    labels = df["label"].values

    # Point sizes (proportional to weight if available)
    if "weight" in df.columns:
        weights = df["weight"].values
        sizes = 20 + 80 * (weights / weights.max())
    else:
        sizes = np.full(n, 40)

    # Draw CI lines
    for i in range(n):
        ax.plot([ci_low[i], ci_high[i]], [i, i], color=_OKABE_ITO[4], linewidth=1)

    # Draw effect points
    ax.scatter(effects, y_pos, s=sizes, color=_OKABE_ITO[4], zorder=5, edgecolors="white", linewidth=0.3)

    # Null reference line (0 for mean differences, 1 for odds ratios)
    null_val = 0 if effects.min() >= -5 else 1  # heuristic
    ax.axvline(null_val, color="gray", linestyle="--", linewidth=0.5, alpha=0.5)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel("Effect Size (95% CI)")

    # Add CI text on right side
    for i in range(n):
        ax.text(ax.get_xlim()[1] if ax.get_xlim()[1] != 1 else ci_high.max() * 1.1,
                i, f" {effects[i]:.2f} [{ci_low[i]:.2f}, {ci_high[i]:.2f}]",
                va="center", fontsize=6, transform=ax.get_yaxis_transform())


def plot_contour(ax: plt.Axes, df: pd.DataFrame, args: argparse.Namespace) -> None:
    """Filled contour plot for 2D function visualization (loss surfaces, heat maps).

    Expects CSV with x, y, z columns. If z is not a direct column, the first
    numeric column not used as x or y is used.
    """
    x_col = _get_col(df, args.x, "--x")
    y_col = _get_col(df, args.y, "--y")

    if x_col is None or y_col is None:
        print("ERROR: --type contour requires --x and --y", file=sys.stderr)
        sys.exit(1)

    # Determine z column: try args.group, else first numeric col not x/y
    num_cols = _get_numeric_cols(df)
    if args.group and args.group in df.columns:
        z_col = args.group
    else:
        candidates = [c for c in num_cols if c not in (x_col, y_col)]
        if not candidates:
            print("ERROR: Need a numeric z column (use --group z_col or ensure a third numeric column exists)", file=sys.stderr)
            sys.exit(1)
        z_col = candidates[0]

    # Pivot into grid form
    try:
        pivot = df.pivot_table(index=y_col, columns=x_col, values=z_col, aggfunc="mean")
        x_vals = pivot.columns.values.astype(float)
        y_vals = pivot.index.values.astype(float)
        z_vals = pivot.values
    except Exception as e:
        print(f"ERROR: Could not pivot data for contour: {e}", file=sys.stderr)
        sys.exit(1)

    X, Y = np.meshgrid(x_vals, y_vals)
    cs = ax.contourf(X, Y, z_vals, levels=20, cmap="viridis")
    ax.contour(X, Y, z_vals, levels=20, colors="black", linewidths=0.3, alpha=0.3)
    plt.colorbar(cs, ax=ax, shrink=0.8, label=z_col)
    ax.set_xlabel(x_col)
    ax.set_ylabel(y_col)


def plot_survival(ax: plt.Axes, df: pd.DataFrame, args: argparse.Namespace) -> None:
    """Kaplan-Meier survival curve using a simple step-plot implementation.

    Expects CSV with time, event, group columns. event=1 means event occurred,
    event=0 means censored. No lifelines dependency.
    """
    time_col = _get_col(df, args.x or "time", "time")
    event_col = _get_col(df, args.y or "event", "event")
    group_col = _get_col(df, args.group, "--group")

    if time_col is None or event_col is None:
        print("ERROR: --type survival requires --x time and --y event columns", file=sys.stderr)
        sys.exit(1)

    def _kaplan_meier(times, events):
        """Simple KM estimator returning (step_times, survival_probs, ci_low, ci_high)."""
        times = np.asarray(times, dtype=float)
        events = np.asarray(events, dtype=float)
        order = np.argsort(times)
        times = times[order]
        events = events[order]

        unique_times = np.unique(times[events == 1])
        if len(unique_times) == 0:
            return np.array([0, times.max()]), np.array([1.0, 1.0]), np.array([1.0, 1.0]), np.array([1.0, 1.0])

        surv = 1.0
        n_at_risk = len(times)
        var_sum = 0.0
        step_times = [0.0]
        step_surv = [1.0]
        step_var = [0.0]

        for t in unique_times:
            d = np.sum((times == t) & (events == 1))
            n = np.sum(times >= t)
            if n > 0:
                surv *= (1 - d / n)
                if n > d:
                    var_sum += d / (n * (n - d))
            step_times.append(t)
            step_surv.append(surv)
            step_var.append(surv ** 2 * var_sum)

        st = np.array(step_times)
        ss = np.array(step_surv)
        sv = np.array(step_var)
        se = np.sqrt(sv)
        ci_low = np.clip(ss - 1.96 * se, 0, 1)
        ci_high = np.clip(ss + 1.96 * se, 0, 1)
        return st, ss, ci_low, ci_high

    colors = SCIENTIFIC_STYLE["palette"]

    if group_col:
        for i, (name, grp) in enumerate(df.groupby(group_col)):
            color = colors[i % len(colors)]
            t, s, cl, ch = _kaplan_meier(grp[time_col].values, grp[event_col].values)
            ax.step(t, s, where="post", color=color, label=name, linewidth=1.5)
            ax.fill_between(t, cl, ch, step="post", alpha=0.12, color=color)
        ax.legend(title=group_col, loc="lower left")
    else:
        t, s, cl, ch = _kaplan_meier(df[time_col].values, df[event_col].values)
        ax.step(t, s, where="post", color=colors[4], linewidth=1.5)
        ax.fill_between(t, cl, ch, step="post", alpha=0.12, color=colors[4])

    ax.set_ylim(-0.02, 1.05)
    ax.set_xlabel("Time")
    ax.set_ylabel("Survival Probability")
    ax.axhline(0.5, color="gray", linestyle=":", linewidth=0.5, alpha=0.5)


def plot_waterfall(ax: plt.Axes, df: pd.DataFrame, args: argparse.Namespace) -> None:
    """Waterfall chart for sequential positive/negative changes.

    Expects CSV with label (or --x) and value (or --y) columns.
    Each bar starts where the previous one ended.
    """
    label_col = _get_col(df, args.x or "label", "label")
    value_col = _get_col(df, args.y or "value", "value")

    if label_col is None or value_col is None:
        print("ERROR: --type waterfall requires --x (labels) and --y (values)", file=sys.stderr)
        sys.exit(1)

    labels = df[label_col].tolist()
    values = df[value_col].values.astype(float)
    n = len(values)

    colors = SCIENTIFIC_STYLE["palette"]
    pos_color = colors[2]   # green for positive
    neg_color = colors[5]   # red for negative
    tot_color = colors[4]   # blue for totals

    # Cumulative running total
    cumulative = np.zeros(n + 1)
    for i in range(n):
        cumulative[i + 1] = cumulative[i] + values[i]

    bar_colors = []
    for i in range(n):
        # If this is a "total" bar (sum), or values are all positive and cumulative matches
        if values[i] >= 0:
            bar_colors.append(pos_color)
        else:
            bar_colors.append(neg_color)

    bar_bottoms = np.minimum(cumulative[:-1], cumulative[1:])
    bar_heights = np.abs(values)

    for i in range(n):
        ax.bar(i, bar_heights[i], bottom=bar_bottoms[i], width=0.6,
               color=bar_colors[i], edgecolor="white", linewidth=0.5)
        # Connector line from top of previous bar
        if i > 0:
            ax.plot([i - 1 + 0.3, i - 0.3], [cumulative[i], cumulative[i]],
                    color="gray", linewidth=0.5, linestyle="--")

    ax.set_xticks(range(n))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylabel("Value")

    # Net change annotation
    ax.text(n - 1 + 0.3, cumulative[-1], f"Net: {cumulative[-1]:+.2f}",
            va="bottom", fontsize=9, fontweight="bold", color=colors[4])


def plot_radar(ax: plt.Axes, df: pd.DataFrame, args: argparse.Namespace) -> None:
    """Radar / spider chart for multi-dimensional comparison.

    Expects CSV where --x is the category column (metrics along each axis) and
    --y is the value column. --group defines separate series.
    """
    cat_col = _get_col(df, args.x, "--x")
    val_col = _get_col(df, args.y, "--y")
    group_col = _get_col(df, args.group, "--group")

    if cat_col is None or val_col is None:
        print("ERROR: --type radar requires --x (category) and --y (value)", file=sys.stderr)
        sys.exit(1)

    categories = df[cat_col].unique().tolist()
    n_cats = len(categories)
    if n_cats < 3:
        print("ERROR: Radar chart needs at least 3 categories", file=sys.stderr)
        sys.exit(1)

    angles = np.linspace(0, 2 * np.pi, n_cats, endpoint=False).tolist()
    angles += angles[:1]  # close the polygon

    colors = SCIENTIFIC_STYLE["palette"]

    if group_col:
        groups = df[group_col].unique()
        for i, grp_name in enumerate(groups):
            grp_data = df[df[group_col] == grp_name]
            vals = []
            for cat in categories:
                match = grp_data[grp_data[cat_col] == cat]
                vals.append(match[val_col].mean() if len(match) > 0 else 0)
            vals += vals[:1]
            color = colors[i % len(colors)]
            ax.fill(angles, vals, alpha=0.12, color=color)
            ax.plot(angles, vals, color=color, linewidth=1.5, label=grp_name)
        ax.legend(title=group_col, loc="upper right", bbox_to_anchor=(1.3, 1.1))
    else:
        vals = []
        for cat in categories:
            match = df[df[cat_col] == cat]
            vals.append(match[val_col].mean() if len(match) > 0 else 0)
        vals += vals[:1]
        ax.fill(angles, vals, alpha=0.15, color=colors[0])
        ax.plot(angles, vals, color=colors[0], linewidth=1.5)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, fontsize=9)
    ax.set_ylim(0, None)


# ---------------------------------------------------------------------------
# Plot type dispatcher
# ---------------------------------------------------------------------------

PLOT_FUNCTIONS = {
    "bar": plot_bar,
    "scatter": plot_scatter,
    "line": plot_line,
    "heatmap": plot_heatmap,
    "box": plot_box,
    "violin": plot_violin,
    "histogram": plot_histogram,
    "errorbar": plot_errorbar,
    "roc": plot_roc,
    "forest": plot_forest,
    "contour": plot_contour,
    "survival": plot_survival,
    "waterfall": plot_waterfall,
    "radar": plot_radar,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Create publication-ready matplotlib figures from data files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s data.csv --type bar --x category --y value -o bar.pdf
  %(prog)s data.csv --type scatter --x col1 --y col2 --group col3 -o scatter.pdf
  %(prog)s data.csv --type heatmap -o heatmap.pdf
  %(prog)s meta.csv --type forest -o forest.pdf
  %(prog)s grid.csv --type contour --x lon --y lat --group temp -o contour.pdf
  %(prog)s survival.csv --type survival --x time --y event --group arm -o survival.pdf
  %(prog)s costs.csv --type waterfall --x item --y change -o waterfall.pdf
  %(prog)s metrics.csv --type radar --x metric --y score --group model -o radar.pdf
        """,
    )
    p.add_argument("input", help="Input data file (CSV, JSON, TSV, or Excel)")
    p.add_argument("--type", required=True, choices=list(PLOT_FUNCTIONS.keys()),
                   help="Plot type to generate")
    p.add_argument("--x", help="X-axis column name")
    p.add_argument("--y", help="Y-axis column name")
    p.add_argument("--group", "--hue", dest="group", help="Grouping/hue column")
    p.add_argument("--yerr", help="Error bar column name")
    p.add_argument("--size", default="single", choices=["single", "double", "square", "slide"],
                   help="Figure size preset (default: single)")
    p.add_argument("--dpi", default="pub", choices=["pub", "line", "screen"],
                   help="DPI preset (default: pub)")
    p.add_argument("--title", help="Plot title")
    p.add_argument("--xlabel", help="X-axis label")
    p.add_argument("--ylabel", help="Y-axis label")
    p.add_argument("-o", "--output", default="figures/plot.pdf",
                   help="Output file path (default: figures/plot.pdf)")
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Always apply the unified style first, then let external style override if available
    _apply_fallback_style()
    if _STYLE_AVAILABLE and style is not None:
        style.apply()

    # Load data
    df = load_data(args.input)

    # Create figure (radar needs polar projection)
    figsize = _SIZE_MAP.get(args.size, (3.5, 2.8))
    if args.type == "radar":
        fig, ax = plt.subplots(figsize=figsize, subplot_kw={"projection": "polar"})
    elif _STYLE_AVAILABLE and style is not None:
        fig, ax = style.create_figure(args.size)
    else:
        fig, ax = plt.subplots(figsize=figsize)

    # Dispatch plot
    plot_fn = PLOT_FUNCTIONS[args.type]
    plot_fn(ax, df, args)

    # Labels and title (skip for types that set their own)
    if args.title:
        ax.set_title(args.title)
    if args.xlabel:
        ax.set_xlabel(args.xlabel)
    elif args.x and args.type not in ("heatmap", "roc", "forest", "radar"):
        ax.set_xlabel(args.x)
    if args.ylabel:
        ax.set_ylabel(args.ylabel)
    elif args.y and args.type not in ("heatmap", "roc", "radar"):
        ax.set_ylabel(args.y)

    # Save
    if _STYLE_AVAILABLE and style is not None:
        out = style.save_figure(fig, args.output, dpi=args.dpi)
    else:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        dpi_val = _DPI_MAP.get(args.dpi, 300)
        fig.savefig(out, dpi=dpi_val, bbox_inches="tight", facecolor="white", edgecolor="none")
        plt.close(fig)
        out = out.resolve()

    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
