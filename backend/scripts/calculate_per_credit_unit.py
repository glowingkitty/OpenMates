#!/usr/bin/env python3
"""
Script to calculate per_credit_unit values for models in provider YAML files.

Formula: per_credit_unit = 333.33 / cost_per_million_token

Where:
- credit_value_usd = 0.001 (110 USD / 110,000 credits)
- markup = 3 (3x your cost)
- Formula derivation: tokens_per_credit = 0.001 / ((your_cost_per_million * 3) / 1,000,000)
- Simplified: tokens_per_credit = 333.33 / your_cost_per_million

User-friendly rounding rules:
- Below 50 tokens/credit: round to nearest 5 (e.g., 13 → 15, 22 → 20, 27 → 25)
- 50 to 200 tokens/credit: round to nearest 10 (e.g., 67 → 70, 111 → 110)
- 200 to 1000 tokens/credit: round to nearest 50 (e.g., 556 → 550, 833 → 850)
- Over 1000 tokens/credit: round to nearest 100 (e.g., 1111 → 1100, 3333 → 3300)

This script:
1. Parses all provider YAML files
2. Extracts cost per million tokens (input and output)
3. Calculates the correct per_credit_unit values with user-friendly rounding
4. Compares with existing values and highlights discrepancies
"""

import yaml
import sys
from pathlib import Path
from typing import Dict, Any, List

# Constants from the pricing formula
CREDIT_VALUE_USD = 0.001
MARKUP = 3
FORMULA_CONSTANT = 333.33  # Derived from: 0.001 / (3 / 1,000,000) = 333.33...


def calculate_exact_per_credit_unit(cost_per_million: float) -> float:
    """
    Calculate exact per_credit_unit from cost per million tokens (no rounding).
    
    Formula: per_credit_unit = 333.33 / cost_per_million_token
    
    Args:
        cost_per_million: Cost in USD per million tokens
        
    Returns:
        Exact per_credit_unit value (tokens per credit) as float
    """
    if cost_per_million <= 0:
        return 0.0
    return FORMULA_CONSTANT / cost_per_million


def calculate_per_credit_unit(cost_per_million: float) -> int:
    """
    Calculate per_credit_unit from cost per million tokens with user-friendly rounding.
    
    Formula: per_credit_unit = 333.33 / cost_per_million_token
    
    Rounding rules for user-friendly values:
    - Below 50 tokens/credit: round to nearest 5 (e.g., 13 → 15, 22 → 20, 27 → 25)
    - 50 to 200 tokens/credit: round to nearest 10 (e.g., 67 → 70, 111 → 110)
    - 200 to 1000 tokens/credit: round to nearest 50 (e.g., 556 → 550, 833 → 850)
    - Over 1000 tokens/credit: round to nearest 100 (e.g., 1111 → 1100, 3333 → 3300)
    
    Args:
        cost_per_million: Cost in USD per million tokens
        
    Returns:
        User-friendly rounded per_credit_unit value (tokens per credit)
    """
    if cost_per_million <= 0:
        return 0
    
    # Calculate exact value using the formula
    calculated = calculate_exact_per_credit_unit(cost_per_million)
    
    # Apply user-friendly rounding rules
    if calculated < 50:
        # Round to nearest 5 for values below 50
        return int(round(calculated / 5) * 5)
    elif calculated < 200:
        # Round to nearest 10 for values 50 to 200
        return int(round(calculated / 10) * 10)
    elif calculated <= 1000:
        # Round to nearest 50 for values 200 to 1000
        return int(round(calculated / 50) * 50)
    else:
        # Round to nearest 100 for values over 1000
        return int(round(calculated / 100) * 100)


def format_price(price: float) -> str:
    """Format price for display."""
    return f"${price:.2f}"


def analyze_provider_file(file_path: Path) -> List[Dict[str, Any]]:
    """
    Analyze a provider YAML file and extract model pricing information.
    
    Args:
        file_path: Path to the provider YAML file
        
    Returns:
        List of model analysis results
    """
    results = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        if not data or 'models' not in data:
            return results
        
        provider_id = data.get('provider_id', 'unknown')
        provider_name = data.get('name', 'Unknown')
        
        for model in data.get('models', []):
            model_id = model.get('id', 'unknown')
            model_name = model.get('name', 'Unknown')
            
            # Extract costs
            costs = model.get('costs', {})
            input_cost_config = costs.get('input_per_million_token', {})
            output_cost_config = costs.get('output_per_million_token', {})
            
            input_price = input_cost_config.get('price')
            output_price = output_cost_config.get('price')
            
            # Extract existing pricing
            pricing = model.get('pricing', {})
            token_pricing = pricing.get('tokens', {})
            input_pricing = token_pricing.get('input', {})
            output_pricing = token_pricing.get('output', {})
            
            existing_input_per_credit = input_pricing.get('per_credit_unit')
            existing_output_per_credit = output_pricing.get('per_credit_unit')
            
            # Calculate correct values (user-friendly rounded)
            calculated_input = None
            calculated_output = None
            exact_input = None
            exact_output = None
            
            if input_price is not None:
                exact_input = calculate_exact_per_credit_unit(input_price)
                calculated_input = calculate_per_credit_unit(input_price)
            
            if output_price is not None:
                exact_output = calculate_exact_per_credit_unit(output_price)
                calculated_output = calculate_per_credit_unit(output_price)
            
            # Check for discrepancies
            input_matches = (existing_input_per_credit == calculated_input) if (existing_input_per_credit is not None and calculated_input is not None) else None
            output_matches = (existing_output_per_credit == calculated_output) if (existing_output_per_credit is not None and calculated_output is not None) else None
            
            results.append({
                'provider_id': provider_id,
                'provider_name': provider_name,
                'model_id': model_id,
                'model_name': model_name,
                'input_price': input_price,
                'output_price': output_price,
                'existing_input_per_credit': existing_input_per_credit,
                'existing_output_per_credit': existing_output_per_credit,
                'calculated_input_per_credit': calculated_input,
                'calculated_output_per_credit': calculated_output,
                'exact_input_per_credit': exact_input,
                'exact_output_per_credit': exact_output,
                'input_matches': input_matches,
                'output_matches': output_matches,
            })
    
    except Exception as e:
        print(f"Error processing {file_path}: {e}", file=sys.stderr)
    
    return results


def print_results(results: List[Dict[str, Any]]) -> None:
    """
    Print analysis results in a readable format.
    
    Args:
        results: List of model analysis results
    """
    if not results:
        print("No models found with pricing information.")
        return
    
    # Group by provider
    by_provider = {}
    for result in results:
        provider_id = result['provider_id']
        if provider_id not in by_provider:
            by_provider[provider_id] = []
        by_provider[provider_id].append(result)
    
    # Print results
    for provider_id, models in sorted(by_provider.items()):
        provider_name = models[0]['provider_name']
        print(f"\n{'='*80}")
        print(f"Provider: {provider_name} ({provider_id})")
        print(f"{'='*80}")
        
        for model in models:
            model_id = model['model_id']
            model_name = model['model_name']
            
            print(f"\n  Model: {model_name} ({model_id})")
            print(f"  {'-'*76}")
            
            # Input pricing
            if model['input_price'] is not None:
                input_price = model['input_price']
                existing = model['existing_input_per_credit']
                calculated = model['calculated_input_per_credit']
                exact = model['exact_input_per_credit']
                matches = model['input_matches']
                
                status = "✓" if matches else "✗" if matches is False else "?"
                print(f"  Input:  {format_price(input_price)}/M tokens")
                print(f"    Current:  {existing if existing is not None else 'N/A':>6} tokens/credit")
                if exact is not None and abs(exact - calculated) > 0.1:
                    print(f"    Calculated: {calculated:>6} tokens/credit (exact: {exact:.1f}) {status}")
                else:
                    print(f"    Calculated: {calculated:>6} tokens/credit {status}")
                
                if matches is False:
                    diff = abs(existing - calculated) if existing is not None else 0
                    print(f"    ⚠️  DISCREPANCY: Difference of {diff}")
            
            # Output pricing
            if model['output_price'] is not None:
                output_price = model['output_price']
                existing = model['existing_output_per_credit']
                calculated = model['calculated_output_per_credit']
                exact = model['exact_output_per_credit']
                matches = model['output_matches']
                
                status = "✓" if matches else "✗" if matches is False else "?"
                print(f"  Output: {format_price(output_price)}/M tokens")
                print(f"    Current:  {existing if existing is not None else 'N/A':>6} tokens/credit")
                if exact is not None and abs(exact - calculated) > 0.1:
                    print(f"    Calculated: {calculated:>6} tokens/credit (exact: {exact:.1f}) {status}")
                else:
                    print(f"    Calculated: {calculated:>6} tokens/credit {status}")
                
                if matches is False:
                    diff = abs(existing - calculated) if existing is not None else 0
                    print(f"    ⚠️  DISCREPANCY: Difference of {diff}")
            
            # Models without token pricing
            if model['input_price'] is None and model['output_price'] is None:
                print("  (No token-based pricing found)")


def print_summary(results: List[Dict[str, Any]]) -> None:
    """
    Print a summary of discrepancies.
    
    Args:
        results: List of model analysis results
    """
    total_models = len(results)
    input_discrepancies = 0
    output_discrepancies = 0
    input_missing = 0
    output_missing = 0
    
    for result in results:
        if result['input_matches'] is False:
            input_discrepancies += 1
        elif result['existing_input_per_credit'] is None and result['input_price'] is not None:
            input_missing += 1
        
        if result['output_matches'] is False:
            output_discrepancies += 1
        elif result['existing_output_per_credit'] is None and result['output_price'] is not None:
            output_missing += 1
    
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Total models analyzed: {total_models}")
    print(f"Input pricing discrepancies: {input_discrepancies}")
    print(f"Output pricing discrepancies: {output_discrepancies}")
    print(f"Missing input per_credit_unit: {input_missing}")
    print(f"Missing output per_credit_unit: {output_missing}")


def print_simple_output(results: List[Dict[str, Any]]) -> None:
    """
    Print simple output showing only calculated per_credit_unit values.
    
    Args:
        results: List of model analysis results
    """
    for result in results:
        provider_id = result['provider_id']
        model_id = result['model_id']
        
        if result['input_price'] is not None:
            calculated = result['calculated_input_per_credit']
            print(f"{provider_id}/{model_id} input: {calculated}")
        
        if result['output_price'] is not None:
            calculated = result['calculated_output_per_credit']
            print(f"{provider_id}/{model_id} output: {calculated}")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Calculate per_credit_unit values for models in provider YAML files'
    )
    parser.add_argument(
        '--simple',
        action='store_true',
        help='Output only calculated per_credit_unit values in simple format'
    )
    args = parser.parse_args()
    
    # Get the script directory and find providers directory
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent.parent
    providers_dir = repo_root / 'backend' / 'providers'
    
    if not providers_dir.exists():
        print(f"Error: Providers directory not found at {providers_dir}", file=sys.stderr)
        sys.exit(1)
    
    # Find all YAML files
    yaml_files = sorted(providers_dir.glob('*.yml'))
    
    if not yaml_files:
        print(f"No YAML files found in {providers_dir}", file=sys.stderr)
        sys.exit(1)
    
    if not args.simple:
        print("Calculating per_credit_unit values for all models")
        print(f"Formula: per_credit_unit = {FORMULA_CONSTANT} / cost_per_million_token")
        print(f"Based on: credit_value_usd = {CREDIT_VALUE_USD}, markup = {MARKUP}x")
        print("Rounding: <50 → nearest 5, 50-200 → nearest 10, 200-1000 → nearest 50, >1000 → nearest 100")
    
    # Analyze all files
    all_results = []
    for yaml_file in yaml_files:
        results = analyze_provider_file(yaml_file)
        all_results.extend(results)
    
    # Print results
    if args.simple:
        print_simple_output(all_results)
    else:
        print_results(all_results)
        print_summary(all_results)


if __name__ == '__main__':
    main()
