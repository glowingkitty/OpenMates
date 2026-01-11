#!/usr/bin/env python3
"""
Direct test script for get_docs skill to debug the empty documentation issue.
This tests the Context7 API call directly.
"""

import asyncio
import sys
import os
import logging

# Setup path for imports
sys.path.insert(0, "/app" if os.path.exists("/app") else os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# Configure logging to see all Context7 API logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


async def test_context7_direct():
    """Test Context7 API directly to see what's being returned."""
    
    print("=" * 80)
    print("TESTING CONTEXT7 API DIRECTLY")
    print("=" * 80)
    
    from backend.apps.code.skills.get_docs_skill import Context7Client
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    
    # Initialize SecretsManager to get API key
    print("\n1. Initializing SecretsManager...")
    secrets_manager = SecretsManager()
    try:
        await secrets_manager.initialize()
        print("✅ SecretsManager initialized")
    except Exception as e:
        print(f"❌ Failed to initialize SecretsManager: {e}")
        return 1
    
    # Get API key
    print("\n2. Getting Context7 API key from Vault...")
    try:
        api_key = await secrets_manager.get_secret(
            secret_path="kv/data/providers/context7",
            secret_key="api_key"
        )
        if api_key:
            print(f"✅ API key retrieved (length: {len(api_key) if api_key else 0})")
            print(f"   API key starts with: {api_key[:10] if api_key else 'None'}...")
        else:
            print("⚠️  No API key found")
            api_key = None
    except Exception as e:
        print(f"❌ Failed to get API key: {e}")
        api_key = None
    
    # Create client
    print("\n3. Creating Context7Client...")
    client = Context7Client(api_key=api_key)
    print(f"✅ Client created (API key present: {api_key is not None})")
    
    # Test cases
    test_cases = [
        {
            "library_id": "/stripe/stripe-js",
            "query": "Implement Apple Pay web app",
            "description": "User's failing test case"
        },
        {
            "library_id": "/sveltejs/svelte",
            "query": "How to use runes?",
            "description": "Known working library"
        },
        {
            "library_id": "/vercel/next.js",
            "query": "How to setup app router?",
            "description": "Another known working library"
        },
    ]
    
    print("\n4. Testing get_context calls...")
    print("=" * 80)
    
    results = []
    for i, test in enumerate(test_cases, 1):
        print(f"\n--- Test {i}: {test['description']} ---")
        print(f"Library ID: {test['library_id']}")
        print(f"Query: {test['query']}")
        print("-" * 80)
        
        try:
            result = await client.get_context(test['library_id'], test['query'])
            
            if result:
                print(f"✅ SUCCESS: Retrieved {len(result)} characters")
                print(f"First 200 chars: {result[:200]}")
                results.append(("SUCCESS", test['description'], len(result)))
            else:
                print(f"❌ FAILED: Returned None or empty")
                results.append(("FAILED", test['description'], 0))
                
        except Exception as e:
            print(f"❌ EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            results.append(("EXCEPTION", test['description'], str(e)))
    
    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    for status, desc, detail in results:
        print(f"{status:10} | {desc:40} | {detail}")
    
    failed_count = sum(1 for r in results if r[0] != "SUCCESS")
    if failed_count > 0:
        print(f"\n❌ {failed_count} test(s) failed")
        return 1
    else:
        print("\n✅ All tests passed")
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(test_context7_direct())
    sys.exit(exit_code)
