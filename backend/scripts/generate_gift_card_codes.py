#!/usr/bin/env python3
"""
Simple script to generate gift card codes in the format XXXX-XXXX-XXXX.
Uses numbers (0-9) and uppercase letters (A-Z).
"""

import random
import string

def generate_gift_card_code():
    """
    Generate a single gift card code in the format XXXX-XXXX-XXXX.
    
    Returns:
        str: A gift card code in the format XXXX-XXXX-XXXX
    """
    # Characters: numbers 0-9 and uppercase letters A-Z
    characters = string.digits + string.ascii_uppercase
    
    # Generate 4 groups of 4 characters each
    groups = []
    for _ in range(3):
        group = ''.join(random.choice(characters) for _ in range(4))
        groups.append(group)
    
    # Join groups with dashes
    return '-'.join(groups)

if __name__ == '__main__':
    # Generate 10 gift card codes
    print("Generated Gift Card Codes:")
    print("-" * 20)
    for i in range(10):
        code = generate_gift_card_code()
        print(f"{i + 1:2d}. {code}")

