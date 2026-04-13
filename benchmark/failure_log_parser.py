"""
Failure Detection Log Parser for HotStuff BFT
Extracts timeout detection times, view changes, and recovery metrics from logs
"""

import re
from datetime import datetime
from glob import glob
from os.path import join
from statistics import mean


class FailureMetrics:
    """Container for failure detection and recovery metrics"""
    
    def __init__(self):
        self.failure_injection_time = None
        self.first_timeout_time = None
        self.view_change_complete_time = None
        self.first_commit_after_failure = None
        
        self.detection_latency_ms = None  # Time from failure to first timeout
        self.view_change_duration_ms = None  # Time for view change to complete
        self.total_recovery_time_ms = None  # Time from failure to first new commit
        
        self.timeouts_during_recovery = 0
        self.rounds_during_recovery = []
    
    def calculate_metrics(self):
        """Calculate derived metrics from timestamps"""
        if self.failure_injection_time and self.first_timeout_time:
            self.detection_latency_ms = int(
                (self.first_timeout_time - self.failure_injection_time) * 1000
            )
        
        if self.first_timeout_time and self.view_change_complete_time:
            self.view_change_duration_ms = int(
                (self.view_change_complete_time - self.first_timeout_time) * 1000
            )
        
        if self.failure_injection_time and self.first_commit_after_failure:
            self.total_recovery_time_ms = int(
                (self.first_commit_after_failure - self.failure_injection_time) * 1000
            )
    
    def to_dict(self):
        """Convert to dictionary for CSV export"""
        return {
            'detection_latency_ms': self.detection_latency_ms or 0,
            'view_change_duration_ms': self.view_change_duration_ms or 0,
            'total_recovery_time_ms': self.total_recovery_time_ms or 0,
            'timeouts_during_recovery': self.timeouts_during_recovery
        }
    
    def __repr__(self):
        return (f"FailureMetrics(detection={self.detection_latency_ms}ms, "
                f"view_change={self.view_change_duration_ms}ms, "
                f"recovery={self.total_recovery_time_ms}ms)")


class FailureLogParser:
    """Parse HotStuff logs to extract failure detection metrics"""
    
    @staticmethod
    def _parse_timestamp(timestamp_str):
        """
        Convert ISO timestamp string to Unix timestamp.
        Format: 2025-12-23T17:04:11.265Z
        """
        # Remove 'Z' and parse
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        return dt.timestamp()
    
    @staticmethod
    def parse_node_log(log_content, failure_injection_time=None):
        """
        Parse a single node's log file for failure-related events.
        
        Args:
            log_content: String content of the log file
            failure_injection_time: Unix timestamp when failure was injected
            
        Returns:
            dict: Extracted events with timestamps
        """
        events = {
            'timeouts': [],
            'round_changes': [],
            'commits': [],
            'view_changes': []
        }
        
        # Regex patterns
        timeout_pattern = r'\[(.*Z)\s+WARN.*Timeout reached for round (\d+)'
        round_pattern = r'\[(.*Z)\s+DEBUG.*Moved to round (\d+)'
        commit_pattern = r'\[(.*Z)\s+INFO.*Committed\s+B\d+'
        
        for line in log_content.split('\n'):
            # Timeouts
            match = re.search(timeout_pattern, line)
            if match:
                timestamp = FailureLogParser._parse_timestamp(match.group(1))
                round_num = int(match.group(2))
                events['timeouts'].append((timestamp, round_num))
            
            # Round changes
            match = re.search(round_pattern, line)
            if match:
                timestamp = FailureLogParser._parse_timestamp(match.group(1))
                round_num = int(match.group(2))
                events['round_changes'].append((timestamp, round_num))
            
            # Commits
            match = re.search(commit_pattern, line)
            if match:
                timestamp = FailureLogParser._parse_timestamp(match.group(1))
                events['commits'].append(timestamp)
        
        return events
    
    @staticmethod
    def extract_failure_metrics(logs_dir, failure_injection_time, killed_node_id):
        """
        Extract failure detection metrics from all node logs.
        
        Args:
            logs_dir: Directory containing node log files
            failure_injection_time: Unix timestamp when node was killed
            killed_node_id: ID of the node that was killed
            
        Returns:
            FailureMetrics: Aggregated metrics
        """
        metrics = FailureMetrics()
        metrics.failure_injection_time = failure_injection_time
        
        all_timeouts = []
        all_commits = []
        
        # Parse all node logs (except the killed node)
        for log_file in sorted(glob(join(logs_dir, 'node-*.log'))):
            # Extract node ID from filename
            node_id = int(re.search(r'node-(\d+)\.log', log_file).group(1))
            
            # Skip the killed node's log
            if node_id == killed_node_id:
                continue
            
            with open(log_file, 'r') as f:
                log_content = f.read()
            
            events = FailureLogParser.parse_node_log(log_content, failure_injection_time)
            
            # Collect timeouts after failure
            for timeout_time, round_num in events['timeouts']:
                if timeout_time > failure_injection_time:
                    all_timeouts.append(timeout_time)
                    metrics.timeouts_during_recovery += 1
            
            # Collect commits after failure
            for commit_time in events['commits']:
                if commit_time > failure_injection_time:
                    all_commits.append(commit_time)
        
        # Find first timeout after failure (detection time)
        if all_timeouts:
            metrics.first_timeout_time = min(all_timeouts)
        
        # Find first commit after failure (recovery complete)
        if all_commits:
            metrics.first_commit_after_failure = min(all_commits)
            # View change is complete when we get first commit
            metrics.view_change_complete_time = metrics.first_commit_after_failure
        
        metrics.calculate_metrics()
        return metrics
    
    @staticmethod
    def parse_baseline_performance(logs_dir):
        """
        Parse logs from a baseline (no-failure) run to get normal performance.
        
        Args:
            logs_dir: Directory containing node log files
            
        Returns:
            dict: Baseline performance metrics
        """
        all_commits = []
        
        for log_file in sorted(glob(join(logs_dir, 'node-*.log'))):
            with open(log_file, 'r') as f:
                log_content = f.read()
            
            # Extract commit timestamps - look for "Committed B" pattern
            commit_matches = re.findall(r'\[(.*Z)\s+INFO.*Committed\s+B\d+', log_content)
            for timestamp_str in commit_matches:
                try:
                    timestamp = FailureLogParser._parse_timestamp(timestamp_str)
                    all_commits.append(timestamp)
                except:
                    continue
        
        if len(all_commits) < 2:
            return {'commits': 0, 'duration': 0, 'tps': 0}
        
        all_commits.sort()
        duration = all_commits[-1] - all_commits[0]
        tps = len(all_commits) / duration if duration > 0 else 0
        
        return {
            'commits': len(all_commits),
            'duration': duration,
            'tps': tps
        }
