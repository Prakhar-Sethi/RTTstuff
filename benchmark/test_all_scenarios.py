import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'benchmark')

from failure_experiment import FailureExperiment
from failure_injection import ALL_SCENARIOS
from benchmark.config import BenchParameters, NodeParameters
import csv

# Short duration for testing
bench_params = {
    'nodes': [13],
    'rate': [1000],
    'tx_size': 512,
    'duration': 60,  # Just 60 seconds
    'faults': 0
}

node_params = {
    'consensus': {'timeout_delay': 5000, 'sync_retry_delay': 5000},
    'mempool': {'gc_depth': 50, 'sync_retry_delay': 5000, 'sync_retry_nodes': 3, 'batch_size': 500_000, 'max_batch_delay': 100}
}

# Test all 3 scenarios
test_results = []

for scenario_name in ['baseline', 'realistic', 'stress']:
    print(f"\n{'='*60}")
    print(f"TESTING: {scenario_name.upper()}")
    print(f"{'='*60}")
    
    scenario = ALL_SCENARIOS[scenario_name]
    exp = FailureExperiment(bench_params, node_params, scenario)
    
    try:
        res = exp.run(debug=False)
        
        result = {
            'scenario': scenario_name,
            'success': res.get('success', False),
            'failures': res.get('failures_injected', 0),
            'detection_ms': res.get('avg_detection_latency_ms', 0),
            'recovery_ms': res.get('avg_recovery_time_ms', 0),
            'tps': res.get('throughput_tps', 0),
            'commits': res.get('total_commits', 0)
        }
        
        test_results.append(result)
        
        print(f"\n✅ SUCCESS: {scenario_name}")
        print(f"   Failures injected: {result['failures']}")
        print(f"   Detection: {result['detection_ms']}ms")
        print(f"   Recovery: {result['recovery_ms']}ms")
        print(f"   TPS: {result['tps']}")
        print(f"   Commits: {result['commits']}")
        
    except Exception as e:
        print(f"\n❌ FAILED: {scenario_name}")
        print(f"   Error: {e}")
        import traceback
        traceback.print_exc()
        test_results.append({
            'scenario': scenario_name,
            'success': False,
            'error': str(e)
        })

# Summary
print(f"\n{'='*60}")
print("SUMMARY OF ALL TESTS")
print(f"{'='*60}")

for r in test_results:
    status = "✅ PASS" if r.get('success') else "❌ FAIL"
    print(f"{status} {r['scenario']:12s} - TPS: {r.get('tps', 'N/A'):>5}, Detection: {r.get('detection_ms', 'N/A'):>5}ms")

# Check if all passed
all_passed = all(r.get('success', False) for r in test_results)

if all_passed:
    print(f"\n🎉 ALL TESTS PASSED! Safe to run full 10-hour experiment.")
else:
    print(f"\n⚠️  SOME TESTS FAILED! Fix issues before full run.")
