# Code App architecture

The Code app allows for viewing, writing and editing code / software projects.

## Embedded previews

### Code

> Note: Not yet implemented, but high priority.

Used every time a code block is contained in a message in the chat history or message input field.

Can include a filepath in the first line of the code block where we also define the language of the code: `{language}:{filepath}`.

Data processing is done via unified `parseMessage()` function described in [message_parsing.md](../message_parsing.md).

#### Code | Processing

[![Code | Processing | Preview & Fullscreen view in mobile & desktop](../../images/apps/code/previews/code/processing.jpg)](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3508-41238&t=V4FPCQaihiRx7h7e-4)

When the code is still being generated, those layouts are used.

##### Code | Processing | Input example (Markdown code block)

````
```python:stripe_payment_processor.py
import stripe
from datetime import datetime

# Initialize Stripe with your secret key
stripe.api_key = "sk_test_..."

def process_payment(amount, currency, payment_method, customer_email):
   try:
       # Create a PaymentIntent to charge the customer
       payment_intent = 
            stripe.PaymentIntent.create(
            amount=int(amount * 100),  # Convert to smallest currency unit (e.g., cents)
            currency=currency,
            payment_method=payment_method,
            confirmation_method='automatic',
            confirm=True,  # Attempt to confirm and process immediately
            receipt_email=customer_email,
            return_url="https://example.com/return"  # Required for payment methods that redirect
        )
# ...
```
````

##### Code | Processing | Output

- tiptap node (lightweight) with:
  - language (string)
  - line count (number)
  - contentRef (string) pointing to full source in client EmbedStore (memory + IndexedDB)
  - contentHash? (string, sha256 when finished; used for preview caching)
  - preview is derived at render-time (first 12 lines only)
  - "Write" text and 'modify' icon, indicating that the code is still being written
- Figma design:
  - [Preview mobile](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=2264-21760&t=JIw9suqrshvmsdFU-4)
  - [Preview desktop](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=1764-16509&t=JIw9suqrshvmsdFU-4)


##### Code | Processing | Fullscreen view

Show code in fullscreen mode, with preview element in bottom of the screen (with line count and "Write" text and icon, indicating that the code is still being written). The download and copy to clipboard buttons are also available in the top left corner. Top right corner has the fullscreen button, which closes the fullscreen view.

Figma design:

- [Mobile](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3498-40814&t=JIw9suqrshvmsdFU-4)
- [Desktop](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3498-40841&t=JIw9suqrshvmsdFU-4)


#### Code | Finished

[![Code | Finished | Preview & Fullscreen view in mobile & desktop](../../images/apps/code/previews/code/finished.jpg)](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3508-41242&t=V4FPCQaihiRx7h7e-4)

When the code is finished being generated, those layouts are used.

##### Code | Finished | Input example (Markdown code block)

````
```python:stripe_payment_processor.py
import stripe
from datetime import datetime

# Initialize Stripe with your secret key
stripe.api_key = "sk_test_..."

def process_payment(amount, currency, payment_method, customer_email):
   try:
       # Create a PaymentIntent to charge the customer
       payment_intent = 
            stripe.PaymentIntent.create(
            amount=int(amount * 100),  # Convert to smallest currency unit (e.g., cents)
            currency=currency,
            payment_method=payment_method,
            confirmation_method='automatic',
            confirm=True,  # Attempt to confirm and process immediately
            receipt_email=customer_email,
            return_url="https://example.com/return"  # Required for payment methods that redirect
        )
# ...
```
````

##### Code | Finished | Output

- tiptap node (lightweight) with:
  - language (string)
  - line count (number)
  - filename (string)
  - contentRef (string) pointing to full source in client ContentStore (loaded on fullscreen)
  - contentHash (string, sha256 for immutable snapshot/caching)
  - preview is derived at render-time (first 12 lines only)

- Figma design:
  - [Preview mobile](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3423-41511&t=JIw9suqrshvmsdFU-4)
  - [Preview desktop](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3423-41498&t=JIw9suqrshvmsdFU-4)



##### Code | Finished | Fullscreen view

Show code in fullscreen mode, with preview element in bottom of the screen (with filename, line count and language of the code). The download, copy to clipboard and modify buttons are also available in the top left corner. Top right corner has the fullscreen button, which closes the fullscreen view. Full source is resolved via `contentRef` from the client EmbedStore and can stream/live-update independently of the preview node.

> Note: Modify functionality is not yet planned out and should be added in the future.

Figma design:

- [Mobile](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3406-38017&t=V4FPCQaihiRx7h7e-4)
- [Desktop](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3406-38057&t=V4FPCQaihiRx7h7e-4)


##### Code | Finished | Fullscreen view with Architecture Diagrams (Future Feature)

> **Status:** Planned feature - to be implemented

**Concept:** When code is updated in the fullscreen view, automatically generate and display architecture diagrams alongside the code. These diagrams are generated by analyzing code structure (not LLM-generated), helping users understand and visualize code relationships, class hierarchies, module dependencies, and system architecture in real-time.

**Key Idea:**
- Auto-generated diagrams are **separate from LLM-generated content** - they use hardcoded analysis scripts
- When code is modified, the architecture diagram updates automatically to reflect the new structure
- Diagrams are embedded in a tab or side panel in the fullscreen view
- For Python code: UML class diagrams, dependency graphs, module relationships
- For other languages: similar architectural analysis relevant to that language

**Recommended Python Packages for Auto-Diagram Generation:**

| Package | Purpose | Use Case |
|---------|---------|----------|
| **py2puml** | Generates PlantUML class diagrams from Python code | Class hierarchies, method relationships, code structure |
| **PyUMLify** | Auto-generates UML diagrams from Python projects | Project-wide architecture, package diagrams |
| **py-code-visualizer** | Transforms codebases into visual diagrams | Module relationships, architecture maps |
| **Diagrams** | Programmatically create architecture diagrams | Cloud system architecture, infrastructure diagrams |
| **uml-class-diagram-generator** | Generates UML class diagrams from Python | Detailed class structures, XML output for customization |

**Implementation Strategy:**
1. Create a backend service (Python-based) that analyzes code structure using AST (Abstract Syntax Tree) parsing
2. Use one of the above packages to generate diagram files (PlantUML, Mermaid, or SVG format)
3. Cache diagrams with contentHash to avoid regenerating identical code structures
4. Stream diagrams to the frontend alongside code updates
5. Support multiple diagram types (class diagrams, dependency graphs, module hierarchies)
6. Display diagrams in a collapsible panel or tab within fullscreen view

**Benefits:**
- Real-time understanding of code architecture as users write/modify code
- No LLM latency - deterministic analysis based on code structure
- Version-controlled and reproducible visualizations
- Helps users understand complex codebases quickly
- Useful for documentation and knowledge sharing


#### Code | Chat example

[![Code | Chat example](../../images/apps/code/previews/code/chat_example.jpg)](https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=3508-41244&t=V4FPCQaihiRx7h7e-4)

Shows how code previews are rendered in a chat message. Mobile / desktop layouts are used depending on the viewport width.

**Multiple previews:**

General rule for all previews/apps: If multiple previews of the same type are rendered in a chat message, they should be grouped together in a horizontally scrollable container. The previews must be sorted from status "Processing" (left) to "Finished" (right), so that the user can always see if there are any unfinished previews. Scroll bar is visible if there are scrollable elements.

**Single preview:**

If there is only one preview of the same type, no additional container with scrollbar is needed. If a text is following the preview, it will be regularly rendered below the preview. Same if a preview or group of previews of another type is following the preview.


### Notebook

> Note: To be implemented in the future.

Renders the Jupyter notebook json via notebookjs and adds execute buttons to it, triggering the execution in an e2b sandboxed instance and updating the Jupyter notebook json with the cell output. 

#### Input example (Markdown code block with Jupyter notebook json):

````
```json
{
  "cells": [
    {
      "cell_type": "code",
      ...
    }
  ]
}
```
````

#### Output:

- tiptap node with:
  - json code (string)
  - filename (string)
  - cell count (number)


## Skills

### Run Code

Uses e2b (https://github.com/e2b-dev/infra) to start a vm where the user code can run safely. From python to JavaScript and more. Including that the user can take control over the coding environment via a code-server instance installed on the vm. Great for testing, Jupyter notebook, and more.

### Get error logs

Use Sentry or similar providers to get the error logs after an issue occured, for better debugging and fixing of the issue.


### Search

**Recommended Approach:** Use `grep` (with `rg` as preferred alternative) for searching code in the codebase. This provides reliable pattern matching for the Search skill.

### Replace

**Status:** Planned feature - to be implemented with careful consideration.

**Recommended Approach:** Consider using `sed` for code replacement operations. However, this requires **follow-up validation and safety checks** to prevent breaking the codebase:

1. **Pattern Validation**: Before executing sed, validate that the pattern matches expected code blocks
2. **Dry-run Preview**: Show the user a preview of all changes that would be made before applying them
3. **Post-replacement Checks**: After applying sed replacements:
   - Run linters and syntax validators to ensure code integrity
   - Execute unit tests related to modified files
   - Check for compilation/syntax errors
   - Validate no critical functionality is broken
4. **Rollback Capability**: Maintain the ability to revert changes if validation fails
5. **Scope Limitation**: Require explicit file/directory scope to prevent accidental global changes

This multi-step approach ensures sed can be used safely for large-scale code replacements without introducing bugs or breaking the codebase.

### Get docs

Use context7.com API to get docs for the code. If no docs found, use web search + web read to get docs.

## Automated Code Quality Checks

> **Status:** Planned feature - to be implemented

**Functionality:** Every time the chatbot generates code, an automated check runs to ensure no critical issues exist in the generated code. If issues are detected, the LLM is automatically requested to fix the code until it passes validation.

**Description:**
To prevent broken code from being generated and to maintain code quality, the Code app performs automated validation checks on all generated code before it's considered complete. This ensures that generated code is syntactically correct and free from critical issues.

**Validation Process:**
1. **Automatic Check**: After code generation completes, the system automatically runs validation checks specific to the programming language
2. **Issue Detection**: If critical issues are found (e.g., syntax errors, indentation problems, compilation errors), the validation fails
3. **Automatic Fix Request**: The LLM is automatically prompted to fix the detected issues
4. **Iterative Fixing**: This process repeats until the code passes all validation checks or a maximum retry limit is reached

**Language-Specific Validators:**

| Language | Validator | Checks |
|----------|-----------|--------|
| **Python** | `py_compile` | Syntax errors, indentation issues, import errors |
| **JavaScript/TypeScript** | ESLint / TypeScript compiler | Syntax errors, type errors, linting issues |
| **Java** | `javac` | Compilation errors, syntax issues |
| **C/C++** | `gcc` / `clang` | Compilation errors, syntax issues |
| **Go** | `go build` | Compilation errors, syntax issues |
| **Rust** | `rustc` | Compilation errors, syntax issues |
| **Other languages** | Language-specific compilers/linters | Syntax and critical errors |

**Implementation Strategy:**
1. Create a validation service that detects the programming language from the code block
2. Run appropriate validator for the detected language (e.g., `py_compile.compile()` for Python)
3. Capture validation errors and format them for the LLM
4. Automatically generate a fix request prompt with the error details
5. Re-run validation after each fix attempt
6. Set a maximum retry limit (e.g., 3-5 attempts) to prevent infinite loops

**Benefits:**
- Prevents broken code from being delivered to users
- Catches syntax errors and indentation issues automatically
- Reduces manual debugging time
- Ensures code quality standards are maintained
- Provides immediate feedback to improve code generation

**Example Python Validation:**
```python
import py_compile
import tempfile
import os

def validate_python_code(code: str) -> tuple[bool, str]:
    """
    Validates Python code using py_compile.
    Returns (is_valid, error_message).
    """
    try:
        # Create temporary file with the code
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            temp_path = f.name
        
        # Compile the code to check for syntax errors
        py_compile.compile(temp_path, doraise=True)
        
        # Clean up
        os.unlink(temp_path)
        
        return True, ""
    except py_compile.PyCompileError as e:
        # Clean up on error
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        return False, str(e)
    except Exception as e:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        return False, f"Validation error: {str(e)}"
```

**Integration Points:**
- Runs automatically after code generation in the message processing pipeline
- Can be triggered manually for code blocks in chat history
- Works with both streaming and non-streaming code generation
- Integrates with the code preview system to show validation status

## Focuses

### Reverse engineer API

Starts focus mode that focuse on using stagehand / playwright / web app to analyze api which website is using in background. With the end goal to create a Jupyter notebook file with the api being successfully used. Could also use https://github.com/LaurieWired/GhidraMCP/ to reverse engineer processing.

### Plan project

Include asking user multiple choice questions to better understand their requirements and provide more targeted assistance. Important: before suggestions using any AI models for a project, always research what the most recent models from providers are, to recommend recent models and not outdated LLMs / text to image models for example. Also auto research currently best tech stack for a project before making suggestions to user for tech stack.

### Auto setup project

**Functionality:** Automatically initializes and configures new or existing projects with comprehensive documentation, coding standards, and development environment setup.

**Description:**
Similar to Claude's `/init` function, this focus mode ensures projects have proper structure, documentation standards, and coding guidelines defined from the start. It analyzes the existing codebase (if any) and creates a complete project setup with best practices.

### Write code

> Note: Planned feature - to be implemented

**Functionality:** Comprehensive code writing mode for implementing new features, creating mini projects, or building larger applications.

**Description:**
This focus mode is optimized for writing new code from scratch or implementing significant new features. When active in a project with a connected GitHub repository, it:
- Understands project context and coding standards
- Plans implementation with clear milestones
- Writes clean, well-documented code
- Runs tests and validates functionality
- Upon completion:
  - Searches for related GitHub issues/feature requests
  - Links commits/PRs to relevant issues
  - Comments with implementation details
  - Marks issues as resolved when applicable

Suitable for everything from quick utility functions to full-featured applications.

### Fix bug

> Note: Planned feature - to be implemented

**Functionality:** Specialized mode for debugging and fixing unexpected behavior with optimized troubleshooting workflows.

**Description:**
This focus mode is specifically designed for bug fixes and resolving unexpected behavior. When active in a project with a connected GitHub repository, it:
- Analyzes error logs and stack traces
- Reproduces the issue to understand root cause
- Searches codebase for related patterns
- Implements targeted fixes with minimal changes
- Validates fix with tests and edge cases
- Upon successful fix:
  - Auto-searches GitHub issues matching the bug description
  - Comments on issue with root cause analysis and fix explanation
  - Links the fix commit/PR to the issue
  - Closes or marks issue as resolved

Optimized for rapid issue resolution with clear documentation of the debugging process.