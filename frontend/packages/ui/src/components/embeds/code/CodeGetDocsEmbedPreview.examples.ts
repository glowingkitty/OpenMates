/**
 * App-store examples for the code get_docs skill.
 *
 * Real documentation fetched from Context7 for three popular libraries:
 * Svelte 5, React, and FastAPI. The documentation content is genuine
 * (captured from Context7 API) so the fullscreen view renders real markdown.
 * The preview shows: library ID, question, "via Context7", word count.
 *
 * A "Sample data" banner is shown at the top of the fullscreen via the
 * is_store_example flag set by SkillExamplesSection.
 */

export interface CodeGetDocsStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  library?: string;
  question?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: CodeGetDocsStoreExample[] = [
  {
    "id": "store-example-code-get-docs-1",
    "query": "Svelte 5 $state rune",
    "query_translation_key": "settings.app_store_examples.code.get_docs.1",
    "library": "Svelte 5",
    "question": "How to use reactive state with $state rune in Svelte 5",
    "status": "finished",
    "results": [
      {
        "type": "get_docs",
        "library": {
          "id": "/sveltejs/svelte",
          "title": "Svelte",
          "description": "Svelte is a compiler that transforms declarative UI components into efficient JavaScript that surgically updates the DOM."
        },
        "documentation": "### Declare Reactive State with $state Rune in Svelte 5\n\nSource: https://context7.com/sveltejs/svelte/llms.txt\n\nThe $state rune defines reactive variables that trigger UI updates on change. It supports deep reactivity for objects and arrays, raw state for high-performance large datasets, and snapshots for extracting plain data for external APIs.\n\n```svelte\n<script>\n  // Basic reactive state\n  let count = $state(0);\n\n  // Deep reactive state - arrays and objects are proxied\n  let todos = $state([\n    { id: 1, text: 'Learn Svelte', done: false },\n    { id: 2, text: 'Build app', done: false }\n  ]);\n\n  // Modifying nested properties triggers updates\n  function toggleTodo(id) {\n    const todo = todos.find(t => t.id === id);\n    todo.done = !todo.done; // This triggers a UI update\n  }\n\n  // Adding items to arrays\n  function addTodo(text) {\n    todos.push({ id: Date.now(), text, done: false });\n  }\n\n  // Non-reactive raw state (better performance for large data)\n  let largeDataset = $state.raw([/* thousands of items */]);\n  // Must reassign to trigger updates\n  largeDataset = [...largeDataset, newItem];\n\n  // Take a snapshot of reactive state (for external APIs)\n  function saveState() {\n    const snapshot = $state.snapshot(todos);\n    localStorage.setItem('todos', JSON.stringify(snapshot));\n  }\n</script>\n\n<button onclick={() => count++}>Count: {count}</button>\n\n{#each todos as todo}\n  <label>\n    <input type=\"checkbox\" checked={todo.done} onchange={() => toggleTodo(todo.id)} />\n    {todo.text}\n  </label>\n{/each}\n```\n\n### Declare reactive state using $state in Svelte 5\n\nReplaces implicit top-level 'let' reactivity with the explicit $state rune. This allows variables to remain reactive even when refactored outside of component top-level scopes.\n\n```svelte\n<script>\n\tlet count = $state(0);\n</script>\n```\n\n### Initialize and Update Basic Reactive State in Svelte\n\nThis Svelte component demonstrates the fundamental use of the `$state` rune to declare a reactive variable. The `count` variable is initialized with `0`, and its value is updated directly within an `onclick` handler, causing the UI to reactively display the new count.\n\n```svelte\n<script>\n\tlet count = $state(0);\n</script>\n\n<button onclick={() => count++}>\n\tclicks: {count}\n</button>\n```",
        "source": "context7",
        "word_count": 228
      }
    ]
  },
  {
    "id": "store-example-code-get-docs-2",
    "query": "React useState hook",
    "query_translation_key": "settings.app_store_examples.code.get_docs.2",
    "library": "React",
    "question": "How to use the useState hook in React",
    "status": "finished",
    "results": [
      {
        "type": "get_docs",
        "library": {
          "id": "/facebook/react",
          "title": "React",
          "description": "The library for web and native user interfaces."
        },
        "documentation": "### Manage Component State with useState Hook in React\n\nSource: https://context7.com/facebook/react/llms.txt\n\nA Hook that adds state to functional components, returning the current state value and a function to update it. It supports initial values, lazy initialization for performance, and functional updates for complex state transitions.\n\n```jsx\nimport { useState } from 'react';\n\nfunction Counter() {\n  // Basic state with initial value\n  const [count, setCount] = useState(0);\n\n  // State with lazy initialization (expensive computation)\n  const [data, setData] = useState(() => {\n    return expensiveComputation();\n  });\n\n  // State with object value\n  const [user, setUser] = useState({ name: '', email: '' });\n\n  return (\n    <div>\n      <p>Count: {count}</p>\n      {/* Direct value update */}\n      <button onClick={() => setCount(5)}>Set to 5</button>\n\n      {/* Functional update based on previous state */}\n      <button onClick={() => setCount(prev => prev + 1)}>Increment</button>\n\n      {/* Updating object state (must spread to create new reference) */}\n      <input\n        value={user.name}\n        onChange={(e) => setUser(prev => ({ ...prev, name: e.target.value }))}\n      />\n    </div>\n  );\n}\n```\n\n### Render a React Counter Component with useState and ReactDOM\n\nThis snippet demonstrates how to create a functional React component using the `useState` hook to manage state. It shows how to increment a counter and render it to the DOM using `createRoot` from `react-dom/client`.\n\n```javascript\nimport { useState } from 'react';\nimport { createRoot } from 'react-dom/client';\n\nfunction Counter() {\n  const [count, setCount] = useState(0);\n  return (\n    <>\n      <h1>{count}</h1>\n      <button onClick={() => setCount(count + 1)}>\n        Increment\n      </button>\n    </>\n  );\n}\n\nconst root = createRoot(document.getElementById('root'));\nroot.render(<Counter />);\n```",
        "source": "context7",
        "word_count": 204
      }
    ]
  },
  {
    "id": "store-example-code-get-docs-3",
    "query": "FastAPI path parameters",
    "query_translation_key": "settings.app_store_examples.code.get_docs.3",
    "library": "FastAPI",
    "question": "How to create API endpoints with path parameters in FastAPI",
    "status": "finished",
    "results": [
      {
        "type": "get_docs",
        "library": {
          "id": "/fastapi/fastapi",
          "title": "FastAPI",
          "description": "FastAPI framework, high performance, easy to learn, fast to code, ready for production."
        },
        "documentation": "### Declare Typed Path Parameters in FastAPI\n\nSource: https://github.com/fastapi/fastapi/blob/master/docs/en/docs/tutorial/path-params.md\n\nShows how to add type annotations to path parameters in FastAPI. Type declarations enable automatic data conversion, validation, and interactive API documentation generation.\n\n```python\nfrom fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get(\"/items/{item_id}\")\nasync def read_item(item_id: int):\n    return {\"item_id\": item_id}\n```\n\n### Path Parameters with Validation\n\nThe `Path()` function is used to declare path parameters with validation rules and documentation. It allows you to specify constraints like greater-than, less-than, and metadata for OpenAPI docs.\n\n```python\nfrom fastapi import FastAPI, Path\nfrom typing import Annotated\n\napp = FastAPI()\n\n@app.get(\"/items/{item_id}\")\nasync def read_item(\n    item_id: Annotated[int, Path(title=\"The ID of the item to get\", gt=0)]\n):\n    return {\"item_id\": item_id}\n```\n\n### Combine Multiple Path and Query Parameters\n\nShows how to declare multiple path and query parameters simultaneously in a single endpoint. FastAPI automatically detects which parameters are path parameters and which are query parameters based on their names.\n\n```python\nfrom fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get(\"/users/{user_id}/items/{item_id}\")\nasync def read_user_item(\n    user_id: int,\n    item_id: str,\n    q: str = None,\n    short: bool = False\n):\n    return {\n        \"user_id\": user_id,\n        \"item_id\": item_id,\n        \"q\": q,\n        \"short\": short\n    }\n```",
        "source": "context7",
        "word_count": 173
      }
    ]
  }
];

export default examples;
