#!/bin/bash

echo "============================================"
echo "COMPREHENSIVE TIMEOUT COMPARISON"
echo "============================================"
echo "This will run:"
echo "  - 3 timeout strategies (Fixed, Exponential, Adaptive)"
echo "  - 3 network conditions (Local 50ms, Regional 200ms, Global 500ms)"
echo "  - 4 node configurations (4, 7, 10, 13 nodes)"
echo "  - 30 runs each"
echo "  - Total: 1,080 tests (~12-15 hours)"
echo ""
read -p "Press Enter to continue or Ctrl+C to cancel..."

# Backup originals
echo "Creating backups..."
cp ../consensus/src/timer.rs ../consensus/src/timer.rs.BACKUP
cp ../network/src/simple_sender.rs ../network/src/simple_sender.rs.BACKUP
cp fabfile.py fabfile.py.BACKUP

# Create results file
echo "Timeout,Network,Delay_ms,Nodes,Run,Consensus_TPS,Consensus_Latency_ms,E2E_TPS,E2E_Latency_ms" > comprehensive_results.csv

# Test configurations
TIMEOUTS=("fixed" "exponential" "adaptive")
NETWORKS=("local:50" "regional:200" "global:500")
NODE_COUNTS=(4 7 10 13)
RUNS=30

total_tests=$((${#TIMEOUTS[@]} * ${#NETWORKS[@]} * ${#NODE_COUNTS[@]} * RUNS))
current_test=0
start_time=$(date +%s)

for nodes in "${NODE_COUNTS[@]}"; do
    for timeout in "${TIMEOUTS[@]}"; do
        for network_config in "${NETWORKS[@]}"; do
            IFS=':' read -r network delay <<< "$network_config"
            
            echo ""
            echo "========================================"
            echo "Testing: $nodes nodes, $timeout timeout, $network network (0-${delay}ms)"
            echo "Progress: $current_test/$total_tests tests completed"
            
            # Calculate ETA
            if [ $current_test -gt 0 ]; then
                elapsed=$(($(date +%s) - start_time))
                avg_time_per_test=$((elapsed / current_test))
                remaining_tests=$((total_tests - current_test))
                eta_seconds=$((avg_time_per_test * remaining_tests))
                eta_hours=$((eta_seconds / 3600))
                eta_mins=$(((eta_seconds % 3600) / 60))
                echo "ETA: ${eta_hours}h ${eta_mins}m remaining"
            fi
            echo "========================================"
            
            # Set the timeout strategy
            cp ../consensus/src/timer_${timeout}.rs ../consensus/src/timer.rs
            
            # Set the network delay
            cp ../network/src/simple_sender_${network}.rs ../network/src/simple_sender.rs
            
            # Modify fabfile.py to use correct number of nodes (only first occurrence)
            sed -i "0,/\"nodes\": [0-9]*/s//\"nodes\": $nodes/" fabfile.py
            
            # Build once per configuration
            echo "Building..."
            cargo build --release --quiet 2>&1 | tail -1
            
            # Run 30 times
            for run in $(seq 1 $RUNS); do
                current_test=$((current_test + 1))
                printf "  Run %2d/%d... " $run $RUNS
                
                # Run benchmark
                fab local > temp_output.txt 2>&1
                
                # Extract metrics
                CONS_TPS=$(grep "Consensus TPS:" temp_output.txt | awk '{print $3}' | tr -d ',')
                CONS_LAT=$(grep "Consensus latency:" temp_output.txt | awk '{print $3}' | tr -d ',')
                E2E_TPS=$(grep "End-to-end TPS:" temp_output.txt | awk '{print $3}' | tr -d ',')
                E2E_LAT=$(grep "End-to-end latency:" temp_output.txt | awk '{print $3}' | tr -d ',')
                
                # Save to CSV
                echo "$timeout,$network,$delay,$nodes,$run,$CONS_TPS,$CONS_LAT,$E2E_TPS,$E2E_LAT" >> comprehensive_results.csv
                
                echo "$E2E_TPS TPS, ${E2E_LAT}ms"
                
                sleep 0.5
            done
            
            # Restore fabfile for next iteration
            cp fabfile.py.BACKUP fabfile.py
        done
    done
done

# Restore all originals
echo ""
echo "Restoring original files..."
cp ../consensus/src/timer.rs.BACKUP ../consensus/src/timer.rs
cp ../network/src/simple_sender.rs.BACKUP ../network/src/simple_sender.rs
cp fabfile.py.BACKUP fabfile.py

# Calculate statistics
echo ""
echo "========================================"
echo "CALCULATING STATISTICS"
echo "========================================"

python3 << 'EOF'
import pandas as pd
import numpy as np

df = pd.read_csv('comprehensive_results.csv')

# Calculate statistics for each configuration
summary = df.groupby(['Nodes', 'Timeout', 'Network']).agg({
    'E2E_TPS': ['mean', 'std'],
    'E2E_Latency_ms': ['mean', 'std']
}).round(2)

print("\n" + "="*100)
print("SUMMARY RESULTS (Mean ± Std Dev over 30 runs)")
print("="*100)
print(summary.to_string())

# Save summary
summary.to_csv('summary_results.csv')

# Find best performer for each configuration
print("\n" + "="*100)
print("BEST PERFORMER BY CONFIGURATION")
print("="*100)

for nodes in sorted(df['Nodes'].unique()):
    for network in sorted(df['Network'].unique()):
        subset = df[(df['Nodes'] == nodes) & (df['Network'] == network)]
        grouped = subset.groupby('Timeout')['E2E_TPS'].mean()
        best = grouped.idxmax()
        improvement = ((grouped[best] - grouped['fixed']) / grouped['fixed'] * 100)
        print(f"{nodes} nodes, {network:8s}: {best:12s} wins with {grouped[best]:.1f} TPS (+{improvement:.1f}% vs fixed)")

print("\n✅ Detailed results: comprehensive_results.csv")
print("✅ Summary statistics: summary_results.csv")
EOF

rm temp_output.txt

total_time=$(($(date +%s) - start_time))
hours=$((total_time / 3600))
mins=$(((total_time % 3600) / 60))

echo ""
echo "========================================"
echo "ALL TESTS COMPLETE!"
echo "Total time: ${hours}h ${mins}m"
echo "========================================"
