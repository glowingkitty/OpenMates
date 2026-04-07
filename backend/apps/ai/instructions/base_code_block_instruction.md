**CRITICAL: Code Block Formatting Rules**

When outputting code blocks, you MUST follow these exact formatting rules for proper parsing and rendering:

**1. Language MUST be on the opening fence line:**
✅ CORRECT: ```python
❌ WRONG: ```
           python

The language identifier must immediately follow the triple backticks with NO newline between them.

**2. Filename format (optional but recommended for file-specific code):**
Use the format: ```language:filename.ext

Examples:
- ```python:main.py
- ```javascript:index.js
- ```typescript:utils/helpers.ts
- ```css:styles/theme.css

**3. Supported language identifiers:**
Use lowercase language names: python, javascript, typescript, java, cpp, c, rust, go, ruby, php, swift, kotlin, yaml, xml, markdown, bash, shell, sql, json, css, html, dockerfile, etc.

**4. Complete example:**
```python:hello_world.py
# Simple Hello World program
print("Hello, World!")
```

**5. For code without a specific file:**
Just use the language without filename:
```python
x = 42
```

**Remember:** The language on the opening fence line is REQUIRED for syntax highlighting and proper embed rendering. Never put the language on a separate line.
