#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script to analyze usage Cursor CSV files and provide a summary of costs and tokens.

Usage:
    python analyze_usage_csv.py <csv_file>
    
Example:
    python analyze_usage_csv.py usage_data.csv

The script expects a CSV with the following columns:
- Date, Kind, Model, Max Mode, Input (w/ Cache Write), Input (w/o Cache Write),
  Cache Read, Output Tokens, Total Tokens, Cost
"""

import csv
import sys
from collections import defaultdict
from typing import Dict, List, Any


def parse_csv(filepath: str) -> List[Dict[str, Any]]:
    """
    Parse the CSV file and return a list of row dictionaries.
    
    Args:
        filepath: Path to the CSV file
        
    Returns:
        List of dictionaries, each representing a row
    """
    rows = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert numeric fields to appropriate types
            parsed_row = {
                'date': row['Date'],
                'kind': row['Kind'],
                'model': row['Model'],
                'max_mode': row['Max Mode'],
                'input_cache_write': int(row['Input (w/ Cache Write)']),
                'input_no_cache': int(row['Input (w/o Cache Write)']),
                'cache_read': int(row['Cache Read']),
                'output_tokens': int(row['Output Tokens']),
                'total_tokens': int(row['Total Tokens']),
                'cost': float(row['Cost']),
            }
            rows.append(parsed_row)
    return rows


def analyze_data(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze the usage data and compute summaries.
    
    Args:
        rows: List of parsed row dictionaries
        
    Returns:
        Dictionary containing analysis results
    """
    # Initialize totals
    total_cost = 0.0
    total_tokens = 0
    total_input_cache_write = 0
    total_input_no_cache = 0
    total_cache_read = 0
    total_output_tokens = 0
    
    # Per-model tracking
    model_stats = defaultdict(lambda: {
        'cost': 0.0,
        'total_tokens': 0,
        'input_cache_write': 0,
        'input_no_cache': 0,
        'cache_read': 0,
        'output_tokens': 0,
        'request_count': 0,
    })
    
    # Process each row
    for row in rows:
        model = row['model']
        
        # Update totals
        total_cost += row['cost']
        total_tokens += row['total_tokens']
        total_input_cache_write += row['input_cache_write']
        total_input_no_cache += row['input_no_cache']
        total_cache_read += row['cache_read']
        total_output_tokens += row['output_tokens']
        
        # Update model-specific stats
        model_stats[model]['cost'] += row['cost']
        model_stats[model]['total_tokens'] += row['total_tokens']
        model_stats[model]['input_cache_write'] += row['input_cache_write']
        model_stats[model]['input_no_cache'] += row['input_no_cache']
        model_stats[model]['cache_read'] += row['cache_read']
        model_stats[model]['output_tokens'] += row['output_tokens']
        model_stats[model]['request_count'] += 1
    
    return {
        'total_cost': total_cost,
        'total_tokens': total_tokens,
        'total_input_cache_write': total_input_cache_write,
        'total_input_no_cache': total_input_no_cache,
        'total_cache_read': total_cache_read,
        'total_output_tokens': total_output_tokens,
        'request_count': len(rows),
        'model_stats': dict(model_stats),
    }


def format_number(num: int) -> str:
    """Format large numbers with commas for readability."""
    return f"{num:,}"


def print_summary(analysis: Dict[str, Any]) -> None:
    """
    Print a formatted summary of the analysis.
    
    Args:
        analysis: Dictionary containing analysis results
    """
    print("\n" + "=" * 70)
    print("                        USAGE SUMMARY")
    print("=" * 70)
    
    # Overall totals
    print("\n📊 OVERALL TOTALS")
    print("-" * 50)
    print(f"  Total Requests:           {format_number(analysis['request_count'])}")
    print(f"  Total Cost:               ${analysis['total_cost']:.2f}")
    print(f"  Total Tokens:             {format_number(analysis['total_tokens'])}")
    print()
    print(f"  Input (w/ Cache Write):   {format_number(analysis['total_input_cache_write'])}")
    print(f"  Input (w/o Cache Write):  {format_number(analysis['total_input_no_cache'])}")
    print(f"  Cache Read:               {format_number(analysis['total_cache_read'])}")
    print(f"  Output Tokens:            {format_number(analysis['total_output_tokens'])}")
    
    # Per-model breakdown
    print("\n" + "=" * 70)
    print("                      BREAKDOWN BY MODEL")
    print("=" * 70)
    
    # Sort models by cost (descending)
    sorted_models = sorted(
        analysis['model_stats'].items(),
        key=lambda x: x[1]['cost'],
        reverse=True
    )
    
    for model, stats in sorted_models:
        cost_percentage = (stats['cost'] / analysis['total_cost'] * 100) if analysis['total_cost'] > 0 else 0
        token_percentage = (stats['total_tokens'] / analysis['total_tokens'] * 100) if analysis['total_tokens'] > 0 else 0
        
        print(f"\n🤖 {model}")
        print("-" * 50)
        print(f"  Requests:                 {format_number(stats['request_count'])}")
        print(f"  Cost:                     ${stats['cost']:.2f} ({cost_percentage:.1f}% of total)")
        print(f"  Total Tokens:             {format_number(stats['total_tokens'])} ({token_percentage:.1f}% of total)")
        print()
        print(f"  Input (w/ Cache Write):   {format_number(stats['input_cache_write'])}")
        print(f"  Input (w/o Cache Write):  {format_number(stats['input_no_cache'])}")
        print(f"  Cache Read:               {format_number(stats['cache_read'])}")
        print(f"  Output Tokens:            {format_number(stats['output_tokens'])}")
        print(f"  Avg Cost/Request:         ${stats['cost'] / stats['request_count']:.3f}")
        print(f"  Avg Tokens/Request:       {format_number(stats['total_tokens'] // stats['request_count'])}")
    
    print("\n" + "=" * 70)


def main():
    """Main entry point for the script."""
    # Check command line arguments
    if len(sys.argv) != 2:
        print("Usage: python analyze_usage_csv.py <csv_file>")
        print("Example: python analyze_usage_csv.py usage_data.csv")
        sys.exit(1)
    
    filepath = sys.argv[1]
    
    try:
        # Parse and analyze the data
        rows = parse_csv(filepath)
        
        if not rows:
            print("No data found in the CSV file.")
            sys.exit(1)
        
        analysis = analyze_data(rows)
        print_summary(analysis)
        
    except FileNotFoundError:
        print(f"Error: File not found: {filepath}")
        sys.exit(1)
    except KeyError as e:
        print(f"Error: Missing expected column in CSV: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"Error: Invalid data format in CSV: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
