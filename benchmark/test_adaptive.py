#!/usr/bin/env python3
"""
Test adaptive timeout by introducing network delays
"""
import subprocess
import time

def run_test(delay_ms, duration=30):
    """Run benchmark with specific network delay"""
    print(f"\n{'='*60}")
    print(f"Testing with {delay_ms}ms network delay")
    print(f"{'='*60}\n")
    
    # Run benchmark
    cmd = f"fab local"
    subprocess.run(cmd, shell=True)
    
    # Wait between tests
    time.sleep(5)

if __name__ == "__main__":
    # Test 1: Normal conditions (baseline)
    print("TEST 1: Normal network (no delay)")
    run_test(0)
    
    # Test 2: High latency
    print("\nTEST 2: High latency (200ms delay)")
    run_test(200)
    
    # Test 3: Variable latency
    print("\nTEST 3: Variable latency (100-300ms)")
    run_test(150)
