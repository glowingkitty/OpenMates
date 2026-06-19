/**
 * frontend/packages/ui/src/components/interactive_questions/types.ts
 *
 * Type definitions for the InteractiveQuestions system.
 * Declares strictly validated schemas for Choice, Input, Slider, Swipe, and Rating questions
 * and their structured user responses.
 *
 * Architecture: Svelte 5 / ProseMirror custom node view schemas
 */

export type QuestionType = 'choice' | 'input' | 'slider' | 'swipe' | 'rating';

export interface BaseQuestion {
  id: string;
  type: QuestionType;
}

export interface ChoiceQuestionData extends BaseQuestion {
  type: 'choice';
  multiple: boolean;
  question: string;
  custom_option_id?: string;
  custom_placeholder?: string;
  options: Array<{
    id: string;
    text: string;
    embed_id?: string;
  }>;
}

export interface InputField {
  id: string;
  label: string;
  placeholder?: string;
  required?: boolean;
}

export interface InputQuestionData extends BaseQuestion {
  type: 'input';
  fields: InputField[];
}

export interface SliderQuestionData extends BaseQuestion {
  type: 'slider';
  question: string;
  min: number;
  max: number;
  step?: number;
  default?: number;
  labels?: Record<number, string>;
}

export interface SwipeCard {
  id: string;
  text: string;
  image_url?: string;
}

export interface SwipeQuestionData extends BaseQuestion {
  type: 'swipe';
  cards: SwipeCard[];
}

export interface RatingQuestionData extends BaseQuestion {
  type: 'rating';
  question: string;
  max_stars?: number;
  require_comment?: boolean;
  comment_placeholder?: string;
}

export type InteractiveQuestionPayload =
  | ChoiceQuestionData
  | InputQuestionData
  | SliderQuestionData
  | SwipeQuestionData
  | RatingQuestionData;

export interface ChoiceResponse {
  id: string;
  selection: string[];
  custom_answer?: string;
}

export interface InputResponse {
  id: string;
  inputs: Record<string, string>;
}

export interface SliderResponse {
  id: string;
  value: number;
}

export interface SwipeResponse {
  id: string;
  swipes: Record<string, 'like' | 'dislike'>;
}

export interface RatingResponse {
  id: string;
  rating: number;
  comment?: string;
}

export type InteractiveQuestionResponse =
  | ChoiceResponse
  | InputResponse
  | SliderResponse
  | SwipeResponse
  | RatingResponse;
