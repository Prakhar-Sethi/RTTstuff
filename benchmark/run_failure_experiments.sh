#!/bin/bash

# Failure Injection Experiment Automation Script
# Runs complete failure injection experiments with both fixed and adaptive timeouts

echo "============================================"
echo "FAILURE INJECTION EXPERIMENTS"
echo "============================================"
echo "Configuration:"
echo "  - 3 scenarios (baseline, realistic, stress)"
echo "  - 2 timeout strategies (fixed, adaptive)"
echo "  - 20 trials each"
echo "  - Total: 120 experiments (~10 hours)"
echo ""
echo "Scenarios:"
echo "  • Baseline: No failures (performance baseline)"
echo "  • Realistic: 1 failure at 150s (typical operations)"
echo "  • Stress: 2 failures at 100s & 200s (degraded conditions)"
echo ""
read -p "Press Enter to continue or Ctrl+C to cancel..."

# Paths
TIMER_FIXED="../consensus/src/timer_fixed.rs"
TIMER_ADAPTIVE="../consensus/src/timer.rs"
TIMER_TARGET="../consensus/src/timer.rs"

# Check required files exist
if [ ! -f "$TIMER_FIXED" ]; then
    echo "❌ ERROR: $TIMER_FIXED not found!"
    echo "Please create timer_fixed.rs with fixed timeout implementation"
    exit 1
fi

if [ ! -f "$TIMER_ADAPTIVE" ]; then
    echo "❌ ERROR: $TIMER_ADAPTIVE not found!"
    exit 1
fi

# Backup original files
echo "Creating backups..."
cp ../consensus/src/timer.rs ../consensus/src/timer.rs.BACKUP_$(date +%s)
cp benchmark/failure_experiment.py ./

# Install Python dependencies
echo "Checking Python environment..."
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate
pip install -q pandas numpy matplotlib 2>/dev/null || true

# Create output directory
mkdir -p failure_results
OUTPUT_CSV="failure_results/failure_experiments_$(date +%Y%m%d_%H%M%S).csv"

# Initialize CSV
echo "scenario,timeout_strategy,trial,success,failures_injected,avg_detection_latency_ms,avg_recovery_time_ms,throughput_tps" > "$OUTPUT_CSV"

# Experiment parameters
SCENARIOS=("baseline" "realistic" "stress")
STRATEGIES=("fixed" "adaptive")
TRIALS=20

total_tests=$((${#SCENARIOS[@]} * ${#STRATEGIES[@]} * TRIALS))
current_test=0
start_time=$(date +%s)

echo ""
echo "========================================"
echo "STARTING EXPERIMENTS"
echo "========================================"

for strategy in "${STRATEGIES[@]}"; do
    echo ""
    echo "========================================"
    echo "TIMEOUT STRATEGY: ${strategy^^}"
    echo "========================================"
    
    # Switch timeout implementation
    if [ "$strategy" = "fixed" ]; then
        echo "📝 Switching to fixed timeout (5000ms)..."
        cp "$TIMER_FIXED" "$TIMER_TARGET"
    else
        echo "📝 Switching to adaptive timeout (EWMA)..."
        cp "$TIMER_ADAPTIVE" "$TIMER_TARGET"
    fi
    
    # Rebuild with new timeout strategy
    echo "🔨 Rebuilding..."
    cd ../node
    cargo build --release --quiet
    cd ../benchmark
    
    for scenario in "${SCENARIOS[@]}"; do
        echo ""
        echo "----------------------------------------"
        echo "SCENARIO: ${scenario^^}"
        echo "----------------------------------------"
        
        for trial in $(seq 1 $TRIALS); do
            current_test=$((current_test + 1))
            
            # Calculate ETA
            if [ $current_test -gt 1 ]; then
                elapsed=$(($(date +%s) - start_time))
                avg_time=$((elapsed / (current_test - 1)))
                remaining=$((total_tests - current_test))
                eta_sec=$((avg_time * remaining))
                eta_min=$((eta_sec / 60))
                echo "Trial $trial/$TRIALS (Test $current_test/$total_tests, ETA: ${eta_min}m)"
            else
                echo "Trial $trial/$TRIALS (Test $current_test/$total_tests)"
            fi
            
            # Run experiment using Python
            python3 << PYTHON_SCRIPT
import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'benchmark')

from failure_experiment import FailureExperiment
from failure_injection import ALL_SCENARIOS
from benchmark.config import BenchParameters, NodeParameters

# Configuration
bench_params = {
    'nodes': [13],
    'rate': [1000],
    'tx_size': 512,
    'duration': 300,
    'faults': 0
}

node_params = {
    'consensus': {
        'timeout_delay': 5000,
        'sync_retry_delay': 5000,
    },
    'mempool': {
        'gc_depth': 50,
        'sync_retry_delay': 5000,
        'sync_retry_nodes': 3,
        'batch_size': 500_000,
        'max_batch_delay': 100,
    },
}

scenario = ALL_SCENARIOS['${scenario}']
experiment = FailureExperiment(bench_params, node_params, scenario)

try:
    results = experiment.run(debug=False)
    
    # Extract metrics
    success = results.get('success', False)
    failures = results.get('failures_injected', 0)
    detection = results.get('avg_detection_latency_ms', 0)
    recovery = results.get('avg_recovery_time_ms', 0)
    throughput = results.get('throughput_tps', 0)
    
    # Print for bash to capture
    print(f"{success},{failures},{detection},{recovery},{throughput}")
    
except Exception as e:
    print(f"False,0,0,0,0")
    import traceback
    traceback.print_exc()
PYTHON_SCRIPT
            
            # Capture Python output
            read success failures detection recovery throughput <<< $(python3 -c "
import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'benchmark')
from failure_experiment import FailureExperiment
from failure_injection import ALL_SCENARIOS
from benchmark.config import BenchParameters, NodeParameters

bench_params = {'nodes': [13], 'rate': [1000], 'tx_size': 512, 'duration': 300, 'faults': 0}
node_params = {'consensus': {'timeout_delay': 5000, 'sync_retry_delay': 5000}, 'mempool': {'gc_depth': 50, 'sync_retry_delay': 5000, 'sync_retry_nodes': 3, 'batch_size': 500_000, 'max_batch_delay': 100}}

scenario = ALL_SCENARIOS['$scenario']
exp = FailureExperiment(bench_params, node_params, scenario)

try:
    res = exp.run(debug=False)
    print(f\"{res.get('success', False)},{res.get('failures_injected', 0)},{res.get('avg_detection_latency_ms', 0)},{res.get('avg_recovery_time_ms', 0)},{res.get('throughput_tps', 0)}\")
except:
    print('False,0,0,0,0')
" 2>&1 | tail -1)
            
            # Append to CSV
            echo "${scenario},${strategy},${trial},${success},${failures},${detection},${recovery},${throughput}" >> "$OUTPUT_CSV"
            
            echo "  ✅ Detection: ${detection}ms, Recovery: ${recovery}ms, TPS: ${throughput}"
            
            # Brief pause between trials
            sleep 2
        done
    done
done

# Restore original timer
echo ""
echo "Restoring original timer.rs..."
latest_backup=$(ls -t ../consensus/src/timer.rs.BACKUP_* 2>/dev/null | head -1)
if [ -n "$latest_backup" ]; then
    cp "$latest_backup" ../consensus/src/timer.rs
fi

# Generate summary statistics
echo ""
echo "========================================"
echo "GENERATING SUMMARY"
echo "========================================"

python3 << 'PYTHON_SUMMARY'
import pandas as pd
import sys

try:
    df = pd.read_csv('${OUTPUT_CSV}')
    
    print("\n" + "="*80)
    print("FAILURE DETECTION & RECOVERY SUMMARY")
    print("="*80)
    
    summary = df.groupby(['scenario', 'timeout_strategy']).agg({
        'avg_detection_latency_ms': ['mean', 'std', 'min', 'max'],
        'avg_recovery_time_ms': ['mean', 'std', 'min', 'max'],
        'throughput_tps': ['mean', 'std']
    }).round(2)
    
    print(summary.to_string())
    
    # Find improvements
    print("\n" + "="*80)
    print("ADAPTIVE VS FIXED COMPARISON")
    print("="*80)
    
    for scenario in df['scenario'].unique():
        subset = df[df['scenario'] == scenario]
        fixed = subset[subset['timeout_strategy'] == 'fixed']
        adaptive = subset[subset['timeout_strategy'] == 'adaptive']
        
        if len(fixed) > 0 and len(adaptive) > 0:
            det_fixed = fixed['avg_detection_latency_ms'].mean()
            det_adaptive = adaptive['avg_detection_latency_ms'].mean()
            improvement = ((det_fixed - det_adaptive) / det_fixed * 100) if det_fixed > 0 else 0
            
            print(f"\n{scenario.upper()}:")
            print(f"  Fixed detection:    {det_fixed:.1f}ms")
            print(f"  Adaptive detection: {det_adaptive:.1f}ms")
            print(f"  Improvement:        {improvement:.1f}% faster")
    
    print("\n✅ Results saved to: ${OUTPUT_CSV}")
    
except Exception as e:
    print(f"Error generating summary: {e}")
    import traceback
    traceback.print_exc()
PYTHON_SUMMARY

total_time=$(($(date +%s) - start_time))
hours=$((total_time / 3600))
mins=$(((total_time % 3600) / 60))

echo ""
echo "========================================"
echo "ALL EXPERIMENTS COMPLETE!"
echo "Total time: ${hours}h ${mins}m"
echo "Results: $OUTPUT_CSV"
echo "========================================"
