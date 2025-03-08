import logging
import requests
import os
import uuid
import random
import string
import re
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from dotenv import load_dotenv
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class InviteCodeGenerator:
    def __init__(self, base_url: str, access_token: str):
        """Initialize InviteCodeGenerator with API credentials"""
        self.base_url = base_url.rstrip('/')
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

    def generate_invite_code(self) -> str:
        """Generate a unique invite code in the format XXXX-XXXX-XXXX"""
        chars = string.ascii_uppercase + string.digits
        segments = []
        
        # Generate three segments of 4 characters each
        for _ in range(3):
            segment = ''.join(random.choice(chars) for _ in range(4))
            segments.append(segment)
            
        return '-'.join(segments)

    def create_invite_code(self, 
                          valid_from: Optional[datetime] = None,
                          expire_date: Optional[datetime] = None, 
                          single_use: bool = True,
                          use_limit: Optional[int] = None,
                          gifted_credits: Optional[int] = None) -> Dict[str, Any]:
        """Create an invite code in Directus"""
        code = self.generate_invite_code()
        
        payload = {
            "code": code,
            "can_be_used_once": single_use
        }
        
        # Only add valid_from if it's specified
        if valid_from:
            payload["valid_from"] = valid_from.isoformat()
            
        # Only add expire_date if it's specifically set
        if expire_date:
            payload["expire_date"] = expire_date.isoformat()
            
        if not single_use and use_limit is not None:
            payload["can_be_used_x_more_times"] = use_limit
            
        if gifted_credits is not None:
            payload["gifted_credits"] = gifted_credits
            
        try:
            url = f"{self.base_url}/items/invitecode"
            logger.debug(f"Creating invite code: {code}")
            response = requests.post(url, json=payload, headers=self.headers)
            response.raise_for_status()
            created_code = response.json()['data']
            logger.info(f"Created invite code: {code}")
            return created_code
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to create invite code: {str(e)}")
            raise

    def create_specific_code(self, 
                           code: str,
                           valid_from: Optional[datetime] = None,
                           expire_date: Optional[datetime] = None, 
                           single_use: bool = True,
                           use_limit: Optional[int] = None,
                           gifted_credits: Optional[int] = None) -> Dict[str, Any]:
        """Create a specific invite code in Directus"""
        # Validate the code format
        if not self._is_valid_code_format(code):
            raise ValueError("Invalid code format. Must be in the format XXXX-XXXX-XXXX")
        
        payload = {
            "code": code,
            "can_be_used_once": single_use
        }
        
        # Only add valid_from if it's specified
        if valid_from:
            payload["valid_from"] = valid_from.isoformat()
            
        # Only add expire_date if it's specifically set
        if expire_date:
            payload["expire_date"] = expire_date.isoformat()
            
        if not single_use and use_limit is not None:
            payload["can_be_used_x_more_times"] = use_limit
            
        if gifted_credits is not None:
            payload["gifted_credits"] = gifted_credits
            
        try:
            url = f"{self.base_url}/items/invitecode"
            logger.debug(f"Creating specific invite code: {code}")
            response = requests.post(url, json=payload, headers=self.headers)
            response.raise_for_status()
            created_code = response.json()['data']
            logger.info(f"Created specific invite code: {code}")
            return created_code
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to create specific invite code: {str(e)}")
            raise
            
    def _is_valid_code_format(self, code: str) -> bool:
        """Check if a code matches the XXXX-XXXX-XXXX format"""
        pattern = r"^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$"
        return bool(re.match(pattern, code))

    def batch_create_invite_codes(self, 
                                count: int,
                                valid_from: Optional[datetime] = None,
                                expire_days: Optional[int] = None,
                                single_use: bool = True,
                                use_limit: Optional[int] = None,
                                gifted_credits: Optional[int] = None) -> list:
        """Create multiple invite codes at once"""
        # Only calculate expire_date if expire_days is explicitly provided and positive
        expire_date = None
        if expire_days is not None and expire_days > 0:
            expire_date = datetime.now() + timedelta(days=expire_days)
            
        created_codes = []
        for _ in range(count):
            try:
                code = self.create_invite_code(
                    valid_from=valid_from,
                    expire_date=expire_date,  # Will be None if expire_days wasn't provided or positive
                    single_use=single_use,
                    use_limit=use_limit,
                    gifted_credits=gifted_credits
                )
                created_codes.append(code)
            except Exception as e:
                logger.error(f"Failed to create a code: {str(e)}")
                
        return created_codes

    def format_codes_for_display(self, codes: list) -> str:
        """Format generated codes for simple display"""
        result = []
        result.append("Generated Invite Codes:")
        result.append("======================")
        
        for i, code in enumerate(codes):
            result.append(f"Code #{i+1}: {code['code']}")
            
            if 'valid_from' in code and code['valid_from']:
                result.append(f"  Valid from: {code['valid_from']}")
                
            if 'expire_date' in code and code['expire_date']:
                result.append(f"  Expires: {code['expire_date']}")
                
            if code.get('can_be_used_once'):
                result.append("  Usage: Single-use only")
            elif 'can_be_used_x_more_times' in code:
                result.append(f"  Usage: Can be used {code['can_be_used_x_more_times']} more times")
                
            if 'gifted_credits' in code and code['gifted_credits']:
                result.append(f"  Credits: {code['gifted_credits']}")
                
            result.append("")  # Empty line between codes
            
        if not codes:
            result.append("No codes were generated.")
            
        return "\n".join(result)

def print_menu():
    """Print the main menu options"""
    print("\n===== Invite Code Generator =====")
    print("1. Create new random codes")
    print("2. Create specific code")
    print("3. Exit")
    print("================================")

def get_menu_choice() -> int:
    """Get user's menu choice"""
    while True:
        try:
            choice = input("Enter your choice (1-3): ")
            choice_num = int(choice)
            if 1 <= choice_num <= 3:
                return choice_num
            else:
                print("Invalid choice. Please enter a number between 1 and 3.")
        except ValueError:
            print("Please enter a valid number.")

def get_random_codes_input() -> dict:
    """Get parameters for generating random invite codes"""
    print("\n-- Create Random Invite Codes --")
    
    try:
        count = int(input("Number of invite codes to generate: "))
        if count <= 0:
            print("Error: Count must be a positive number")
            return None
            
        valid_from_input = input("Valid from date (YYYY-MM-DD) [leave empty for immediately valid]: ").strip()
        valid_from = None
        if valid_from_input:
            valid_from = datetime.strptime(valid_from_input, "%Y-%m-%d")
            
        expire_days_input = input("Expire after how many days [leave empty for no expiration]: ").strip()
        expire_days = None
        if expire_days_input:
            expire_days = int(expire_days_input)
            if expire_days <= 0:
                print("Error: Expire days must be a positive number")
                return None
                
        single_use_input = input("Single use codes? (y/n) [default: y]: ").lower()
        single_use = single_use_input != 'n'
        
        use_limit = None
        if not single_use:
            use_limit_input = input("How many times can each code be used? [leave empty for unlimited]: ").strip()
            if use_limit_input:
                use_limit = int(use_limit_input)
                if use_limit <= 0:
                    print("Error: Use limit must be a positive number")
                    return None
        
        gifted_credits_input = input("Credits to gift with code [leave empty for none]: ").strip()
        gifted_credits = None
        if gifted_credits_input:
            gifted_credits = int(gifted_credits_input)
            if gifted_credits < 0:
                print("Error: Credits must be a non-negative number")
                return None
                
        print("\nGenerating codes with these parameters:")
        print(f"- Count: {count}")
        if valid_from:
            print(f"- Valid from: {valid_from.strftime('%Y-%m-%d')}")
        if expire_days:
            print(f"- Expire after: {expire_days} days")
        print(f"- Single use: {single_use}")
        if not single_use and use_limit:
            print(f"- Use limit: {use_limit}")
        if gifted_credits is not None:
            print(f"- Gifted credits: {gifted_credits}")
        
        confirm = input("\nConfirm? (y/n): ").lower()
        if confirm != 'y':
            print("Operation cancelled.")
            return None
        
        return {
            'count': count,
            'valid_from': valid_from,
            'expire_days': expire_days,
            'single_use': single_use,
            'use_limit': use_limit,
            'gifted_credits': gifted_credits
        }
        
    except ValueError as e:
        print(f"Error: {str(e)}")
        return None

def get_specific_code_input() -> dict:
    """Get parameters for creating a specific invite code"""
    print("\n-- Create Specific Invite Code --")
    
    try:
        while True:
            code = input("Enter specific code (format XXXX-XXXX-XXXX): ").strip().upper()
            if re.match(r"^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$", code):
                break
            else:
                print("Invalid format. Please use the format XXXX-XXXX-XXXX.")
        
        valid_from_input = input("Valid from date (YYYY-MM-DD) [leave empty for immediately valid]: ").strip()
        valid_from = None
        if valid_from_input:
            valid_from = datetime.strptime(valid_from_input, "%Y-%m-%d")
            
        expire_days_input = input("Expire after how many days [leave empty for no expiration]: ").strip()
        expire_days = None
        if expire_days_input:
            expire_days = int(expire_days_input)
            if expire_days <= 0:
                print("Error: Expire days must be a positive number")
                return None
                
        single_use_input = input("Single use code? (y/n) [default: y]: ").lower()
        single_use = single_use_input != 'n'
        
        use_limit = None
        if not single_use:
            use_limit_input = input("How many times can the code be used? [leave empty for unlimited]: ").strip()
            if use_limit_input:
                use_limit = int(use_limit_input)
                if use_limit <= 0:
                    print("Error: Use limit must be a positive number")
                    return None
        
        gifted_credits_input = input("Credits to gift with code [leave empty for none]: ").strip()
        gifted_credits = None
        if gifted_credits_input:
            gifted_credits = int(gifted_credits_input)
            if gifted_credits < 0:
                print("Error: Credits must be a non-negative number")
                return None
        
        print("\nCreating code with these parameters:")
        print(f"- Code: {code}")
        if valid_from:
            print(f"- Valid from: {valid_from.strftime('%Y-%m-%d')}")
        if expire_days:
            print(f"- Expire after: {expire_days} days")
        print(f"- Single use: {single_use}")
        if not single_use and use_limit:
            print(f"- Use limit: {use_limit}")
        if gifted_credits is not None:
            print(f"- Gifted credits: {gifted_credits}")
        
        confirm = input("\nConfirm? (y/n): ").lower()
        if confirm != 'y':
            print("Operation cancelled.")
            return None
        
        return {
            'code': code,
            'valid_from': valid_from,
            'expire_days': expire_days,
            'single_use': single_use,
            'use_limit': use_limit,
            'gifted_credits': gifted_credits
        }
        
    except ValueError as e:
        print(f"Error: {str(e)}")
        return None

def main():
    """Main function to generate invite codes"""
    directus_url = os.getenv("DIRECTUS_URL", "http://localhost:1337")
    admin_token = os.getenv("DIRECTUS_ADMIN_TOKEN")

    if not admin_token:
        print("Error: DIRECTUS_ADMIN_TOKEN environment variable is not set")
        return

    # Initialize generator
    generator = InviteCodeGenerator(directus_url, admin_token)
    
    while True:
        print_menu()
        choice = get_menu_choice()
        
        if choice == 1:  # Create new random codes
            params = get_random_codes_input()
            if not params:
                continue  # User canceled or input error
            
            print("\nGenerating invite codes...")
            codes = generator.batch_create_invite_codes(
                count=params['count'],
                valid_from=params['valid_from'],
                expire_days=params['expire_days'],
                single_use=params['single_use'],
                use_limit=params['use_limit'],
                gifted_credits=params['gifted_credits']
            )
            
            print("\n" + generator.format_codes_for_display(codes))
            
            input("\nPress Enter to continue...")
            
        elif choice == 2:  # Create specific code
            params = get_specific_code_input()
            if not params:
                continue  # User canceled or input error
            
            # Calculate expiration date if needed (only if specifically set)
            expire_date = None
            if params['expire_days'] is not None and params['expire_days'] > 0:
                expire_date = datetime.now() + timedelta(days=params['expire_days'])
            
            print("\nCreating specific invite code...")
            code = generator.create_specific_code(
                code=params['code'],
                valid_from=params['valid_from'],
                expire_date=expire_date,
                single_use=params['single_use'],
                use_limit=params['use_limit'],
                gifted_credits=params['gifted_credits']
            )
            
            print("\n" + generator.format_codes_for_display([code]))
            
            input("\nPress Enter to continue...")
            
        else:  # Exit
            print("Exiting...")
            break
            
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nOperation canceled by user.")