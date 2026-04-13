#!/bin/bash

echo "============================================"
echo "BACKING UP ORIGINAL FILES FIRST"
echo "============================================"

# Backup originals
cp ../consensus/src/timer.rs ../consensus/src/timer.rs.ORIGINAL_BACKUP
cp ../network/src/simple_sender.rs ../network/src/simple_sender.rs.ORIGINAL_BACKUP

echo "✅ Backups created"
echo ""
echo "Starting experiments..."

# Create results file
echo "Timeout,Network,Delay(ms),TPS,Latency(ms)" > results.csv

# Test configurations
declare -a NETWORKS=("local" "regional" "global")
declare -a DELAYS=("50" "200" "500")
declare -a TIMEOUTS=("fixed" "adaptive")

for i in {0..2}; do
    NETWORK=${NETWORKS[$i]}
    DELAY=${DELAYS[$i]}
    
    echo ""
    echo "=========================================="
    echo "NETWORK: $NETWORK (0-${DELAY}ms jitter)"
    echo "=========================================="
    
    for TIMEOUT in "${TIMEOUTS[@]}"; do
        echo ""
        echo "  Testing: $TIMEOUT timeout..."
        
        # Copy the right files
        cp ../consensus/src/timer_${TIMEOUT}.rs ../consensus/src/timer.rs
        cp ../network/src/simple_sender_${NETWORK}.rs ../network/src/simple_sender.rs
        
        # Build
        echo "    Building..."
        cargo build --release --quiet
        
        # Run test
        echo "    Running benchmark..."
        fab local > test_output.txt 2>&1
        
        # Extract results
        TPS=$(grep "Consensus TPS:" test_output.txt | awk '{print $3}')
        LAT=$(grep "End-to-end latency:" test_output.txt | awk '{print $3}')
        
        echo "    Result: $TPS TPS, $LAT latency"
        echo "$TIMEOUT,$NETWORK,$DELAY,$TPS,$LAT" >> results.csv
        
        sleep 2
    done
done

echo ""
echo "============================================"
echo "RESTORING ORIGINAL FILES"
echo "============================================"

# Restore originals
cp ../consensus/src/timer.rs.ORIGINAL_BACKUP ../consensus/src/timer.rs
cp ../network/src/simple_sender.rs.ORIGINAL_BACKUP ../network/src/simple_sender.rs

echo "✅ Original files restored"
echo ""
echo "============================================"
echo "ALL EXPERIMENTS COMPLETE!"
echo "============================================"
echo ""
echo "Results:"
column -t -s',' results.csv

rm test_output.txt
