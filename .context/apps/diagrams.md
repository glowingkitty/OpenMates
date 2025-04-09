
# Skills

## /create_diagram

Defines a function to generate diagrams based on provided code and a specified provider.

**Function Signature:**

`create_diagram(provider: str, diagram_code: str)`

**Parameters:**

*   `provider`: The type of diagramming language/tool to use (e.g., 'mermaid', potentially others like 'plantuml', 'graphviz' in the future).
*   `diagram_code`: The textual code defining the diagram in the syntax of the specified `provider`.

**Initial Supported Providers:**

*   `mermaid`

**Reliable Mermaid Generation Workflow (when provider='mermaid'):**

*   Generate initial Mermaid code using an LLM (if not provided directly in `diagram_code`).
*   Validate syntax using the Mermaid CLI (`mmdc`).
*   If syntax errors exist, feed errors back to the LLM for correction (repeat N times).
*   Render the syntactically valid code to an image.
*   Analyze the image using a vision model for readability (contrast, clarity, etc.).
*   If readability issues exist, feed feedback back to the LLM for style/layout adjustments (repeat M times).
*   Return the validated and visually checked diagram or a failure status if retries are exhausted.
