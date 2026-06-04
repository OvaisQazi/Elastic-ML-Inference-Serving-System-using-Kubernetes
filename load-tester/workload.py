"""
workload.py
-----------
Provides the QPS (queries per second) schedule from the professor's trace.
Each value in the trace = number of requests to send in that second.

Usage:
    from workload import get_qps_at

    qps = get_qps_at(second=10)   # returns QPS for second 10
    for second, qps in enumerate(TRACE):
        ...
"""

# ── Professor's workload trace ────────────────────────────────────────
# Each value = QPS for that second of the experiment
# Total duration = len(TRACE) seconds
TRACE = [
    7, 6, 7, 6, 7, 8, 7, 7, 7, 8, 6, 9, 9, 7, 7, 9, 7, 7, 8, 8,
    8, 7, 6, 7, 5, 7, 8, 10, 7, 5, 8, 7, 8, 6, 8, 6, 7, 8, 6, 8,
    7, 7, 6, 6, 6, 7, 8, 6, 6, 6, 6, 5, 7, 7, 7, 8, 8, 8, 6, 5,
    9, 6, 7, 6, 7, 7, 6, 8, 8, 8, 5, 8, 8, 7, 6, 5, 8, 6, 4, 5,
    7, 6, 6, 7, 6, 7, 5, 6, 6, 6, 6, 8, 6, 7, 7, 8, 6, 6, 5, 7,
    7, 7, 8, 8, 7, 5, 7, 6, 6, 6, 6, 8, 7, 7, 8, 8, 6, 7, 8, 7,
    10, 6, 8, 7, 8, 6, 6, 7, 7, 9, 6, 7, 9, 8, 7, 7, 8, 6, 5, 6,
    8, 7, 8, 6, 7, 6, 8, 6, 6, 9, 6, 9, 8, 9, 7, 6, 9, 8, 8, 10,
    7, 8, 7, 6, 8, 7, 5, 6, 6, 6, 7, 7, 8, 6, 7, 5, 7, 6, 9, 6,
    6, 7, 9, 5, 10, 6, 6, 8, 5, 5, 8, 8, 7, 6, 6, 9, 8, 8, 9, 7,
    10, 8, 6, 8, 8, 6, 6, 7, 5, 7, 10, 9, 6, 8, 8, 5, 8, 9, 8, 8,
    7, 8, 9, 6, 8, 7, 7, 7, 8, 7, 9, 10, 6, 7, 8, 7, 7, 8, 7, 7,
    7, 7, 6, 7, 7, 7, 6, 9, 7, 6, 6, 7, 6, 8,
    # ── Spike region ─────────────────────────────────────────────────
    20, 17, 20, 28, 28, 30, 32, 31, 30, 36, 30, 32, 35, 31, 36, 31,
    35, 35, 37, 38, 36, 32, 32, 36, 38, 36, 35, 44, 36, 37, 36, 37,
    35, 37, 35, 38, 32, 36, 35, 33, 41, 34, 32, 36, 38, 41, 37, 42,
    37, 38, 44, 36, 35, 36, 36, 35, 39, 37, 37, 37, 33, 40, 42, 38,
    36, 33, 41, 43, 37, 33, 41, 42, 35, 37, 36, 35, 35, 35, 32, 38,
    38, 41, 35, 35, 38, 38, 40, 38, 43, 40, 36, 41, 39, 33, 37, 35,
    32, 31, 36, 34, 30, 32, 32, 32, 30, 35, 34, 31, 30, 33, 37, 30,
    30, 34, 31, 34, 33, 34, 32, 33, 36, 33, 29, 32, 33, 34, 37, 34,
    37, 31, 33, 32, 37, 33, 33, 36, 38, 36, 32, 34, 34, 32, 35, 35,
    39, 32, 35, 39, 31, 36, 38, 37, 34, 36, 37, 33, 35, 34, 33, 35,
    34, 31, 33, 33,
    # ── Ramp down ────────────────────────────────────────────────────
    29, 25, 27, 28, 28, 25, 26, 30, 28, 28, 32, 29, 28, 24, 27, 22,
    24, 27, 20, 18, 20, 21, 17, 20, 19, 19, 19, 17, 20, 18, 18, 20,
    19, 18, 20, 22, 16, 19, 16, 14, 13, 15, 12, 18, 19, 20, 21, 19,
    18, 18, 18, 14, 16, 14, 15, 14, 12, 12, 13, 12, 12, 14, 13, 11,
    11, 10, 7, 7, 11, 9, 9, 6, 7, 8, 8, 8, 8, 6, 8, 9, 7, 6, 7,
    9, 9, 8, 8, 7, 11, 8, 7, 8, 6, 8, 7, 9, 9, 7, 7, 7, 7, 10, 6,
    9, 7, 7, 7, 8, 9, 7, 10, 7, 6, 7, 7, 6, 6, 9, 8, 8, 6, 7, 10,
    8, 10, 7, 7, 7, 9, 7, 8, 6, 5, 7, 7, 8, 7, 7, 8, 9, 5, 8, 8,
    7, 8, 8, 9, 8, 9, 8, 9, 9, 8, 8, 8, 8, 8, 9, 7, 8, 9, 7, 7,
    6, 6, 8, 10, 8, 8, 7, 7, 7, 10, 5, 8, 6, 6, 8, 7, 7, 8, 8, 9,
    9, 7, 7, 8, 9, 9, 8, 10, 8, 8, 5, 10, 7, 9, 9, 7, 10, 7, 6, 8,
    11, 8, 7, 8, 9, 6, 7, 7, 8,
]

DURATION_S   = len(TRACE)          # total experiment duration in seconds
MAX_QPS      = max(TRACE)          # 44
MIN_QPS      = min(TRACE)          # 4
AVG_QPS      = sum(TRACE) / len(TRACE)

# Identify the spike region for reporting
SPIKE_START  = next(i for i, q in enumerate(TRACE) if q >= 20)
SPIKE_END    = max(i for i, q in enumerate(TRACE) if q >= 20)


def get_qps_at(second: int) -> int:
    """Return the QPS for a given second. Clamps to last value if out of range."""
    if second < 0:
        return TRACE[0]
    if second >= DURATION_S:
        return TRACE[-1]
    return TRACE[second]


def summary():
    print(f"Workload trace summary")
    print(f"  Total duration : {DURATION_S}s ({DURATION_S/60:.1f} min)")
    print(f"  Min QPS        : {MIN_QPS}")
    print(f"  Max QPS        : {MAX_QPS}")
    print(f"  Avg QPS        : {AVG_QPS:.1f}")
    print(f"  Spike region   : second {SPIKE_START}–{SPIKE_END} "
          f"({SPIKE_END - SPIKE_START}s)")
    print(f"  Total requests : {sum(TRACE)}")


if __name__ == "__main__":
    summary()