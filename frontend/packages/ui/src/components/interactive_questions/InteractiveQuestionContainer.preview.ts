/**
 * frontend/packages/ui/src/components/interactive_questions/InteractiveQuestionContainer.preview.ts
 *
 * Mock data and variants for the InteractiveQuestionContainer preview page.
 * Exposes Choice, Input, Slider, Swipe, and Rating configurations.
 *
 * Architecture: Svelte 5 / Developer Component Previews
 */

import type { InteractiveQuestionPayload } from './types';

// Default mock payload (Choice Single-Select)
const defaultPayload: InteractiveQuestionPayload = {
  id: "python_slice_step",
  type: "choice",
  multiple: false,
  question: "What does a step of `-1` do in the slice `s[start:stop:-1]`?",
  options: [
    { id: "opt_reverse", text: "Reverses the direction of slicing and steps backward" },
    { id: "opt_error", text: "Triggers a ValueError in Python" },
    { id: "opt_skip", text: "Skips every other character starting from index 1" }
  ]
};

// Named variants for each question type
export const variants = {
  choice_multi: {
    payload: {
      id: "python_fences_check",
      type: "choice",
      multiple: true,
      question: "Which of these are valid markdown code fence delimiters?",
      options: [
        { id: "opt_three_backticks", text: "``` (Three backticks)" },
        { id: "opt_three_tildes", text: "~~~ (Three tildes)" },
        { id: "opt_four_backticks", text: "```` (Four backticks)" },
        { id: "opt_four_spaces", text: "    (Four spaces - block indent)" }
      ]
    } as InteractiveQuestionPayload,
    chatId: "demo-for-everyone"
  },
  choice_custom: {
    payload: {
      id: "project_direction",
      type: "choice",
      multiple: false,
      question: "What should we work on next?",
      custom_option_id: "own_answer",
      custom_placeholder: "Type your own answer",
      options: [
        { id: "ship_fix", text: "Ship the bug fix" },
        { id: "write_docs", text: "Write documentation" },
        { id: "improve_tests", text: "Improve test coverage" },
        { id: "own_answer", text: "I give you my own answer" }
      ]
    } as InteractiveQuestionPayload,
    chatId: "demo-for-everyone"
  },
  input_form: {
    payload: {
      id: "onboarding_form",
      type: "input",
      question: "Please introduce yourself to the assistant",
      fields: [
        { id: "name", label: "Full Name", placeholder: "e.g., Jane Doe", required: true },
        { id: "profession", label: "Profession", placeholder: "e.g., Software Engineer", required: false },
        { id: "experience", label: "Years of Experience", placeholder: "e.g., 5", required: true }
      ]
    } as InteractiveQuestionPayload,
    chatId: "demo-for-everyone"
  },
  slider_scale: {
    payload: {
      id: "understanding_recursion",
      type: "slider",
      question: "How confident do you feel explaining recursion to a beginner?",
      min: 1,
      max: 5,
      step: 1,
      default: 3,
      labels: {
        1: "No clue",
        3: "Somewhat confident",
        5: "Extreme master"
      }
    } as InteractiveQuestionPayload,
    chatId: "demo-for-everyone"
  },
  swipe_cards: {
    payload: {
      id: "ux_layouts",
      type: "swipe",
      question: "Review these UI Layout proposals",
      cards: [
        { id: "minimalist", text: "Minimalist: ultra-light borders, 64px line heights, and pastel backgrounds." },
        { id: "brutalist", text: "Brutalist: 4px thick black borders, 90-degree corners, and neon contrast fills." },
        { id: "skeuomorphic", text: "Skeuomorphic: heavy gradients, drop shadows, glass reflections, and physical textures." }
      ]
    } as InteractiveQuestionPayload,
    chatId: "demo-for-everyone"
  },
  rating_stars: {
    payload: {
      id: "session_rating",
      type: "rating",
      question: "Rate your experience with the OpenMates developer console",
      max_stars: 5,
      require_comment: false,
      comment_placeholder: "Let us know how we can improve..."
    } as InteractiveQuestionPayload,
    chatId: "demo-for-everyone"
  }
};

export default {
  payload: defaultPayload,
  chatId: "demo-for-everyone"
};
