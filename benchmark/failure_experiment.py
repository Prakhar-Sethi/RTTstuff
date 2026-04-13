"""
Failure Injection Experiment Runner for HotStuff BFT
Runs experiments with controlled node failures to measure detection and recovery times
"""

import subprocess
import time
import csv
import re
import os
from glob import glob
from datetime import datetime
from math import ceil
from os.path import join
from time import sleep

from benchmark.commands import CommandMaker
from benchmark.config import Key, LocalCommittee, NodeParameters, BenchParameters, ConfigError
from benchmark.utils import Print, BenchError, PathMaker
from failure_injection import NodeKiller, FailureScenario, ALL_SCENARIOS
from failure_log_parser import FailureLogParser


class FailureExperiment:
    """Manages failure injection experiments"""
    
    BASE_PORT = 9000
    
    def __init__(self, bench_params, node_params, scenario):
        """
        Args:
            bench_params: Dictionary of benchmark parameters
            node_params: Dictionary of node parameters  
            scenario: FailureScenario object defining failure injection times
        """
        try:
            self.bench_params = BenchParameters(bench_params)
            self.node_params = NodeParameters(node_params)
            self.scenario = scenario
        except ConfigError as e:
            raise BenchError('Invalid parameters', e)
    
    def _background_run(self, command, log_file):
        """Start a command in background tmux session"""
        name = log_file.split('/')[-1].replace('.log', '')
        cmd = f'{command} 2>> {log_file}'  # Append to log file
        subprocess.run(['tmux', 'new', '-d', '-s', name, cmd], check=True)
    
    def _kill_all_nodes(self):
        """Kill all running nodes"""
        try:
            cmd = CommandMaker.kill().split()
            subprocess.run(cmd, stderr=subprocess.DEVNULL)
        except subprocess.SubprocessError as e:
            raise BenchError('Failed to kill nodes', e)
    
    def _setup_testbed(self, nodes):
        """
        Set up the testbed: clean files, compile, generate keys, create committee.
        
        Returns:
            tuple: (keys, committee, key_files, dbs, node_logs, client_logs)
        """
        Print.info('Setting up testbed...')
        
        # Cleanup
        cmd = f'{CommandMaker.clean_logs()} ; {CommandMaker.cleanup()}'
        subprocess.run([cmd], shell=True, stderr=subprocess.DEVNULL)
        sleep(0.5)
        
        # Compile
        cmd = CommandMaker.compile().split()
        subprocess.run(cmd, check=True, cwd=PathMaker.node_crate_path())
        
        # Create binary aliases
        cmd = CommandMaker.alias_binaries(PathMaker.binary_path())
        subprocess.run([cmd], shell=True)
        
        # Generate keys
        keys = []
        key_files = [PathMaker.key_file(i) for i in range(nodes)]
        for filename in key_files:
            cmd = CommandMaker.generate_key(filename).split()
            subprocess.run(cmd, check=True)
            keys.append(Key.from_file(filename))
        
        # Create committee
        names = [x.name for x in keys]
        committee = LocalCommittee(names, self.BASE_PORT)
        committee.print(PathMaker.committee_file())
        
        # Save parameters
        self.node_params.print(PathMaker.parameters_file())
        
        # Prepare paths
        dbs = [PathMaker.db_path(i) for i in range(nodes)]
        node_logs = [PathMaker.node_log_file(i) for i in range(nodes)]
        client_logs = [PathMaker.client_log_file(i) for i in range(nodes)]
        
        return keys, committee, key_files, dbs, node_logs, client_logs
    
    def _start_clients(self, committee, nodes, rate, timeout, client_logs):
        """Start all client processes"""
        addresses = committee.front
        rate_share = ceil(rate / nodes)
        
        for addr, log_file in zip(addresses, client_logs):
            cmd = CommandMaker.run_client(addr, self.bench_params.tx_size, 
                                         rate_share, timeout)
            self._background_run(cmd, log_file)
    
    def _start_nodes(self, nodes, key_files, dbs, node_logs, debug=False):
        """Start all node processes"""
        for key_file, db, log_file in zip(key_files, dbs, node_logs):
            cmd = CommandMaker.run_node(
                key_file,
                PathMaker.committee_file(),
                db,
                PathMaker.parameters_file(),
                debug=debug
            )
            self._background_run(cmd, log_file)
    
    def _inject_failures(self, start_time, key_files, dbs, node_logs, nodes, debug=False):
        """
        Monitor time and inject failures according to scenario.
        
        Returns:
            list: List of (failure_time, killed_node_id) tuples
        """
        injected_failures = []
        current_round = 1  # Approximate tracking
        
        while True:
            elapsed = time.time() - start_time
            
            # Check if experiment duration is over
            if elapsed >= self.bench_params.duration:
                break
            
            # Check for scheduled failures
            failures = self.scenario.get_failures_at_time(elapsed, tolerance=0.5)
            
            for target, scheduled_time in failures:
                # Determine which node to kill
                if target == 'leader':
                    # Kill current leader based on round
                    node_id = NodeKiller.get_leader_for_round(current_round, nodes)
                    Print.info(f"🎯 Targeting leader (node-{node_id}) at round ~{current_round}")
                else:
                    node_id = int(target)
                
                # Kill the node
                failure_time = NodeKiller.kill_node(node_id)
                injected_failures.append((failure_time, node_id))
                
                # Wait a bit for detection
                sleep(10)
                
                # Restart the node (it will sync back up)
                NodeKiller.restart_node(
                    node_id, 
                    key_files[node_id],
                    PathMaker.committee_file(),
                    dbs[node_id],
                    PathMaker.parameters_file(),
                    node_logs[node_id],
                    debug=debug
                )
            
            # Update approximate round (rough estimate: 1 round per 0.5s)
            current_round = int(elapsed / 0.5)
            
            sleep(0.5)
        
        return injected_failures
    
    def run(self, debug=False):
        """
        Run a single failure injection experiment.
        
        Returns:
            dict: Experiment results including failure metrics
        """
        Print.heading(f'Starting failure experiment: {self.scenario.name}')
        Print.info(f'Scenario: {self.scenario.description}')
        
        # Kill any previous testbed
        self._kill_all_nodes()
        sleep(1)
        
        try:
            nodes = self.bench_params.nodes[0]
            rate = self.bench_params.rate[0]
            timeout = self.node_params.timeout_delay
            
            # Setup
            keys, committee, key_files, dbs, node_logs, client_logs = \
                self._setup_testbed(nodes)
            
            # Start clients
            self._start_clients(committee, nodes, rate, timeout, client_logs)
            
            # Start nodes
            self._start_nodes(nodes, key_files, dbs, node_logs, debug=debug)
            
            # Wait for synchronization
            Print.info('Waiting for nodes to synchronize...')
            sleep(2 * timeout / 1000)
            
            # Start experiment timer
            start_time = time.time()
            Print.info(f'Running experiment ({self.bench_params.duration}s)...')
            
            # Inject failures according to scenario
            injected_failures = self._inject_failures(
                start_time, key_files, dbs, node_logs, nodes, debug=debug
            )
            
            # Wait for experiment to complete
            remaining = self.bench_params.duration - (time.time() - start_time)
            if remaining > 0:
                sleep(remaining)
            
            # Stop everything
            self._kill_all_nodes()
            sleep(1)
            
            # Parse results
            Print.info('Parsing logs...')
            results = self._parse_results(injected_failures)
            
            return results
            
        except (subprocess.SubprocessError, Exception) as e:
            self._kill_all_nodes()
            raise BenchError('Experiment failed', e)
    
    def _parse_results(self, injected_failures):
        """
        Parse experiment results from logs.
        
        Args:
            injected_failures: List of (failure_time, node_id) tuples
            
        Returns:
            dict: Parsed metrics
        """
        results = {
            'scenario': self.scenario.name,
            'success': True,
            'failures_injected': len(injected_failures),
            'failure_metrics': []
        }
        
        # If no failures (baseline), just get performance
        if len(injected_failures) == 0:
            try:
                # Count UNIQUE blocks from node-0 only (not batches, not all nodes)
                node_0_log = join('./logs', 'node-0.log')
                if not os.path.exists(node_0_log):
                    raise FileNotFoundError(f"node-0.log not found")
                
                with open(node_0_log, 'r') as f:
                    content = f.read()
                    # Match only "Committed B<number>" at END of line (excludes "Committed B -> batch")
                    total_commits = len(re.findall(r'INFO.*Committed\s+B\d+$', content, re.MULTILINE))
                
                # Calculate throughput (unique blocks over duration)
                if total_commits > 0:
                    results['throughput_tps'] = int(total_commits / self.bench_params.duration)
                    results['total_commits'] = total_commits
                else:
                    results['throughput_tps'] = 0
                    results['total_commits'] = 0
                    
                Print.info(f"📊 Baseline: {total_commits} unique blocks, {results['throughput_tps']} TPS")
            except Exception as e:
                Print.warn(f"Failed to parse baseline performance: {e}")
                results['throughput_tps'] = 0
                results['total_commits'] = 0
            
            return results
        
        # Parse each failure's detection/recovery metrics
        for failure_time, node_id in injected_failures:
            try:
                metrics = FailureLogParser.extract_failure_metrics(
                    './logs', failure_time, node_id
                )
                results['failure_metrics'].append(metrics.to_dict())
            except Exception as e:
                Print.warn(f"Failed to parse failure metrics: {e}")
                # Add empty metrics so we don't crash
                results['failure_metrics'].append({
                    'detection_latency_ms': 0,
                    'view_change_duration_ms': 0,
                    'total_recovery_time_ms': 0,
                    'timeouts_during_recovery': 0
                })
        
        # Calculate averages
        if results['failure_metrics']:
            avg_detection = sum(m['detection_latency_ms'] for m in results['failure_metrics']) / len(results['failure_metrics'])
            avg_recovery = sum(m['total_recovery_time_ms'] for m in results['failure_metrics']) / len(results['failure_metrics'])
            
            results['avg_detection_latency_ms'] = int(avg_detection)
            results['avg_recovery_time_ms'] = int(avg_recovery)
            
            Print.info(f"📊 Failures: Detection={results['avg_detection_latency_ms']}ms, Recovery={results['avg_recovery_time_ms']}ms")
        else:
            results['avg_detection_latency_ms'] = 0
            results['avg_recovery_time_ms'] = 0
        
        # Calculate TPS for failure scenarios (count unique blocks from node-0)
        try:
            node_0_log = join('./logs', 'node-0.log')
            if not os.path.exists(node_0_log):
                raise FileNotFoundError(f"node-0.log not found")
            
            with open(node_0_log, 'r') as f:
                content = f.read()
                # Match only "Committed B<number>" at END of line (excludes "Committed B -> batch")
                total_commits = len(re.findall(r'INFO.*Committed\s+B\d+$', content, re.MULTILINE))
            
            # Calculate throughput (unique blocks over duration)
            if total_commits > 0:
                results['throughput_tps'] = int(total_commits / self.bench_params.duration)
                results['total_commits'] = total_commits
            else:
                results['throughput_tps'] = 0
                results['total_commits'] = 0
                
            Print.info(f"📊 Throughput: {total_commits} unique blocks, {results['throughput_tps']} TPS")
        except Exception as e:
            Print.warn(f"Failed to parse throughput: {e}")
            results['throughput_tps'] = 0
            results['total_commits'] = 0
        
        return results


def run_failure_experiments(output_csv='failure_results.csv', trials=20, debug=False):
    """
    Run complete failure injection experiment suite.
    
    Args:
        output_csv: Output CSV filename
        trials: Number of trials per scenario
        debug: Enable debug logging
    """
    # Configuration (matching your paper parameters)
    bench_params = {
        'nodes': [13],
        'rate': [1000],
        'tx_size': 512,
        'duration': 300,  # 5 minutes per trial
        'faults': 0
    }
    
    node_params = {
        'consensus': {
            'timeout_delay': 5000,  # Production value from Sonnino
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
    
    # Prepare CSV
    with open(output_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'scenario', 'timeout_strategy', 'trial', 'success',
            'failures_injected', 'avg_detection_latency_ms', 
            'avg_recovery_time_ms', 'throughput_tps'
        ])
        writer.writeheader()
    
    # Run experiments
    scenarios = ['baseline', 'realistic', 'stress']
    strategies = ['fixed', 'adaptive']
    
    total = len(scenarios) * len(strategies) * trials
    current = 0
    start_time = time.time()
    
    for scenario_name in scenarios:
        scenario = ALL_SCENARIOS[scenario_name]
        
        for strategy in strategies:
            Print.heading(f'\n=== {scenario_name.upper()} + {strategy.upper()} ===')
            
            # TODO: Switch timeout strategy here (modify timer.rs)
            # For now, assumes you've set it manually
            
            for trial in range(1, trials + 1):
                current += 1
                elapsed = time.time() - start_time
                avg_time = elapsed / current if current > 0 else 0
                eta = avg_time * (total - current)
                
                Print.info(f'\nTrial {trial}/{trials} (Test {current}/{total}, ETA: {int(eta/60)}m)')
                
                # Run experiment
                experiment = FailureExperiment(bench_params, node_params, scenario)
                results = experiment.run(debug=debug)
                
                # Save results
                row = {
                    'scenario': scenario_name,
                    'timeout_strategy': strategy,
                    'trial': trial,
                    'success': results.get('success', False),
                    'failures_injected': results.get('failures_injected', 0),
                    'avg_detection_latency_ms': results.get('avg_detection_latency_ms', 0),
                    'avg_recovery_time_ms': results.get('avg_recovery_time_ms', 0),
                    'throughput_tps': results.get('throughput_tps', 0)
                }
                
                with open(output_csv, 'a', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=row.keys())
                    writer.writerow(row)
                
                Print.info(f'✅ Result: Detection={row["avg_detection_latency_ms"]}ms, '
                          f'Recovery={row["avg_recovery_time_ms"]}ms')
    
    Print.heading(f'\n🎉 ALL EXPERIMENTS COMPLETE!')
    Print.info(f'Results saved to: {output_csv}')
    Print.info(f'Total time: {int((time.time() - start_time)/60)} minutes')


if __name__ == '__main__':
    run_failure_experiments(trials=20, debug=False)
