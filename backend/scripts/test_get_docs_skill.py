#!/usr/bin/env python3
"""
Test script for the get_docs skill.
Run from within Docker container: docker exec api python /app/backend/scripts/test_get_docs_skill.py
"""

import asyncio
import sys
import os
import json

# Add backend to path
sys.path.insert(0, "/app")


async def test_context7_search():
    """Test Context7 library search."""
    print("=" * 60)
    print("TEST 1: Context7 Library Search")
    print("=" * 60)
    
    from backend.apps.code.skills.get_docs_skill import Context7Client
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    
    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    
    # Get API key from Vault
    api_key = await secrets_manager.get_secret(
        secret_path="kv/data/providers/context7",
        secret_key="api_key"
    )
    
    if api_key:
        print(f"✅ Context7 API key loaded from Vault")
    else:
        print("⚠️  No Context7 API key in Vault, using public API")
    
    client = Context7Client(api_key=api_key)
    
    test_queries = ["svelte", "fastapi"]
    
    for query in test_queries:
        print(f"\n--- Searching: {query} ---")
        results = await client.search_libraries(query)
        print(f"Found {len(results)} libraries")
        
        for i, lib in enumerate(results[:3]):
            print(f"  {i+1}. {lib.get('id')}")
            print(f"     Title: {lib.get('title')}")
            print(f"     Benchmark: {lib.get('benchmarkScore')}")
    
    return True


async def test_context7_docs():
    """Test Context7 documentation retrieval."""
    print("\n" + "=" * 60)
    print("TEST 2: Context7 Documentation Retrieval")
    print("=" * 60)
    
    from backend.apps.code.skills.get_docs_skill import Context7Client
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    
    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    api_key = await secrets_manager.get_secret(
        secret_path="kv/data/providers/context7",
        secret_key="api_key"
    )
    
    client = Context7Client(api_key=api_key)
    
    test_cases = [
        ("/sveltejs/svelte", "How to use $state rune?"),
    ]
    
    for library_id, question in test_cases:
        print(f"\n--- Library: {library_id} ---")
        print(f"    Question: {question}")
        
        docs = await client.get_context(library_id, question)
        
        if docs:
            print(f"    Content length: {len(docs)} chars")
            print("    Preview (first 300 chars):")
            print("-" * 40)
            print(docs[:300])
            print("-" * 40)
        else:
            print("    ERROR: No documentation returned")
    
    return True


async def test_llm_selection():
    """Test LLM library selection."""
    print("\n" + "=" * 60)
    print("TEST 3: LLM Library Selection")
    print("=" * 60)
    
    from backend.apps.code.skills.get_docs_skill import select_library_with_llm
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    
    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    
    # Check for LLM API keys
    groq_key = await secrets_manager.get_secret(
        secret_path="kv/data/providers/groq",
        secret_key="api_key"
    )
    
    if groq_key:
        print(f"✅ Groq API key available")
    else:
        print("⚠️  No Groq API key - LLM selection will use fallback")
    
    # Mock libraries for testing
    test_libraries = [
        {
            "id": "/sveltejs/svelte",
            "title": "Svelte",
            "description": "Compiler framework for building UI",
            "benchmarkScore": 85
        },
        {
            "id": "/websites/svelte_dev",
            "title": "Svelte Docs",
            "description": "Official Svelte documentation website",
            "benchmarkScore": 91
        },
        {
            "id": "/sveltejs/kit",
            "title": "SvelteKit",
            "description": "Full-stack framework built on Svelte",
            "benchmarkScore": 80
        },
    ]
    
    question = "How to use $state rune in Svelte 5?"
    
    print(f"\nQuestion: {question}")
    print(f"Libraries: {[lib['id'] for lib in test_libraries]}")
    
    selected = await select_library_with_llm(
        libraries=test_libraries,
        question=question,
        secrets_manager=secrets_manager
    )
    print(f"✅ Selected: {selected}")
    
    return True


async def test_all_providers():
    """Test all three LLM providers (Groq, Cerebras, Mistral) for library selection."""
    print("\n" + "=" * 60)
    print("TEST 3B: All LLM Providers Library Selection")
    print("=" * 60)
    
    from backend.apps.code.skills.get_docs_skill import select_library_with_llm, LIBRARY_SELECTION_TOOL
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.apps.ai.llm_providers.groq_client import invoke_groq_chat_completions
    from backend.apps.ai.llm_providers.cerebras_wrapper import invoke_cerebras_chat_completions
    from backend.apps.ai.llm_providers.mistral_client import invoke_mistral_chat_completions
    
    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    
    # Check API keys
    groq_key = await secrets_manager.get_secret(
        secret_path="kv/data/providers/groq",
        secret_key="api_key"
    )
    cerebras_key = await secrets_manager.get_secret(
        secret_path="kv/data/providers/cerebras",
        secret_key="api_key"
    )
    mistral_key = await secrets_manager.get_secret(
        secret_path="kv/data/providers/mistral_ai",
        secret_key="api_key"
    )
    
    print(f"\nAPI Keys Status:")
    print(f"  Groq: {'✅' if groq_key else '❌'}")
    print(f"  Cerebras: {'✅' if cerebras_key else '❌'}")
    print(f"  Mistral: {'✅' if mistral_key else '❌'}")
    
    # Mock libraries for testing
    test_libraries = [
        {
            "id": "/sveltejs/svelte",
            "title": "Svelte",
            "description": "Compiler framework for building UI",
            "benchmarkScore": 85
        },
        {
            "id": "/websites/svelte_dev",
            "title": "Svelte Docs",
            "description": "Official Svelte documentation website",
            "benchmarkScore": 91
        },
        {
            "id": "/sveltejs/kit",
            "title": "SvelteKit",
            "description": "Full-stack framework built on Svelte",
            "benchmarkScore": 80
        },
    ]
    
    question = "How to use $state rune in Svelte 5?"
    task_id = "test_all_providers"
    
    messages = [
        {"role": "system", "content": "You are a library selection system. Select the most relevant library from the provided options based on the user's question."},
        {"role": "user", "content": f"Question: {question}\n\nAvailable libraries:\n{json.dumps([{'id': lib['id'], 'title': lib['title'], 'description': lib['description'][:100]} for lib in test_libraries], indent=2)}\n\nSelect the most relevant library by calling the select_library function."}
    ]
    
    valid_ids = {lib['id'] for lib in test_libraries}
    tools = [LIBRARY_SELECTION_TOOL]
    
    # Test Groq with function calling (tool use)
    print("\n--- Testing Groq (openai/gpt-oss-20b) with function calling ---")
    if groq_key:
        try:
            result = await invoke_groq_chat_completions(
                task_id=task_id,
                model_id="openai/gpt-oss-20b",
                messages=messages,
                secrets_manager=secrets_manager,
                temperature=0,
                max_tokens=100,
                tools=tools,
                tool_choice="auto"  # Use function calling (tool use)
            )
            
            if result.success:
                from backend.apps.code.skills.get_docs_skill import _extract_library_id_from_response
                selected = _extract_library_id_from_response(result, valid_ids)
                if selected:
                    print(f"✅ Groq selected: {selected}")
                else:
                    print(f"⚠️  Groq returned invalid selection")
                    if result.tool_calls_made:
                        print(f"   Tool calls: {[tc.function_name for tc in result.tool_calls_made]}")
                    print(f"   Content: {result.direct_message_content[:200] if result.direct_message_content else 'None'}")
            else:
                print(f"❌ Groq failed: {result.error_message}")
        except Exception as e:
            print(f"❌ Groq error: {e}")
    else:
        print("⚠️  Skipping Groq (no API key)")
    
    # Test Cerebras with function calling
    print("\n--- Testing Cerebras (gpt-oss-120b) with function calling ---")
    if cerebras_key:
        try:
            result = await invoke_cerebras_chat_completions(
                task_id=task_id,
                model_id="gpt-oss-120b",
                messages=messages,
                secrets_manager=secrets_manager,
                temperature=0,
                max_tokens=100,
                tools=tools,
                tool_choice="auto"
            )
            
            if result.success:
                from backend.apps.code.skills.get_docs_skill import _extract_library_id_from_response
                selected = _extract_library_id_from_response(result, valid_ids)
                if selected:
                    print(f"✅ Cerebras selected: {selected}")
                else:
                    print(f"⚠️  Cerebras returned invalid selection")
                    if result.tool_calls_made:
                        print(f"   Tool calls: {[tc.function_name for tc in result.tool_calls_made]}")
            else:
                print(f"❌ Cerebras failed: {result.error_message}")
        except Exception as e:
            print(f"❌ Cerebras error: {e}")
    else:
        print("⚠️  Skipping Cerebras (no API key)")
    
    # Test Mistral with function calling
    print("\n--- Testing Mistral (mistral-small-latest) with function calling ---")
    if mistral_key:
        try:
            result = await invoke_mistral_chat_completions(
                task_id=task_id,
                model_id="mistral-small-latest",
                messages=messages,
                secrets_manager=secrets_manager,
                temperature=0,
                max_tokens=100,
                tools=tools,
                tool_choice="auto"
            )
            
            if result.success:
                from backend.apps.code.skills.get_docs_skill import _extract_library_id_from_response
                selected = _extract_library_id_from_response(result, valid_ids)
                if selected:
                    print(f"✅ Mistral selected: {selected}")
                else:
                    print(f"⚠️  Mistral returned invalid selection")
                    if result.tool_calls_made:
                        print(f"   Tool calls: {[tc.function_name for tc in result.tool_calls_made]}")
            else:
                print(f"❌ Mistral failed: {result.error_message}")
        except Exception as e:
            print(f"❌ Mistral error: {e}")
    else:
        print("⚠️  Skipping Mistral (no API key)")
    
    return True


async def test_full_skill():
    """Test the full GetDocsSkill execute method."""
    print("\n" + "=" * 60)
    print("TEST 4: Full GetDocsSkill Execution")
    print("=" * 60)
    
    from backend.apps.code.skills.get_docs_skill import GetDocsSkill
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    
    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    
    # Create skill instance (mock app for testing)
    class MockApp:
        celery_producer = None
    
    skill = GetDocsSkill(
        app=MockApp(),
        app_id="code",
        skill_id="get_docs",
        skill_name="Get Docs",
        skill_description="Fetch documentation",
        stage="development"
    )
    
    # Test with real query
    print("\n--- Testing: svelte + $state rune ---")
    result = await skill.execute(
        library="svelte",
        question="How to use $state rune?",
        secrets_manager=secrets_manager
    )
    
    if result.error:
        print(f"❌ Error: {result.error}")
    else:
        print(f"✅ Library: {result.library}")
        print(f"   Source: {result.source}")
        print(f"   Tokens: {result.tokens_used}")
        if result.documentation:
            print(f"   Doc preview (first 200 chars):")
            print("-" * 40)
            print(result.documentation[:200])
            print("-" * 40)
    
    return True


async def main():
    """Run all tests."""
    print("=" * 60)
    print("GET DOCS SKILL TEST SUITE (Docker)")
    print("=" * 60)
    
    try:
        await test_context7_search()
        await test_context7_docs()
        await test_llm_selection()
        await test_all_providers()  # Test all three providers individually
        await test_full_skill()
        
        print("\n" + "=" * 60)
        print("✅ All tests completed!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
