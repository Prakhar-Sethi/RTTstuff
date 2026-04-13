"""
Failure Injection Module for HotStuff BFT Consensus
Handles killing and restarting specific nodes during experiments
"""

import subprocess
import time
from datetime import datetime
from benchmark.utils import PathMaker, BenchError, Print
from benchmark.commands import CommandMaker


class NodeKiller:
    """Manages node failures during experiments"""
    
    @staticmethod
    def get_leader_for_round(round_num, num_nodes):
        """
        Determine which node is the leader for a given round.
        HotStuff uses round-robin: leader = round % num_nodes
        
        Args:
            round_num: Current consensus round
            num_nodes: Total number of nodes
            
        Returns:
            node_id: The node ID (0-indexed) that is leader
        """
        return round_num % num_nodes
    
    @staticmethod
    def kill_node(node_id):
        """
        Kill a specific node by terminating its tmux session.
        
        Args:
            node_id: Integer node ID (0-indexed)
            
        Returns:
            timestamp: Unix timestamp when node was killed
        """
        session_name = f"node-{node_id}"
        timestamp = time.time()
        
        try:
            Print.info(f"💀 Killing node-{node_id} at {datetime.fromtimestamp(timestamp).isoformat()}")
            subprocess.run(
                ['tmux', 'kill-session', '-t', session_name],
                check=True,
                stderr=subprocess.DEVNULL
            )
            return timestamp
        except subprocess.CalledProcessError as e:
            raise BenchError(f'Failed to kill node {node_id}', e)
    
    @staticmethod
    def restart_node(node_id, key_file, committee_file, db, parameters_file, log_file, debug=False):
        """
        Restart a previously killed node.
        
        Args:
            node_id: Integer node ID (0-indexed)
            key_file: Path to node's key file
            committee_file: Path to committee configuration
            db: Path to node's database
            parameters_file: Path to parameters file
            log_file: Path to log file
            debug: Whether to enable debug logging
            
        Returns:
            timestamp: Unix timestamp when node was restarted
        """
        timestamp = time.time()
        
        try:
            Print.info(f"♻️  Restarting node-{node_id} at {datetime.fromtimestamp(timestamp).isoformat()}")
            
            # Build the command to run the node
            cmd = CommandMaker.run_node(
                key_file,
                committee_file,
                db,
                parameters_file,
                debug=debug
            )
            
            # Start in new tmux session with proper logging
            session_name = f"node-{node_id}"
            full_cmd = f'{cmd} 2>> {log_file}'
            subprocess.run(
                ['tmux', 'new', '-d', '-s', session_name, full_cmd],
                check=True
            )
            
            # Give it a moment to initialize
            time.sleep(1)
            
            return timestamp
            
        except subprocess.CalledProcessError as e:
            raise BenchError(f'Failed to restart node {node_id}', e)
    
    @staticmethod
    def kill_multiple_nodes(node_ids):
        """
        Kill multiple nodes simultaneously.
        
        Args:
            node_ids: List of node IDs to kill
            
        Returns:
            dict: Mapping of node_id -> kill_timestamp
        """
        timestamps = {}
        for node_id in node_ids:
            timestamps[node_id] = NodeKiller.kill_node(node_id)
        return timestamps
    
    @staticmethod
    def verify_node_alive(node_id):
        """
        Check if a node's tmux session is running.
        
        Args:
            node_id: Integer node ID
            
        Returns:
            bool: True if node is running, False otherwise
        """
        session_name = f"node-{node_id}"
        try:
            result = subprocess.run(
                ['tmux', 'has-session', '-t', session_name],
                capture_output=True,
                check=False
            )
            return result.returncode == 0
        except Exception:
            return False
    
    @staticmethod
    def wait_for_node_sync(node_id, timeout=10):
        """
        Wait for a restarted node to sync with the network.
        
        Args:
            node_id: Node ID to monitor
            timeout: Maximum seconds to wait
            
        Returns:
            bool: True if node synced, False if timeout
        """
        start = time.time()
        while time.time() - start < timeout:
            if NodeKiller.verify_node_alive(node_id):
                time.sleep(2)  # Give it extra time to establish connections
                return True
            time.sleep(0.5)
        return False


class FailureScenario:
    """Defines when and how to inject failures"""
    
    def __init__(self, name, description, failure_schedule):
        """
        Args:
            name: Scenario identifier (e.g., "baseline", "single_failure")
            description: Human-readable description
            failure_schedule: List of (time_offset, node_id_or_strategy) tuples
                            Example: [(150, 'leader')] means "kill leader at 150s"
        """
        self.name = name
        self.description = description
        self.failure_schedule = failure_schedule
    
    def get_failures_at_time(self, elapsed_time, tolerance=1.0):
        """
        Check if any failures should be injected at the current time.
        
        Args:
            elapsed_time: Seconds since experiment start
            tolerance: Time window for matching (seconds)
            
        Returns:
            list: List of (node_id_or_strategy, scheduled_time) tuples
        """
        failures = []
        for scheduled_time, target in self.failure_schedule:
            if abs(elapsed_time - scheduled_time) <= tolerance:
                failures.append((target, scheduled_time))
        return failures
    
    def __repr__(self):
        return f"FailureScenario({self.name}: {len(self.failure_schedule)} failures)"


# Pre-defined scenarios for the paper
BASELINE_SCENARIO = FailureScenario(
    name="baseline",
    description="No failures - establishes performance baseline",
    failure_schedule=[]
)

REALISTIC_SCENARIO = FailureScenario(
    name="realistic",
    description="Single leader failure at midpoint (150s) - models typical operational failure",
    failure_schedule=[(150, 'leader')]
)

STRESS_SCENARIO = FailureScenario(
    name="stress",
    description="Four leader failures (60s intervals) - models degraded conditions following chaos engineering methodology",
    failure_schedule=[(60, 'leader'), (120, 'leader'), (180, 'leader'), (240, 'leader')]
)

# Export all scenarios
ALL_SCENARIOS = {
    'baseline': BASELINE_SCENARIO,
    'realistic': REALISTIC_SCENARIO,
    'stress': STRESS_SCENARIO
}
