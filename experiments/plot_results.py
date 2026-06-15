"""
plot_results.py
---------------
Reads summary CSVs from all three experiments and generates
comparison graphs for the report.

Graphs produced (saved to experiments/results/plots/):
  1. p99_latency.png   — p99 latency over time, all 3 experiments
  2. cpu_cores.png     — CPU cores used over time
  3. summary_bar.png   — bar chart: avg latency + seconds with P99 > 500ms

Usage:
    python plot_results.py

Requires:
    pip install matplotlib pandas
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────
RESULTS_DIR = Path(__file__).parent.parent / "load-tester" / "results"
PLOTS_DIR   = Path(__file__).parent / "results" / "plots"
PLOTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Experiment definitions ────────────────────────────────────────────
EXPERIMENTS = {
    "hpa_70": {"label": "HPA 70%",          "color": "#e74c3c", "style": "--"},
    "hpa_90": {"label": "HPA 90%",          "color": "#e67e22", "style": "-."},
    "custom": {"label": "Custom Autoscaler", "color": "#2ecc71", "style": "-"},
}

# ── Style ─────────────────────────────────────────────────────────────
plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor":   "white",
    "axes.grid":        True,
    "grid.alpha":       0.3,
    "font.size":        11,
    "axes.titlesize":   13,
    "axes.labelsize":   11,
    "legend.fontsize":  10,
    "lines.linewidth":  1.8,
})

# ─────────────────────────────────────────────────────────────────────
# Load data
# ─────────────────────────────────────────────────────────────────────

def load_summaries() -> dict:
    dfs = {}
    for name in EXPERIMENTS:
        path = RESULTS_DIR / name / "summary.csv"
        if not path.exists():
            print(f"  [SKIP] {name} — summary.csv not found at {path}")
            continue
        df = pd.read_csv(path)
        df["second_min"] = df["second"] / 60
        dfs[name] = df
        print(f"  [OK]   {name} — {len(df)} seconds loaded")
    return dfs


# ─────────────────────────────────────────────────────────────────────
# Plot 1 — P99 latency over time
# ─────────────────────────────────────────────────────────────────────

def plot_p99_latency(dfs: dict):
    fig, ax = plt.subplots(figsize=(12, 5))
    for name, df in dfs.items():
        cfg      = EXPERIMENTS[name]
        smoothed = df["p99_latency_ms"].rolling(5, min_periods=1).mean()
        ax.plot(df["second_min"], smoothed,
                label=cfg["label"], color=cfg["color"], linestyle=cfg["style"])
    ax.axhline(500, color="black", linestyle=":", linewidth=1.2,
               label=f"SLO = {500}ms")
    ax.set_title("P99 Latency Over Time")
    ax.set_xlabel("Time (minutes)")
    ax.set_ylabel("P99 Latency (ms)")
    ax.legend()
    ax.set_ylim(bottom=0)
    out = PLOTS_DIR / "p99_latency.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out}")


# ─────────────────────────────────────────────────────────────────────
# Plot 2 — CPU cores over time
# ─────────────────────────────────────────────────────────────────────

def plot_cpu_cores(dfs: dict):
    fig, ax = plt.subplots(figsize=(12, 5))
    for name, df in dfs.items():
        if "cpu_cores" not in df.columns:
            continue
        cfg      = EXPERIMENTS[name]
        smoothed = df["cpu_cores"].rolling(5, min_periods=1).mean()
        ax.plot(df["second_min"], smoothed,
                label=cfg["label"], color=cfg["color"], linestyle=cfg["style"])
    ax.set_title("CPU Cores Used Over Time")
    ax.set_xlabel("Time (minutes)")
    ax.set_ylabel("CPU Cores")
    ax.legend()
    ax.set_ylim(bottom=0)
    out = PLOTS_DIR / "cpu_cores.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out}")


# ─────────────────────────────────────────────────────────────────────
# Plot 3 — Summary bar chart: avg latency + SLO violations
# ─────────────────────────────────────────────────────────────────────

def plot_summary_bars(dfs: dict):
    names  = list(dfs.keys())
    labels = [EXPERIMENTS[n]["label"] for n in names]
    colors = [EXPERIMENTS[n]["color"] for n in names]

    avg_latencies  = []
    slo_violations = []

    for name in names:
        df   = dfs[name]
        lats = df["p99_latency_ms"]
        avg_latencies.append(lats.mean())
        slo_violations.append((lats > 500).sum())

    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    fig.suptitle("Experiment Summary Comparison", fontsize=14, fontweight="bold")

    axes[0].bar(labels, avg_latencies, color=colors, edgecolor="white", width=0.5)
    axes[0].axhline(500, color="black", linestyle=":", linewidth=1.2,
                    label=f"SLO = {500}ms")
    axes[0].set_title("Average P99 Latency")
    axes[0].set_ylabel("ms")
    axes[0].legend(fontsize=9)

    axes[1].bar(labels, slo_violations, color=colors, edgecolor="white", width=0.5)
    axes[1].set_title(f"Request Batches with P99 > {500}ms")
    axes[1].set_ylabel("Request Batches")

    for ax in axes:
        ax.tick_params(axis="x", rotation=10)

    out = PLOTS_DIR / "summary_bar.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out}")


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    print("Loading experiment results...")
    dfs = load_summaries()

    if not dfs:
        print("\nNo results found. Run experiments first:\n"
              "  cd experiments && ./run_hpa_70.sh\n"
              "  cd experiments && ./run_hpa_90.sh\n"
              "  cd experiments && ./run_custom.sh")
        return

    print(f"\nGenerating plots → {PLOTS_DIR}")
    plot_p99_latency(dfs)
    plot_cpu_cores(dfs)
    plot_summary_bars(dfs)

    print(f"Done. Open {PLOTS_DIR} to view the graphs.")


if __name__ == "__main__":
    main()