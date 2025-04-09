# Design Guidelines

## Table of Contents

- [Design Guidelines](#design-guidelines)
  - [Table of Contents](#table-of-contents)
  - [1. Core Design Principles](#1-core-design-principles)
  - [2. Branding \& Visual Identity](#2-branding--visual-identity)
  - [3. Layout \& Spacing](#3-layout--spacing)
  - [4. UI Components \& Patterns](#4-ui-components--patterns)
  - [5. Iconography \& Imagery](#5-iconography--imagery)
  - [6. Accessibility (a11y)](#6-accessibility-a11y)
  - [7. Tone of Voice](#7-tone-of-voice)

## 1. Core Design Principles

*   **Familiarity & Simplicity:** The interface should feel intuitive and familiar, drawing inspiration from common chat application patterns to minimize the learning curve.
*   **Seamless Experience:** Prioritize a single-page application feel, using smooth transitions (e.g., side panels) instead of full page reloads for most actions.
*   **Ease of Use + Power:** Strive for an interface that is exceptionally easy to use for non-technical users while offering powerful features for advanced interactions.
*   **User-Centric:** Focus on maximizing usefulness and addressing user frustrations found in existing AI tools.
*   **Accessibility:** Ensure the product is understandable and usable for everyone, regardless of technical background.
*   **Friendly Tone:** Communication within the app should feel relaxed and friendly, like talking to a helpful teammate, avoiding overly formal or corporate language.

## 2. Branding & Visual Identity

*   **Logo:**
    *   The logo is the wordmark "OpenMates".
    *   "Open" uses a gradient: `linear-gradient(135deg, #4867CD 9.04%, #5A85EB 90.06%)` (defined as `--color-primary`).
    *   "Mates" is white (`#ffffff`) on dark backgrounds or black (`#000000`) on light backgrounds.
    *   *(Note: Specific spacing/usage guidelines TBD).*
*   **Color Palette:**
    *   The full color palette is defined in `frontend/packages/ui/src/styles/theme.css`. This file is the single source of truth for colors.
    *   **Primary Gradient:** `linear-gradient(135deg, #4867CD 9.04%, #5A85EB 90.06%)` (`--color-primary`). Used for key branding elements like the "Open" part of the logo.
    *   **Key Neutrals (Greys):** A scale from `--color-grey-0` (`#ffffff` light / `#171717` dark) to `--color-grey-100` (`#000000` light / `#ffffff` dark) is used extensively for backgrounds, text, and UI elements. Refer to `theme.css` for specific shades (`--color-grey-10`, `--color-grey-20`, etc.) and their light/dark theme values.
    *   **App Colors:** Specific gradients are defined for different app integrations (e.g., `--color-app-ai`, `--color-app-finance`). See `theme.css`.
    *   **Font Colors:** Defined variables like `--color-font-primary`, `--color-font-secondary`, etc. See `theme.css`.
    *   **Button Colors:** Defined variables like `--color-button-primary`, `--color-button-secondary`, etc. See `theme.css`.
*   **Typography:**
    *   **Primary Font:** Lexend Deca should be used for all UI text by default.
    *   **Fallback Fonts:** Standard system fonts should be used as fallbacks, especially for languages not fully supported by Lexend Deca (e.g., CJK languages).
    *   *(Note: Specific sizes, weights, line heights TBD or should be defined consistently in the UI components/CSS).*

## 3. Layout & Spacing

*   **Consistency is Key:** While specific rules (e.g., 8px grid, standard spacing variables) are not formally defined yet, strive for consistency in margins, padding, and alignment across all UI elements and pages.
*   **Responsiveness:** Design layouts to be responsive and adapt gracefully to various screen sizes, considering mobile, tablet, and desktop views. Employ techniques like Flexbox and CSS Grid.
*   **Clarity & Balance:** Avoid overly cluttered interfaces. Ensure sufficient white space to improve readability and visual hierarchy.

## 4. UI Components & Patterns

*   **Component Library:** Reusable UI components (buttons, inputs, cards, etc.) are implemented in Svelte and located in `frontend/packages/ui/src/components`. Use these existing components whenever possible to maintain consistency.
*   **Design Source:** Visual specifications and detailed interaction designs are maintained in the project's design files (Figma, migrating to Penpot). These files serve as the source of truth for component appearance and behavior.
*   **Core Interaction Patterns:**
    *   **Chat Interface:** The central interaction paradigm mimics familiar chat applications.
    *   **Side Panels:** Utilize non-modal side panels for displaying supplementary information or actions, reinforcing the single-page application feel.
*   **New Components:** When creating new components, ensure they align with the established visual style, core principles, and accessibility requirements.

## 5. Iconography & Imagery

*   **Format:** Prioritize vector graphics (SVG, CSS shapes) for all UI elements, icons, and illustrations to ensure scalability, quality, and performance. Raster images (PNG, JPG) should only be used when unavoidable (e.g., user profile pictures, user-uploaded content).
*   **Source:** Icons are custom-designed and should be sourced from the project's design files (Figma/Penpot) and exported as optimized SVGs.
*   **Consistency:** Maintain consistency in icon style (stroke width, level of detail) as defined in the design source.

## 6. Accessibility (a11y)

*   **Goal:** Strive to make the application accessible and usable for everyone, including users with disabilities. While not strictly audited yet, aim towards compliance with **WCAG 2.1 Level AA** as a guiding standard.
*   **Key Considerations:**
    *   **Keyboard Navigation:** All interactive elements MUST be navigable and operable using only the keyboard. Implement logical focus order and visible focus indicators. (Keyboard shortcuts are a helpful addition but not sufficient on their own).
    *   **Semantic HTML:** Use appropriate HTML elements (e.g., `<button>`, `<nav>`, `<main>`, headings) to convey structure and meaning to assistive technologies.
    *   **Color Contrast:** Ensure sufficient contrast between text and background colors to meet WCAG AA requirements, aiding users with visual impairments.
    *   **Screen Reader Compatibility:** Test critical user flows with screen readers (e.g., NVDA, VoiceOver) to ensure content is announced logically and interactively. Use ARIA attributes where necessary to enhance semantics.
    *   **Alternative Text:** Provide descriptive alt text for meaningful images (though primarily using vector graphics reduces this need).

## 7. Tone of Voice

*   **Style:** Friendly, relaxed, approachable, and helpful – like conversing with a knowledgeable friend or teammate.
*   **Clarity:** Use clear and simple language. Avoid technical jargon where possible (e.g., prefer "digital team mates" over "AI agents" in user-facing text).
*   **Directness:** Be direct and informative.
*   **Consistency:** Maintain this tone across all UI text, including button labels, instructions, empty states, and messages from the digital teammates.
*   **Localization:** Keep the language relatively straightforward to facilitate easier and more natural translation into other languages (e.g., avoiding complex idioms that might not translate well).