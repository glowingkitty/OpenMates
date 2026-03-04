/*
Purpose: Client entry point for the independent OpenMates status SPA.
Architecture: Vite-built Svelte app served by backend/status FastAPI.
See docs/architecture/status-page.md for design rationale.
Tests: N/A (status frontend tests not added yet)
*/

import { mount } from "svelte";
import App from "./App.svelte";

mount(App, {
  target: document.getElementById("app"),
});
