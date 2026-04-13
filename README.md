# RTTstuff — Adaptive Timeouts for HotStuff BFT Consensus

[![build status](https://img.shields.io/github/actions/workflow/status/asonnino/hotstuff/rust.yml?style=flat-square&logo=GitHub&logoColor=white)](https://github.com/asonnino/hotstuff/actions)
[![rustc](https://img.shields.io/badge/rustc-1.64+-blue?style=flat-square&logo=rust)](https://www.rust-lang.org)
[![python](https://img.shields.io/badge/python-3.9-blue?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/release/python-390/)
[![license](https://img.shields.io/badge/license-Apache-blue.svg?style=flat-square)](LICENSE)

This repository extends the [2-chain HotStuff BFT consensus protocol](https://arxiv.org/abs/2106.10362) with **TCP-inspired adaptive round timeouts**, replacing the static timeout used in the original implementation. The core contribution is a Jacobson/Karels EWMA algorithm — the same technique that powers TCP retransmission timing — applied to consensus round duration estimation.

The result: **96.7% success rate** and **681 ± 162 TPS** under variable-latency conditions, compared to **46.7% success** and **301 ± 308 TPS** with fixed timeouts. Failure detection is **64.5% faster** under realistic failure conditions.

---

## The Problem

HotStuff consensus liveness depends critically on timeout calibration. A timeout is the mechanism by which nodes detect a failed or slow leader and trigger a view change to elect a new one.

**Fixed timeouts break in both directions:**

- **Too short** → legitimate rounds get falsely timed out. Each false timeout triggers a view change, which itself consumes bandwidth and delays the next leader, who can also time out. The cascade compounds and the system can collapse entirely.
- **Too long** → actual leader failures take forever to detect. Throughput stalls while nodes wait out the full timeout before recovery begins.

In a network with variable latency — any realistic WAN deployment — there is no single fixed value that works well. This is the same problem TCP solved in 1988 with the Jacobson/Karels algorithm.

---

## The Solution: EWMA Adaptive Timeouts

Each node independently estimates the current round-trip time using an exponential weighted moving average and sets its timeout as a function of both the estimate and its variance:

```
EstimatedRTT = (1 - α) × EstimatedRTT + α × SampleRTT
DevRTT       = (1 - β) × DevRTT       + β × |SampleRTT - EstimatedRTT|
Timeout      = EstimatedRTT + 4 × DevRTT
```

### Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| α | 0.125 | Converges in 5–10 rounds; smooth, non-oscillating |
| β | 0.25 | Reacts faster to variance changes than the mean |
| Factor K | 4 | Covers 99.997% of legitimate rounds (only 3 per 100,000 exceed timeout) |
| Min timeout | 1500 ms | Guards against underestimation during warm-up |
| Max timeout | 30,000 ms | Caps recovery time in extreme conditions |

**Why K=4?** Based on the standard normal distribution, a multiplier of K=1 allows 16% false timeouts, K=2 allows 2.3%, K=3 allows 0.13%, and K=4 reduces false timeouts to 0.003% — effectively eliminating false positives while keeping the timeout tight enough to detect real failures quickly.

**Why α=0.125?** A smaller α (e.g. 0.01) takes 50+ rounds to adapt and gets stuck on stale estimates. A larger α (e.g. 0.5) oscillates wildly on every measurement. At 0.125, the estimate adapts in 5–10 rounds and remains stable.

### How It Integrates

The timer hooks into three points in the consensus protocol:

- `start_round()` — called when a new round begins (on boot, on `advance_round`, on timeout)
- `on_round_complete()` — called in `process_qc()` when a quorum certificate is formed, signalling that the round completed successfully. This is where the EWMA update happens.
- `reset()` — arms the sleep timer for the current estimated timeout

This means the timeout adapts continuously based on actual observed round durations, not a static guess.

---

## Timeout Strategies Compared

Three strategies are implemented and evaluated side-by-side:

| Strategy | File | Behaviour |
|----------|------|-----------|
| **Adaptive** (default) | `consensus/src/timer.rs` | TCP-style EWMA; adjusts every round |
| Fixed | `consensus/src/timer_fixed.rs` | Always 5000 ms, regardless of conditions |
| Exponential Backoff | `consensus/src/timer_exponential.rs` | Doubles on timeout, resets to base on success |

To switch strategies, swap the `timer.rs` implementation with one of the alternatives and recompile.

---

## Experimental Results

All experiments ran on 13-node committees. Network conditions were varied by injecting artificial per-message delay drawn uniformly from [0, 200ms] into the `SimpleSender`, simulating realistic WAN jitter.

### Throughput & Stability (1,080 trials)

| Strategy | Success Rate | TPS (mean ± std) | Latency |
|----------|-------------|-------------------|---------|
| Fixed | 46.7% (14/30) | 301 ± 308 | High variance |
| Exponential | 50.0% (15/30) | 350 ± 280 | Unstable |
| **Adaptive** | **96.7% (29/30)** | **681 ± 162** | Stable |

Statistical significance: **p < 0.001**

### Failure Detection & Recovery

Experiments injected controlled leader failures at known times and measured how long the remaining nodes took to detect the failure and resume committing blocks.

| Scenario | Fixed Detection | Adaptive Detection | Improvement |
|----------|----------------|-------------------|-------------|
| Baseline (no failures) | 2843 ± 736 TPS | 2793 ± 795 TPS | No difference (p = 0.84) |
| Realistic (1 failure at 150s) | 6190 ms | 2198 ms | **64.5% faster** |
| Stress (4 failures, 60s intervals) | 5240 ms | 2297 ms | **56.2% faster** |

The baseline result is important: adaptive timeouts impose **no overhead** under normal operation. The gains appear entirely under stress.

### Why Adaptive Wins

Under variable latency, the adaptive timer observes rounds completing in ~900–1200 ms and converges to a timeout of ~1800 ms. Legitimately slow rounds (1100 ms) still complete successfully because the timeout has headroom from the 4 × DevRTT term. Fixed timeouts set at 1000 ms misfire on those slow rounds, triggering the cascade failure described above.

---

## Failure Injection Infrastructure

A full experiment harness is included in `benchmark/`:

- **`failure_injection.py`** — `NodeKiller` class: kills and restarts specific nodes by terminating their tmux sessions. Supports targeting by node ID or by round-robin leader slot.
- **`failure_log_parser.py`** — `FailureLogParser`: parses node logs for `Timeout reached`, `Moved to round`, and `Committed B` events; computes detection latency, view-change duration, and total recovery time.
- **`failure_experiment.py`** — `FailureExperiment`: orchestrates full experiment runs across three scenarios:
  - **Baseline**: no failures
  - **Realistic**: single leader failure at 150 s
  - **Stress**: four leader failures at 60 s intervals
- **`run_failure_experiments.sh`** — shell driver for the full experiment suite
- **`run_comprehensive_tests.sh`** — tests all timeout strategies across all scenarios
- **`analyze_timeouts.py`** — statistical analysis and plot generation

### Running Failure Experiments

```bash
cd benchmark
pip install -r requirements.txt
python failure_experiment.py
```

Results are written to `failure_results/` as CSV files. A summary is printed to stdout.

---

## Quick Start

Build and run a local 13-node benchmark:

```bash
git clone https://github.com/Prakhar-Sethi/RTTstuff.git
cd RTTstuff/benchmark
pip install -r requirements.txt
fab local
```

You will also need Clang (required by RocksDB) and [tmux](https://linuxize.com/post/getting-started-with-tmux/#installing-tmux).

Expected output:

```
-----------------------------------------
 SUMMARY:
-----------------------------------------
 + CONFIG:
 Faults: 0 nodes
 Committee size: 13 nodes
 Input rate: 1,000 tx/s
 Transaction size: 512 B
 Execution time: 20 s

 Consensus timeout delay: 1,000 ms
 Consensus sync retry delay: 10,000 ms
 ...

 + RESULTS:
 Consensus TPS: ~680 tx/s
 End-to-end latency: ~15 ms
-----------------------------------------
```

---

## Repository Structure

```
.
├── consensus/src/
│   ├── core.rs              # Main consensus loop; timer hooks wired here
│   ├── timer.rs             # Adaptive EWMA timer (active)
│   ├── timer_fixed.rs       # Fixed 5000ms timer (comparison)
│   ├── timer_exponential.rs # Exponential backoff timer (comparison)
│   ├── messages.rs          # Block, Vote, QC, Timeout, TC types
│   ├── aggregator.rs        # QC and TC assembly
│   ├── proposer.rs          # Block proposal and broadcast
│   └── synchronizer.rs      # Block sync for view changes
├── network/src/
│   ├── simple_sender.rs     # Best-effort sender with jitter simulation
│   ├── simple_sender_local.rs    # Local (0ms) latency profile
│   ├── simple_sender_regional.rs # Regional (~50ms) latency profile
│   └── simple_sender_global.rs   # Global (~200ms) latency profile
├── benchmark/
│   ├── failure_experiment.py     # Experiment orchestration
│   ├── failure_injection.py      # Node kill/restart control
│   ├── failure_log_parser.py     # Log analysis and metric extraction
│   ├── analyze_timeouts.py       # Statistical analysis
│   ├── comprehensive_results.csv # Full experimental data
│   └── failure_results/          # Failure injection results
├── mempool/                 # Transaction batching and distribution
├── store/                   # RocksDB storage layer
├── crypto/                  # Ed25519 cryptography
└── node/                    # Binary entry point
```

---

## Background

This work builds on the [2-chain HotStuff implementation](https://github.com/asonnino/hotstuff) by Alberto Sonnino. The base protocol is unchanged; this repository contributes only the adaptive timeout mechanism, the comparative timer implementations, and the failure injection experimental infrastructure.

The timeout problem in BFT consensus is a documented open issue — see [Flow issue #3022](https://github.com/onflow/flow-go/issues/3022) for a real-world example of cascade timeout failures in a production BFT system.

---

## License

Apache 2.0. See [LICENSE](LICENSE).
