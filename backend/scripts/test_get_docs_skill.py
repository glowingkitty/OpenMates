#!/usr/bin/env python3
"""
Test script for get_docs_skill.py
Tests both direct library ID fetch and search-based fetch with LLM function calling.

Usage:
    docker exec api python /app/backend/scripts/test_get_docs_skill.py
"""

import asyncio
import sys
import os
import logging
import time

# Setup path for imports
sys.path.insert(0, "/app")

# Configure logging to see PERF logs and function calling details
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

from backend.apps.code.skills.get_docs_skill import GetDocsSkill
from backend.core.api.app.utils.secrets_manager import SecretsManager


async def test_get_docs():
    """Test the get_docs skill with different inputs."""
    
    print("\n" + "=" * 80)
    print("GET DOCS SKILL INTEGRATION TEST")
    print("Tests function calling with Groq/Cerebras/Mistral for library selection")
    print("=" * 80)
    
    # Initialize skill (minimal config for testing)
    skill = GetDocsSkill(
        app=None,
        app_id="code",
        skill_id="get_docs",
        skill_name="Get Documentation",
        skill_description="Fetches library documentation",
        stage="development"
    )
    
    # Initialize SecretsManager
    print("\nInitializing SecretsManager...")
    secrets_manager = SecretsManager()
    try:
        await secrets_manager.initialize()
        print("✅ SecretsManager initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize SecretsManager: {e}")
        return 1
    
    # Test cases
    test_cases = [
        # Test 1: Direct library ID (should skip search + LLM - fastest path)
        {
            "name": "Direct ID - Svelte",
            "library": "/sveltejs/svelte",
            "question": "how to use runes",
            "description": "Tests direct fetch path (no search, no LLM)"
        },
        # Test 2: Library name search (should use search + LLM selection with function calling)
        {
            "name": "Search - React",
            "library": "react",
            "question": "how to use useState hook",
            "description": "Tests search + LLM function calling selection"
        },
        # Test 3: Another direct ID
        {
            "name": "Direct ID - FastAPI",
            "library": "/fastapi/fastapi",
            "question": "how to create endpoints",
            "description": "Tests another direct fetch path"
        },
        # Test 4: Library name that should return multiple results (tests LLM selection)
        {
            "name": "Search - SvelteKit",
            "library": "sveltekit",
            "question": "how to setup routing",
            "description": "Tests LLM function calling with multiple search results"
        },
    ]
    
    results = {
        "passed": [],
        "failed": []
    }
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n{'='*80}")
        print(f"TEST {i}/{len(test_cases)}: {test['name']}")
        print(f"{'='*80}")
        print(f"Description: {test['description']}")
        print(f"Library: {test['library']}")
        print(f"Question: {test['question']}")
        print("-" * 80)
        
        start_time = time.time()
        
        try:
            result = await skill.execute(
                library=test["library"],
                question=test["question"],
                secrets_manager=secrets_manager
            )
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            
            print(f"\n--- Result ---")
            success = result.error is None
            print(f"Success: {'✅ YES' if success else '❌ NO'}")
            print(f"Source: {result.source}")
            print(f"Duration: {elapsed_ms}ms")
            
            if result.library:
                print(f"Library ID: {result.library.get('id')}")
                print(f"Library Title: {result.library.get('title')}")
            
            if result.documentation:
                print(f"Documentation Length: {len(result.documentation)} chars")
                print(f"\n--- First 300 chars of docs ---")
                print(result.documentation[:300])
                print("...")
            
            if result.error:
                print(f"❌ Error: {result.error}")
                results["failed"].append((test['name'], result.error))
            else:
                results["passed"].append(test['name'])
                print("✅ Test passed!")
                
        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            print(f"❌ Exception after {elapsed_ms}ms: {e}")
            import traceback
            traceback.print_exc()
            results["failed"].append((test['name'], str(e)))
        
        print()
    
    # Print summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    total = len(test_cases)
    passed = len(results["passed"])
    failed = len(results["failed"])
    
    print(f"\nTotal: {total} tests")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")
    
    if results["failed"]:
        print("\nFailed tests:")
        for name, error in results["failed"]:
            print(f"  - {name}: {error}")
    
    print("\n" + "=" * 80)
    
    # Return exit code
    if failed > 0:
        print("❌ SOME TESTS FAILED")
        return 1
    else:
        print("✅ ALL TESTS PASSED")
        return 0


if __name__ == "__main__":
    asyncio.run(test_get_docs())
