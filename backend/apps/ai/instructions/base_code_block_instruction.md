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

The preview runs exactly the files in the `application_preview` block. Do not rely on hidden setup files. If you use Tailwind directives such as `@tailwind` or `@apply`, the block MUST also include working Tailwind/PostCSS config files such as `tailwind.config.js` and `postcss.config.js` plus the required dependencies in `package.json`. If you do not include those config files, use plain CSS instead and do not write Tailwind directives.

**Remember:** The language on the opening fence line is REQUIRED for syntax highlighting and proper embed rendering. Never put the language on a separate line.

**7. Remotion video-create fences:**
When creating deterministic videos with exact text, slides, product announcements, diagrams, charts, UI-like motion graphics, or branded layouts, use an explicit Remotion fence:

```remotion:ProductAnnouncement.tsx
// Remotion TSX source
```

Do NOT use generic `tsx`, `typescript`, or `javascript` fences for videos. Generic TSX remains a normal code embed. Use `videos.generate`/Veo instead when the user asks for photorealistic or generative footage.

**8. Atopile PCB schematic fences:**
When creating PCB schematic source, use an explicit `atopile` fence and make the file compile with `atopile==0.15.7`:

```atopile:main.ato
import Resistor
import Capacitor
import ElectricPower

module App:
    power = new ElectricPower
    c_in = new Capacitor
    c_in.capacitance = 10uF +/- 20%
    power.vcc ~ c_in.unnamed[0]
    power.gnd ~ c_in.unnamed[1]
```

Atopile essentials: use `module App:` as the build entrypoint, instantiate with `name = new Type`, connect compatible interfaces with `~`, set resistor/capacitor values through `.resistance` and `.capacitance`, and use tolerances/ranges such as `5.1kohm +/- 5%`, `10uF +/- 20%`, and `target_output_voltage = 3.0V to 3.6V`. Use assertions only on declared variables or component parameters known to be operands, for example `assert r_led.resistance within 470ohm to 2kohm`. Do not assert on signal or `ElectricPower` internals such as `rail_3v3.vcc.voltage`; simple helper modules do not expose those as solver operands.

Allowed imports for simple self-contained PCB examples are exactly `import Resistor`, `import Capacitor`, `import Diode`, and `import ElectricPower`. Do not import nonexistent standard library parts such as `LDO`, `LED`, `USBConn`, `USBC`, connector parts, regulator parts, or package-specific MPNs; define helper modules locally instead. Never use legacy Atopile imports (`import Resistor from "..."`), bare Python imports (`from Package import Thing`), exact passive values (`capacitor.capacitance = 10uF`), generic `.value`, KiCad-style `.p1` / `.p2`, or LED `.a` / `.c` unless those fields are explicitly declared in a local module. Use `.unnamed[0]` / `.unnamed[1]` for resistor/capacitor terminals and `.anode` / `.cathode` for standard diode terminals.
