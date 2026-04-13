#!/usr/bin/env python3
"""
Extract and visualize adaptive timeout data from logs
"""
import re
import matplotlib.pyplot as plt

def parse_logs(logfile):
    """Extract adaptive timeout data from logs"""
    times = []
    sample_rtt = []
    estimated_rtt = []
    dev_rtt = []
    calculated_timeout = []
    
    with open(logfile, 'r') as f:
        for line in f:
            if "Adaptive timeout:" in line:
                # Your log format: sample=0.00ms, est=23.74ms, dev=37.19ms, new=172ms
                match = re.search(r'sample=([\d.]+)ms, est=([\d.]+)ms, dev=([\d.]+)ms, new=(\d+)ms', line)
                if match:
                    times.append(len(times))
                    sample_rtt.append(float(match.group(1)))
                    estimated_rtt.append(float(match.group(2)))
                    dev_rtt.append(float(match.group(3)))
                    calculated_timeout.append(float(match.group(4)))
    
    return times, sample_rtt, estimated_rtt, dev_rtt, calculated_timeout

def plot_results(logfile, output='adaptive_timeout.png'):
    """Plot the adaptive timeout behavior"""
    times, sample, est_rtt, dev_rtt, timeout = parse_logs(logfile)
    
    if not times:
        print("No adaptive timeout data found in logs!")
        return
    
    print(f"✅ Found {len(times)} adaptive timeout measurements!")
    
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 10))
    
    # Plot 1: Sample RTT (actual view completion times)
    ax1.scatter(times, sample, alpha=0.5, s=30, c='orange', label='Sample RTT (actual)')
    ax1.plot(times, est_rtt, 'b-', label='Estimated RTT (EWMA)', linewidth=2)
    ax1.set_ylabel('Time (ms)')
    ax1.set_title('TCP-Style EWMA: Tracking Actual Network Conditions')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Plot 2: Deviation RTT
    ax2.plot(times, dev_rtt, 'r-', label='Deviation RTT', linewidth=2)
    ax2.set_ylabel('Deviation (ms)')
    ax2.set_title('Network Variance Detection (DevRTT)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    # Plot 3: Final adaptive timeout
    ax3.plot(times, timeout, 'g-', label='Adaptive Timeout (EstRTT + 4×DevRTT)', linewidth=2.5)
    ax3.axhline(y=1000, color='gray', linestyle='--', label='Base Timeout (1000ms)', alpha=0.5)
    ax3.set_xlabel('View Number')
    ax3.set_ylabel('Timeout (ms)')
    ax3.set_title('Final Adaptive Timeout - Responding to Network Changes')
    ax3.legend()
    ax3.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output, dpi=300, bbox_inches='tight')
    print(f"✅ Plot saved to {output}")
    
    # Print summary stats
    print(f"\n{'='*60}")
    print(f"📊 ADAPTIVE TIMEOUT STATISTICS")
    print(f"{'='*60}")
    print(f"Total views measured: {len(times)}")
    print(f"\nSample RTT (actual network):")
    print(f"  Average: {sum(sample)/len(sample):.2f}ms")
    print(f"  Min: {min(sample):.2f}ms")
    print(f"  Max: {max(sample):.2f}ms")
    print(f"\nEstimated RTT (EWMA smoothed):")
    print(f"  Average: {sum(est_rtt)/len(est_rtt):.2f}ms")
    print(f"  Min: {min(est_rtt):.2f}ms")
    print(f"  Max: {max(est_rtt):.2f}ms")
    print(f"\nDeviation RTT (variance tracking):")
    print(f"  Average: {sum(dev_rtt)/len(dev_rtt):.2f}ms")
    print(f"  Min: {min(dev_rtt):.2f}ms")
    print(f"  Max: {max(dev_rtt):.2f}ms")
    print(f"\nAdaptive Timeout (final):")
    print(f"  Average: {sum(timeout)/len(timeout):.2f}ms")
    print(f"  Min: {min(timeout):.2f}ms")
    print(f"  Max: {max(timeout):.2f}ms")
    print(f"\n✨ KEY INSIGHT: Timeout adapts from {min(timeout):.0f}ms to {max(timeout):.0f}ms")
    print(f"   Responding to network variance while avoiding false timeouts!")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    import sys
    logfile = sys.argv[1] if len(sys.argv) > 1 else "logs/node-0.log"
    plot_results(logfile)

