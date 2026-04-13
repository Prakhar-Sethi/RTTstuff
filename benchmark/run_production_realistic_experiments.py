#!/usr/bin/env python3
"""
Production-Realistic Failure Detection Experiments
- Timeout: 5000ms (production default from fabfile.py remote)
- Network: 80-150ms (AWS inter-region latency from CloudPing)
- Failures: Controlled node crashes to measure detection speed
"""

import sys
import os
import subprocess
import time
import csv
from datetime import datetime

sys.path.insert(0, '.')
sys.path.insert(0, 'benchmark')

from failure_experiment import FailureExperiment
from failure_injection import ALL_SCENARIOS
from benchmark.config import BenchParameters, NodeParameters


class ProductionRealisticExperiments:
    """
    Production-realistic failure detection experiments
    Using Sonnino's remote (production) configuration
    """
    
    def __init__(self, output_csv='production_realistic_results.csv'):
        self.output_csv = output_csv
        self.timer_dir = '../consensus/src'
        self.network_dir = '../network/src'
        self.node_dir = '../node'
        
        # PRODUCTION CONFIGURATION (from fabfile.py remote)
        self.bench_params = {
            'nodes': [13],
            'rate': [1000],
            'tx_size': 512,
            'duration': 300,  # 5 minutes per trial (fabfile.py remote)
            'faults': 0
        }
        
        # PRODUCTION TIMEOUT (from fabfile.py remote)
        self.node_params = {
            'consensus': {
                'timeout_delay': 5000,  # Production default (Sonnino fabfile.py)
                'sync_retry_delay': 5000
            },
            'mempool': {
                'gc_depth': 50,
                'sync_retry_delay': 5000,
                'sync_retry_nodes': 3,
                'batch_size': 500_000,
                'max_batch_delay': 100
            }
        }
        
        # PRODUCTION NETWORK LATENCY (AWS inter-region from CloudPing)
        # us-east to us-west: 65-75ms
        # us-east to eu-west: 85-95ms
        # Average for global distribution: 80-150ms
        self.network_delay_min = 80   # milliseconds
        self.network_delay_max = 150  # milliseconds
        
        # Experiment matrix
        self.scenarios = ['baseline', 'realistic', 'stress']
        self.strategies = ['fixed', 'adaptive']
        self.trials_per_config = 20
        
        # Note: We're using standard 'stress' scenario from failure_injection.py
        # which has 2 failures. For better TPS differentiation, we'll need 
        # to modify ALL_SCENARIOS['stress'] to have 4 failures.
        
        self.total_experiments = len(self.scenarios) * len(self.strategies) * self.trials_per_config
        self.start_time = None
    
    def verify_files_exist(self):
        """Verify all required files exist"""
        print("\n🔍 Verifying required files...")
        required = [
            f'{self.timer_dir}/timer_fixed.rs',
            f'{self.timer_dir}/timer_adaptive.rs',
            f'{self.network_dir}/simple_sender.rs',
            'failure_experiment.py',
            'failure_injection.py'
        ]
        
        for filepath in required:
            if not os.path.exists(filepath):
                raise FileNotFoundError(f"❌ Missing: {filepath}")
            print(f"  ✅ {filepath}")
        
        print("\n✅ All required files present!")
    
    def create_network_delay_config(self):
        """
        Create simple_sender with production-realistic AWS latency
        80-150ms based on CloudPing measurements
        """
        print(f"\n📝 Configuring production network latency ({self.network_delay_min}-{self.network_delay_max}ms)...")
        
        # Backup original
        backup_path = f'{self.network_dir}/simple_sender.rs.ORIGINAL_BACKUP'
        if not os.path.exists(backup_path):
            subprocess.run(['cp', f'{self.network_dir}/simple_sender.rs', backup_path])
            print(f"  ✅ Backed up original simple_sender.rs")
        
        # Read the original file
        with open(f'{self.network_dir}/simple_sender.rs', 'r') as f:
            content = f.read()
        
        # Modify the delay range to production values (80-150ms)
        # Look for the pattern where SimpleSender is created
        # We need to inject delays into the send method
        
        # Check if we need to add delay logic
        if 'tokio::time::sleep' not in content:
            print("  ⚠️  Adding network delay injection to simple_sender.rs...")
            
            # Find the send method and add delay before sending
            # This is a simplified version - we inject delay before every send
            modified_content = content.replace(
                'async fn send(&self, destination: &Address, bytes: Bytes) -> Result<(), Box<dyn Error>> {',
                f'''async fn send(&self, destination: &Address, bytes: Bytes) -> Result<(), Box<dyn Error>> {{
        // Production-realistic AWS inter-region latency (80-150ms)
        // Based on CloudPing measurements: us-east ↔ us-west ≈ 70ms, us-east ↔ eu-west ≈ 90ms
        use rand::Rng;
        let delay_ms = rand::thread_rng().gen_range({self.network_delay_min}..={self.network_delay_max});
        tokio::time::sleep(tokio::time::Duration::from_millis(delay_ms)).await;
        '''
            )
            
            # Write the modified file
            with open(f'{self.network_dir}/simple_sender.rs', 'w') as f:
                f.write(modified_content)
            
            print(f"  ✅ Injected {self.network_delay_min}-{self.network_delay_max}ms network delay")
        else:
            print(f"  ℹ️  Network delay already configured")
    
    def restore_network_config(self):
        """Restore original simple_sender.rs"""
        backup_path = f'{self.network_dir}/simple_sender.rs.ORIGINAL_BACKUP'
        if os.path.exists(backup_path):
            subprocess.run(['cp', backup_path, f'{self.network_dir}/simple_sender.rs'])
            print("  ✅ Restored original simple_sender.rs")
    
    def switch_timeout_strategy(self, strategy):
        """Switch between fixed and adaptive timeout strategies"""
        print(f"\n📝 Switching to {strategy.upper()} timeout...")
        
        source_file = f'{self.timer_dir}/timer_{strategy}.rs'
        target_file = f'{self.timer_dir}/timer.rs'
        
        # Copy the file
        with open(source_file, 'r') as src:
            content = src.read()
        with open(target_file, 'w') as dst:
            dst.write(content)
        print(f"  ✅ Copied {source_file} → {target_file}")
        
        # Verify
        with open(target_file, 'r') as f:
            new_content = f.read()
        
        if strategy == 'fixed':
            if 'self.current_timeout = 5000' not in new_content:
                raise Exception("❌ Fixed timeout not applied correctly!")
            print(f"  ✅ Verified: Fixed timeout (5000ms) active")
        else:
            if 'self.estimated_rtt' not in new_content:
                raise Exception("❌ Adaptive timeout not applied correctly!")
            print(f"  ✅ Verified: Adaptive EWMA timeout active")
        
        # Rebuild
        print(f"\n🔨 Rebuilding with {strategy} timeout and network delay...")
        result = subprocess.run(
            ['cargo', 'build', '--release', '--quiet'],
            cwd=self.node_dir,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode != 0:
            print(f"❌ Build stderr: {result.stderr}")
            raise Exception(f"Build failed with code {result.returncode}")
        
        print(f"  ✅ Build successful!")
        return True
    
    def initialize_csv(self):
        """Create CSV with header"""
        if not os.path.exists(self.output_csv):
            print(f"\n📄 Creating new results file: {self.output_csv}")
            with open(self.output_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'scenario',
                    'timeout_strategy',
                    'trial',
                    'success',
                    'failures_injected',
                    'avg_detection_latency_ms',
                    'avg_recovery_time_ms',
                    'throughput_tps',
                    'network_delay_range',
                    'timeout_value'
                ])
        else:
            print(f"\n📄 Appending to existing file: {self.output_csv}")
    
    def is_trial_complete(self, scenario, strategy, trial):
        """Check if trial already completed"""
        if not os.path.exists(self.output_csv):
            return False
        
        try:
            with open(self.output_csv, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if (row['scenario'] == scenario and 
                        row['timeout_strategy'] == strategy and 
                        row['trial'] == str(trial)):
                        return True
        except Exception:
            return False
        
        return False
    
    def run_single_trial(self, scenario_name, strategy, trial):
        """Run a single trial"""
        
        print(f"\n{'='*70}")
        print(f"SCENARIO: {scenario_name.upper()} | STRATEGY: {strategy.upper()} | Trial {trial}/20")
        print(f"Config: 5000ms timeout, 80-150ms network (production realistic)")
        print(f"{'='*70}")
        
        scenario = ALL_SCENARIOS[scenario_name]
        
        try:
            exp = FailureExperiment(self.bench_params, self.node_params, scenario)
            result = exp.run(debug=False)
            
            row = {
                'scenario': scenario_name,
                'timeout_strategy': strategy,
                'trial': trial,
                'success': result.get('success', False),
                'failures_injected': result.get('failures_injected', 0),
                'avg_detection_latency_ms': result.get('avg_detection_latency_ms', 0),
                'avg_recovery_time_ms': result.get('avg_recovery_time_ms', 0),
                'throughput_tps': result.get('throughput_tps', 0),
                'network_delay_range': f'{self.network_delay_min}-{self.network_delay_max}ms',
                'timeout_value': '5000ms'
            }
            
            print(f"\n✅ TRIAL COMPLETE:")
            print(f"   Success: {row['success']}")
            print(f"   Failures: {row['failures_injected']}")
            print(f"   Detection: {row['avg_detection_latency_ms']}ms")
            print(f"   Recovery: {row['avg_recovery_time_ms']}ms")
            print(f"   TPS: {row['throughput_tps']}")
            
            return row
            
        except Exception as e:
            print(f"\n❌ TRIAL FAILED: {e}")
            import traceback
            traceback.print_exc()
            
            return {
                'scenario': scenario_name,
                'timeout_strategy': strategy,
                'trial': trial,
                'success': False,
                'failures_injected': 0,
                'avg_detection_latency_ms': 0,
                'avg_recovery_time_ms': 0,
                'throughput_tps': 0,
                'network_delay_range': f'{self.network_delay_min}-{self.network_delay_max}ms',
                'timeout_value': '5000ms'
            }
    
    def save_result(self, row):
        """Append result to CSV"""
        with open(self.output_csv, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'scenario', 'timeout_strategy', 'trial', 'success',
                'failures_injected', 'avg_detection_latency_ms',
                'avg_recovery_time_ms', 'throughput_tps',
                'network_delay_range', 'timeout_value'
            ])
            writer.writerow(row)
    
    def calculate_eta(self, completed, total):
        """Calculate ETA"""
        if completed == 0 or self.start_time is None:
            return "calculating..."
        
        elapsed = time.time() - self.start_time
        avg_time = elapsed / completed
        remaining = total - completed
        eta_seconds = avg_time * remaining
        
        hours = int(eta_seconds // 3600)
        minutes = int((eta_seconds % 3600) // 60)
        
        return f"{hours}h {minutes}m"
    
    def run_all_experiments(self, resume=True):
        """Run complete experiment suite"""
        
        print("\n" + "="*70)
        print("🚀 PRODUCTION-REALISTIC FAILURE DETECTION EXPERIMENTS")
        print("="*70)
        print(f"Configuration:")
        print(f"  - Timeout: 5000ms (Sonnino fabfile.py remote)")
        print(f"  - Network: 80-150ms (AWS CloudPing measurements)")
        print(f"  - Total experiments: {self.total_experiments}")
        print(f"  - Scenarios: {self.scenarios}")
        print(f"  - Strategies: {self.strategies}")
        print(f"  - Output: {self.output_csv}")
        print("="*70)
        
        # Verify files
        self.verify_files_exist()
        
        # Configure network delay
        self.create_network_delay_config()
        
        # Initialize CSV
        self.initialize_csv()
        
        # Start timer
        self.start_time = time.time()
        completed = 0
        skipped = 0
        
        try:
            # Run experiments
            for strategy in self.strategies:
                # Switch timeout strategy and rebuild
                self.switch_timeout_strategy(strategy)
                
                for scenario_name in self.scenarios:
                    for trial in range(1, self.trials_per_config + 1):
                        
                        # Check if already complete
                        if resume and self.is_trial_complete(scenario_name, strategy, trial):
                            skipped += 1
                            print(f"\n⏭️  Skipping {scenario_name}/{strategy}/trial-{trial} (already complete)")
                            continue
                        
                        # Progress
                        completed += 1
                        eta = self.calculate_eta(completed, self.total_experiments - skipped)
                        print(f"\n📊 Progress: {completed}/{self.total_experiments - skipped} | ETA: {eta}")
                        
                        # Run trial
                        result = self.run_single_trial(scenario_name, strategy, trial)
                        
                        # Save immediately
                        self.save_result(result)
                        
                        # Small delay
                        time.sleep(2)
            
            # Summary
            total_time = time.time() - self.start_time
            hours = int(total_time // 3600)
            minutes = int((total_time % 3600) // 60)
            
            print("\n" + "="*70)
            print("🎉 ALL EXPERIMENTS COMPLETE!")
            print("="*70)
            print(f"Total time: {hours}h {minutes}m")
            print(f"Completed: {completed}")
            print(f"Skipped: {skipped}")
            print(f"Results saved to: {self.output_csv}")
            print("="*70)
            
        finally:
            # Always restore network config
            print("\n🔄 Restoring original network configuration...")
            self.restore_network_config()


if __name__ == '__main__':
    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║  PRODUCTION-REALISTIC FAILURE DETECTION EXPERIMENTS          ║
    ║  Timeout: 5000ms (production) | Network: 80-150ms (AWS)      ║
    ╚══════════════════════════════════════════════════════════════╝
    """)
    
    runner = ProductionRealisticExperiments(
        output_csv='failure_results/production_realistic_experiments.csv'
    )
    
    try:
        runner.run_all_experiments(resume=True)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user. Progress saved to CSV.")
        print("   Run again to resume from where you left off!")
        runner.restore_network_config()
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        runner.restore_network_config()
