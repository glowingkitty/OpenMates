#!/usr/bin/env python3
"""
Full flow test for get_docs skill to debug the empty documentation issue.
This tests the complete skill execution including sanitization.
"""

import asyncio
import sys
import os
import logging

# Setup path for imports
sys.path.insert(0, "/app" if os.path.exists("/app") else os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# Configure logging to see all logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


async def test_get_docs_full_flow():
    """Test the complete get_docs skill execution flow."""
    
    print("=" * 80)
    print("TESTING GET_DOCS SKILL - FULL FLOW")
    print("=" * 80)
    
    from backend.apps.code.skills.get_docs_skill import GetDocsSkill
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    
    # Initialize skill
    print("\n1. Initializing GetDocsSkill...")
    skill = GetDocsSkill(
        app=None,
        app_id="code",
        skill_id="get_docs",
        skill_name="Get Documentation",
        skill_description="Fetches library documentation",
        stage="development"
    )
    print("✅ Skill initialized")
    
    # Initialize SecretsManager
    print("\n2. Initializing SecretsManager...")
    secrets_manager = SecretsManager()
    try:
        await secrets_manager.initialize()
        print("✅ SecretsManager initialized")
    except Exception as e:
        print(f"❌ Failed to initialize SecretsManager: {e}")
        return 1
    
    # Test case - the user's failing case
    test_library = "/stripe/stripe-js"
    test_question = "Implement Apple Pay web app"
    
    print(f"\n3. Testing skill.execute() with:")
    print(f"   Library: {test_library}")
    print(f"   Question: {test_question}")
    print("-" * 80)
    
    try:
        result = await skill.execute(
            library=test_library,
            question=test_question,
            secrets_manager=secrets_manager
        )
        
        print(f"\n--- Result ---")
        print(f"Error: {result.error}")
        print(f"Source: {result.source}")
        
        if result.library:
            print(f"Library ID: {result.library.get('id')}")
            print(f"Library Title: {result.library.get('title')}")
            print(f"Library Description: {result.library.get('description', '')[:100]}...")
        
        if result.documentation:
            print(f"\n✅ Documentation retrieved: {len(result.documentation)} characters")
            print(f"First 300 chars:")
            print(result.documentation[:300])
            print("...")
            
            if len(result.documentation.strip()) == 0:
                print("\n⚠️  WARNING: Documentation is empty after sanitization!")
                return 1
            else:
                print("\n✅ Documentation is not empty")
                return 0
        else:
            print(f"\n❌ FAILED: No documentation returned")
            print(f"Error: {result.error}")
            return 1
            
    except Exception as e:
        print(f"\n❌ EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(test_get_docs_full_flow())
    sys.exit(exit_code)
