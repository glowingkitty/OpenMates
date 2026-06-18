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

**6. Runnable web apps:**
When creating a runnable web app, site, dashboard, or browser UI the user can test, return one `application_preview` block instead of setup commands plus separate files. Include at minimum `package.json`, an entry file (`src/main.ts`, `src/main.js`, or `index.html`), and the main source file:

```application_preview
json:package.json
{"scripts":{"dev":"vite"},"dependencies":{"@sveltejs/vite-plugin-svelte":"latest","vite":"latest","svelte":"latest"},"devDependencies":{}}
typescript:src/main.ts
import App from './App.svelte';
new App({ target: document.getElementById('app')! });
svelte:src/App.svelte
<main>Hello</main>
```

Do not provide `localhost` links for these apps; OpenMates creates the runnable preview from the application block.

**Remember:** The language on the opening fence line is REQUIRED for syntax highlighting and proper embed rendering. Never put the language on a separate line.

**7. Remotion video-create fences:**
When creating deterministic videos with exact text, slides, product announcements, diagrams, charts, UI-like motion graphics, or branded layouts, use an explicit Remotion fence:

```remotion:ProductAnnouncement.tsx
// Remotion TSX source
```

Do NOT use generic `tsx`, `typescript`, or `javascript` fences for videos. Generic TSX remains a normal code embed. Use `videos.generate`/Veo instead when the user asks for photorealistic or generative footage.
