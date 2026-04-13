#!/bin/bash

echo "=========================================="
echo "TEST 1: Fixed Timeout + 200ms Network Delay"
echo "=========================================="

# Switch to fixed timeout
cd ../consensus/src
sed -i 's/if let Some(start_time) = self.round_start_time {/\/* if let Some(start_time) = self.round_start_time {/g' timer.rs
sed -i 's/^        }$/        } *\/\n        self.current_timeout = 1000;/g' timer.rs

# Build
cd ../../benchmark
cargo build --release 2>&1 | tail -3

# Add 200ms delay
sudo tc qdisc add dev lo root netem delay 200ms
echo "Added 200ms delay to loopback interface"
sleep 2

# Run test
fab local 2>&1 | tail -30

# Save results
cp -r logs logs_fixed_delay
echo "✅ Results saved to logs_fixed_delay/"

# Remove delay
sudo tc qdisc del dev lo root
echo "Delay removed"
sleep 3

echo ""
echo "=========================================="
echo "TEST 2: Adaptive Timeout + 200ms Network Delay"
echo "=========================================="

# Switch back to adaptive
cd ../consensus/src
cp timer.rs.WITH_ADAPTIVE timer.rs

# Build
cd ../../benchmark
cargo build --release 2>&1 | tail -3

# Add 200ms delay again
sudo tc qdisc add dev lo root netem delay 200ms
echo "Added 200ms delay to loopback interface"
sleep 2

# Run test
fab local 2>&1 | tail -30

# Save results
cp -r logs logs_adaptive_delay
echo "✅ Results saved to logs_adaptive_delay/"

# Remove delay
sudo tc qdisc del dev lo root
echo "Delay removed"

echo ""
echo "=========================================="
echo "ALL TESTS COMPLETE!"
echo "=========================================="
echo "Results saved in:"
echo "  - logs_fixed_delay/"
echo "  - logs_adaptive_delay/"
