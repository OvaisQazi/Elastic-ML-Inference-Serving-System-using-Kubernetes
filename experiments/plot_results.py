"""
plot_results.py
---------------
Reads summary CSVs from all three experiments and generates
comparison graphs for the report.

Graphs produced (saved to experiments/results/plots/):
  1. p99_latency.png   — p99 latency over time, all 3 experiments
  2. throughput.png    — successful requests/s over time
  3. dropped.png       — dropped + timeout requests over time
  4. replicas.png      — replica count over time
  5. cpu_cores.png     — CPU cores used over time
  6. summary_bar.png   — bar chart: overall p99, drop rate, SLO violations

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

SLO_MS = 400


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
    ax.axhline(SLO_MS, color="black", linestyle=":", linewidth=1.2,
               label=f"SLO = {SLO_MS}ms")
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
# Plot 2 — Throughput
# ─────────────────────────────────────────────────────────────────────

def plot_throughput(dfs: dict):
    fig, ax = plt.subplots(figsize=(12, 5))
    first_df = next(iter(dfs.values()))
    ax.fill_between(first_df["second_min"], first_df["scheduled_qps"],
                    alpha=0.1, color="gray", label="Scheduled QPS")
    for name, df in dfs.items():
        cfg      = EXPERIMENTS[name]
        smoothed = df["throughput_rps"].rolling(5, min_periods=1).mean()
        ax.plot(df["second_min"], smoothed,
                label=cfg["label"], color=cfg["color"], linestyle=cfg["style"])
    ax.set_title("Throughput (Successful Requests/s)")
    ax.set_xlabel("Time (minutes)")
    ax.set_ylabel("Requests/s")
    ax.legend()
    ax.set_ylim(bottom=0)
    out = PLOTS_DIR / "throughput.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out}")


# ─────────────────────────────────────────────────────────────────────
# Plot 3 — Dropped + timeouts
# ─────────────────────────────────────────────────────────────────────

def plot_dropped(dfs: dict):
    fig, ax = plt.subplots(figsize=(12, 5))
    for name, df in dfs.items():
        cfg      = EXPERIMENTS[name]
        lost     = df["dropped"] + df["timeouts"]
        smoothed = lost.rolling(5, min_periods=1).mean()
        ax.plot(df["second_min"], smoothed,
                label=cfg["label"], color=cfg["color"], linestyle=cfg["style"])
    ax.set_title("Lost Requests Over Time (Dropped + Timeouts)")
    ax.set_xlabel("Time (minutes)")
    ax.set_ylabel("Lost Requests/s")
    ax.legend()
    ax.set_ylim(bottom=0)
    out = PLOTS_DIR / "dropped.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out}")


# ─────────────────────────────────────────────────────────────────────
# Plot 4 — Replica count over time
# ─────────────────────────────────────────────────────────────────────

def plot_replicas(dfs: dict):
    fig, ax = plt.subplots(figsize=(12, 5))
    for name, df in dfs.items():
        if "replicas" not in df.columns:
            continue
        cfg      = EXPERIMENTS[name]
        smoothed = df["replicas"].rolling(3, min_periods=1).mean()
        ax.plot(df["second_min"], smoothed,
                label=cfg["label"], color=cfg["color"], linestyle=cfg["style"])
    ax.set_title("Replica Count Over Time")
    ax.set_xlabel("Time (minutes)")
    ax.set_ylabel("Number of Replicas")
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.legend()
    ax.set_ylim(bottom=0)
    out = PLOTS_DIR / "replicas.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out}")


# ─────────────────────────────────────────────────────────────────────
# Plot 5 — CPU cores over time
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
# Plot 6 — Summary bar chart
# ─────────────────────────────────────────────────────────────────────

def plot_summary_bars(dfs: dict):
    names  = list(dfs.keys())
    labels = [EXPERIMENTS[n]["label"] for n in names]
    colors = [EXPERIMENTS[n]["color"] for n in names]

    overall_p99    = []
    drop_rates     = []
    slo_violations = []

    for name in names:
        df    = dfs[name]
        lats  = df["p99_latency_ms"]
        ok    = df["ok"].sum()
        lost  = (df["dropped"] + df["timeouts"]).sum()
        total = ok + lost
        overall_p99.append(lats.quantile(0.99))
        drop_rates.append((lost / total * 100) if total > 0 else 0)
        slo_violations.append((lats > SLO_MS).sum())

    fig, axes = plt.subplots(1, 3, figsize=(14, 5))
    fig.suptitle("Experiment Summary Comparison", fontsize=14, fontweight="bold")

    axes[0].bar(labels, overall_p99, color=colors, edgecolor="white", width=0.5)
    axes[0].axhline(SLO_MS, color="black", linestyle=":", linewidth=1.2,
                    label=f"SLO={SLO_MS}ms")
    axes[0].set_title("Overall P99 Latency")
    axes[0].set_ylabel("ms")
    axes[0].legend(fontsize=9)

    axes[1].bar(labels, drop_rates, color=colors, edgecolor="white", width=0.5)
    axes[1].set_title("Request Loss Rate")
    axes[1].set_ylabel("%")
    axes[1].yaxis.set_major_formatter(ticker.FormatStrFormatter("%.1f%%"))

    axes[2].bar(labels, slo_violations, color=colors, edgecolor="white", width=0.5)
    axes[2].set_title("Seconds with P99 > SLO")
    axes[2].set_ylabel("Seconds")

    for ax in axes:
        ax.tick_params(axis="x", rotation=10)

    out = PLOTS_DIR / "summary_bar.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out}")


# ─────────────────────────────────────────────────────────────────────
# Print text summary table
# ─────────────────────────────────────────────────────────────────────

def print_comparison_table(dfs: dict):
    print(f"\n{'─'*70}")
    print(f"{'Metric':<30} {'HPA 70%':>12} {'HPA 90%':>12} {'Custom':>12}")
    print(f"{'─'*70}")

    rows = {
        "Overall P99 latency (ms)": [],
        "Avg latency (ms)":         [],
        "Max P99 latency (ms)":     [],
        "SLO violations (seconds)": [],
        "Total dropped":            [],
        "Total timeouts":           [],
        "Loss rate (%)":            [],
    }

    for name in ["hpa_70", "hpa_90", "custom"]:
        if name not in dfs:
            for k in rows:
                rows[k].append("N/A")
            continue
        df    = dfs[name]
        lats  = df["p99_latency_ms"]
        ok    = df["ok"].sum()
        drop  = df["dropped"].sum()
        tout  = df["timeouts"].sum()
        total = ok + drop + tout

        rows["Overall P99 latency (ms)"].append(f"{lats.quantile(0.99):.0f}")
        rows["Avg latency (ms)"].append(f"{df['avg_latency_ms'].mean():.0f}")
        rows["Max P99 latency (ms)"].append(f"{lats.max():.0f}")
        rows["SLO violations (seconds)"].append(f"{(lats > SLO_MS).sum()}")
        rows["Total dropped"].append(f"{drop}")
        rows["Total timeouts"].append(f"{tout}")
        rows["Loss rate (%)"].append(f"{(drop+tout)/total*100:.1f}%")

    for metric, values in rows.items():
        print(f"{metric:<30} {values[0]:>12} {values[1]:>12} {values[2]:>12}")
    print(f"{'─'*70}\n")


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
    plot_throughput(dfs)
    plot_dropped(dfs)
    plot_replicas(dfs)
    plot_cpu_cores(dfs)
    plot_summary_bars(dfs)

    print_comparison_table(dfs)
    print(f"Done. Open {PLOTS_DIR} to view the graphs.")


if __name__ == "__main__":
    main()