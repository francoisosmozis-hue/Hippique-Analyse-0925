#!/usr/bin/env python3
"""
Monitor ROI performance in real-time from analysis and results files.

Tracks:
- Expected ROI vs Real ROI
- Cumulative P&L
- Win rate by bet type
- CLV (Closing Line Value)
- Sharpe ratio
- Risk of ruin evolution
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from collections import defaultdict
import csv


def load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    """Load JSON file safely."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Failed to load {path}: {e}", file=sys.stderr)
        return None


def parse_tracking_csv(path: Path) -> List[Dict[str, Any]]:
    """Parse tracking.csv file."""
    rows = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    except Exception as e:
        print(f"Warning: Failed to parse {path}: {e}", file=sys.stderr)
    return rows


def collect_analyses(data_dir: Path, date: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Collect all analysis files for given date (or all if None).
    
    Returns list of dicts with analysis + results data.
    """
    analyses = []
    
    # Pattern: data/R#C#/analysis.json or analysis_H5.json
    for rc_dir in sorted(data_dir.glob("R*C*")):
        if not rc_dir.is_dir():
            continue
        
        # Load analysis
        analysis_file = rc_dir / "analysis.json"
        if not analysis_file.exists():
            analysis_file = rc_dir / "analysis_H5.json"
        
        if not analysis_file.exists():
            continue
        
        analysis = load_json_safe(analysis_file)
        if not analysis:
            continue
        
        # Filter by date if specified
        meta = analysis.get("meta", {})
        race_date = meta.get("date")
        if date and race_date != date:
            continue
        
        # Load tracking
        tracking_file = rc_dir / "tracking.csv"
        tracking = []
        if tracking_file.exists():
            tracking = parse_tracking_csv(tracking_file)
        
        # Load metrics
        metrics_file = rc_dir / "metrics.json"
        metrics = load_json_safe(metrics_file) if metrics_file.exists() else {}
        
        analyses.append({
            "rc": rc_dir.name,
            "analysis": analysis,
            "tracking": tracking,
            "metrics": metrics,
            "dir": rc_dir
        })
    
    return analyses


def compute_statistics(analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute aggregate statistics from analyses."""
    
    total_stake = 0.0
    total_gain = 0.0
    total_expected_roi = 0.0
    total_ev_ratio = 0.0
    
    count_races = len(analyses)
    count_played = 0
    count_abstain = 0
    count_alerte = 0
    
    by_type = defaultdict(lambda: {"stake": 0, "gain": 0, "count": 0, "wins": 0})
    
    clv_values = []
    sharpe_values = []
    ror_values = []
    
    for item in analyses:
        analysis = item["analysis"]
        metrics = item["metrics"]
        
        # Meta
        meta = analysis.get("meta", {})
        
        # Abstain check
        if analysis.get("abstain"):
            count_abstain += 1
            continue
        
        count_played += 1
        
        # Tickets
        tickets = analysis.get("tickets", [])
        for ticket in tickets:
            bet_type = ticket.get("type", "unknown")
            stake = float(ticket.get("stake", 0) or ticket.get("mise", 0) or 0)
            gain = float(ticket.get("gain_reel", 0) or ticket.get("gain", 0) or 0)
            
            total_stake += stake
            total_gain += gain
            
            by_type[bet_type]["stake"] += stake
            by_type[bet_type]["gain"] += gain
            by_type[bet_type]["count"] += 1
            
            if gain > stake:
                by_type[bet_type]["wins"] += 1
        
        # Validation metrics
        validation = analysis.get("validation", {})
        roi_global = validation.get("roi_global_est", 0) or 0
        total_expected_roi += roi_global
        
        # EV ratio
        ev_section = analysis.get("ev", {})
        ev_ratio = ev_section.get("ev_ratio", 0) or ev_section.get("ev_global", 0) or 0
        total_ev_ratio += ev_ratio
        
        # Alerts
        flags = analysis.get("flags", {})
        if flags.get("ALERTE_VALUE"):
            count_alerte += 1
        
        # Metrics
        if metrics:
            clv = metrics.get("clv_moyen", 0) or metrics.get("clv_median_30", 0)
            if clv:
                clv_values.append(clv)
            
            sharpe = metrics.get("sharpe", 0)
            if sharpe:
                sharpe_values.append(sharpe)
            
            ror = metrics.get("risk_of_ruin", 0)
            if ror:
                ror_values.append(ror)
    
    # Compute aggregates
    real_roi = (total_gain - total_stake) / total_stake if total_stake > 0 else 0
    expected_roi_avg = total_expected_roi / count_played if count_played > 0 else 0
    ev_ratio_avg = total_ev_ratio / count_played if count_played > 0 else 0
    
    clv_avg = sum(clv_values) / len(clv_values) if clv_values else 0
    sharpe_avg = sum(sharpe_values) / len(sharpe_values) if sharpe_values else 0
    ror_avg = sum(ror_values) / len(ror_values) if ror_values else 0
    
    return {
        "total_races": count_races,
        "races_played": count_played,
        "races_abstain": count_abstain,
        "races_alerte": count_alerte,
        "total_stake": round(total_stake, 2),
        "total_gain": round(total_gain, 2),
        "net_profit": round(total_gain - total_stake, 2),
        "real_roi": round(real_roi, 4),
        "expected_roi_avg": round(expected_roi_avg, 4),
        "ev_ratio_avg": round(ev_ratio_avg, 4),
        "roi_variance": round(real_roi - expected_roi_avg, 4),
        "clv_avg": round(clv_avg, 4),
        "sharpe_avg": round(sharpe_avg, 4),
        "ror_avg": round(ror_avg, 6),
        "by_type": dict(by_type)
    }


def print_report(stats: Dict[str, Any], detail: bool = False):
    """Print formatted ROI report."""
    
    print("=" * 70)
    print("  📊 ROI MONITORING REPORT")
    print("=" * 70)
    print()
    
    # Summary
    print("📈 SUMMARY")
    print("-" * 70)
    print(f"  Total Races:        {stats['total_races']}")
    print(f"  Races Played:       {stats['races_played']}")
    print(f"  Races Abstain:      {stats['races_abstain']}")
    print(f"  Races with Alert:   {stats['races_alerte']}")
    print()
    
    # Financial
    print("💰 FINANCIAL")
    print("-" * 70)
    print(f"  Total Stake:        {stats['total_stake']:.2f} €")
    print(f"  Total Gain:         {stats['total_gain']:.2f} €")
    print(f"  Net Profit:         {stats['net_profit']:.2f} €")
    print()
    
    # ROI Metrics
    print("📊 ROI METRICS")
    print("-" * 70)
    print(f"  Real ROI:           {stats['real_roi']*100:.2f}%")
    print(f"  Expected ROI (avg): {stats['expected_roi_avg']*100:.2f}%")
    print(f"  ROI Variance:       {stats['roi_variance']*100:.2f}%")
    print(f"  EV Ratio (avg):     {stats['ev_ratio_avg']*100:.2f}%")
    print()
    
    # Risk Metrics
    print("⚠️  RISK METRICS")
    print("-" * 70)
    print(f"  CLV Average:        {stats['clv_avg']*100:.2f}%")
    print(f"  Sharpe Ratio (avg): {stats['sharpe_avg']:.3f}")
    print(f"  Risk of Ruin (avg): {stats['ror_avg']*100:.4f}%")
    print()
    
    # By bet type
    if detail and stats['by_type']:
        print("🎯 BY BET TYPE")
        print("-" * 70)
        for bet_type, data in sorted(stats['by_type'].items()):
            stake = data['stake']
            gain = data['gain']
            count = data['count']
            wins = data['wins']
            
            roi = (gain - stake) / stake if stake > 0 else 0
            win_rate = wins / count if count > 0 else 0
            
            print(f"  {bet_type.upper()}")
            print(f"    Tickets:    {count}")
            print(f"    Stake:      {stake:.2f} €")
            print(f"    Gain:       {gain:.2f} €")
            print(f"    ROI:        {roi*100:.2f}%")
            print(f"    Win Rate:   {win_rate*100:.1f}%")
            print()
    
    print("=" * 70)


def export_json(stats: Dict[str, Any], output: Path):
    """Export statistics as JSON."""
    with open(output, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    print(f"✅ Statistics exported to {output}")


def main():
    parser = argparse.ArgumentParser(
        description="Monitor ROI performance from analysis files"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Data directory containing R#C# folders (default: data)"
    )
    parser.add_argument(
        "--date",
        help="Filter by specific date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--last-days",
        type=int,
        help="Show stats for last N days"
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Show detailed breakdown by bet type"
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Export statistics to JSON file"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch mode: refresh every 60 seconds"
    )
    
    args = parser.parse_args()
    
    # Determine date filter
    date_filter = args.date
    if args.last_days:
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=args.last_days)
        # Note: This is simplified, would need to collect multiple dates
        date_filter = None  # For now, show all
    
    def run_report():
        # Collect analyses
        print(f"🔍 Scanning {args.data_dir}...", end="")
        analyses = collect_analyses(args.data_dir, date_filter)
        print(f" Found {len(analyses)} races")
        
        if not analyses:
            print("❌ No analysis files found")
            return
        
        # Compute statistics
        stats = compute_statistics(analyses)
        
        # Print report
        print()
        print_report(stats, detail=args.detail)
        
        # Export JSON
        if args.json_out:
            export_json(stats, args.json_out)
    
    # Run once or watch
    if args.watch:
        import time
        try:
            while True:
                run_report()
                print()
                print("⏳ Refreshing in 60 seconds... (Ctrl+C to stop)")
                time.sleep(60)
                print("\033[2J\033[H")  # Clear screen
        except KeyboardInterrupt:
            print("\n👋 Monitoring stopped")
    else:
        run_report()


if __name__ == "__main__":
    main()
