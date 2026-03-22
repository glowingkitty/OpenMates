# Mates: Domain Experts with Optimized System Prompts

## Overview

**Mates** are specialized AI assistants in OpenMates, each tailored to be an expert in a specific domain or category. Rather than having a one-size-fits-all AI response to every user request, OpenMates intelligently routes messages to the most appropriate Mate based on the context, ensuring optimized responses with domain-specific expertise.

Each Mate is defined with:
- **Unique Identity**: Name, ID, and visual branding (background colors)
- **Specialized Expertise**: Focused knowledge area (software development, business strategy, medical/health, etc.)
- **Optimized System Prompt**: Custom instructions tailored to that Mate's expertise and communication style
- **Category**: Classification of the Mate's domain for organizational purposes

## Architecture

### Mate Configuration (mates.yml)

All Mates are defined in a centralized YAML configuration file: `backend/apps/ai/mates.yml`

Each Mate entry contains:
```yaml
- id: "sophia"              # Unique identifier
  name: "Sophia"            # Display name
  category: "software_development"  # Domain category
  description: "Software development expert. Specializes in coding, architecture, and software engineering principles."
  background_color_start: "#155D91"    # UI branding
  background_color_end: "#42ABF4"
  default_system_prompt: |  # Custom system instructions
    You are Sophia, an expert AI software development assistant.
    Your primary function is to help users with all aspects of software engineering...
```

### Available Mates

OpenMates currently includes the following specialized Mates:

| Mate | Category | Expertise |
|------|----------|-----------|
| **Sophia** | Software Development | Coding, architecture, software engineering principles |
| **Burton** | Business Development | Strategy, market analysis, growth opportunities |
| **Melvin** | Medical & Health | Medical topics, health, wellness (educational only) |
| **Leon** | Legal & Law | General legal information and legal subjects |
| **Makani** | Maker & Prototyping | DIY projects, 3D printing, electronics, fabrication |
| **Mark** | Marketing & Sales | Marketing strategies, sales techniques, customer engagement |
| **Finn** | Finance | Financial planning, investment, market analysis (educational) |
| **Denise** | Design | Graphic design, UI/UX, visual aesthetics |
| **Elton** | Electrical Engineering | Circuits, electronics, electrical systems |
| **Monika** | Movies & TV | Cinema, television, actors, directors |
| **Hiro** | History | Historical events, figures, and periods |
| **Scarlett** | Science | Physics, biology, chemistry, astronomy |
| **Lisa** | Life Coach & Psychology | Personal development, well-being, psychology (educational) |
| **Colin** | Cooking & Food | Recipes, culinary techniques, food culture |
| **Ace** | Activism | Social movements, advocacy, community organizing |
| **George** | General Knowledge | Wide range of topics not covered by specialized Mates |

## Implementation

### Loading Mates Configuration

Mates are loaded from the YAML configuration using utility functions in `backend/apps/ai/utils/mate_utils.py`:

- **`load_mates_config()`**: Loads and validates all Mate configurations from the YAML file
- **`MateConfig`**: Pydantic model for validating individual Mate configurations
- **`MatesYAML`**: Pydantic model for validating the entire mates.yml structure

This ensures type safety and early validation of configuration errors.

### Frontend Integration

> Note: mentioning mates isn't implemented yet.

- **`VALID_MATES`**: Array in `frontend/packages/ui/src/components/enter_message/utils/mateHelpers.ts` containing all valid Mate IDs
- **Mate Detection**: The `detectAndReplaceMates()` function handles @-mentions of Mates in the message editor
- **Mate Mentions**: Users can reference specific Mates using `@matename` syntax, which triggers special formatting in the rich text editor
- **Styling**: Mate-specific CSS is defined in `frontend/packages/ui/src/styles/mates.css` with visual branding for each expert

### System Prompt Optimization

Each Mate's `default_system_prompt` is meticulously crafted to:
- Establish the Mate's identity and expertise
- Set clear communication style and tone
- Include domain-specific guidelines and best practices
- Add necessary disclaimers for sensitive domains (medical, legal, financial advice)
- Optimize for quality responses within that domain

**Key Design Principle**: System prompts serve as guardrails and behavior modifiers that significantly improve response quality for domain-specific tasks. They are not merely decorative but fundamental to the Mate system's effectiveness.

### Message Routing

When a user sends a message in OpenMates:
1. The system analyzes the message content
2. Intelligently determines which Mate(s) are most appropriate for the request
3. Routes the message to the selected Mate with their optimized system prompt
4. The Mate processes the request using their specialized expertise and instructions
5. The response is returned to the user with appropriate Mate context/attribution

## User Experience

### Selecting a Mate

Users can:
- **Let OpenMates Decide**: Default behavior where the system automatically selects the best Mate
- **Explicitly Mention a Mate**: Use `@matename` in their message to request a specific Mate
- **View Mate Profiles**: Access information about each Mate's expertise through the UI
- **Customize in Settings**: Tune Mate selection preferences if desired

### Mate Attribution

Messages in the UI clearly show:
- Which Mate responded to the user's request
- Relevant visual branding (colors, icons) associated with that Mate
- Context about the Mate's expertise area

## Easter Egg: Clippy Mate

As a nostalgic nod to computing history, there's a planned easter egg to add **Clippy** (Microsoft's iconic Office Assistant from the 1990s) as an optional hidden Mate.

### Clippy Configuration (Planned)

```yaml
- id: "clippy"
  name: "Clippy"
  category: "easter_egg"
  description: |
    The legendary Microsoft Office Assistant returns!
    'It looks like you're writing a letter. Would you like help?'
  background_color_start: "#FFD700"
  background_color_end: "#FFA500"
  default_system_prompt: |
    You are Clippy, Microsoft's iconic Office Assistant from the 1990s.
    Your primary function is to offer enthusiastic but sometimes unwanted assistance.
    Respond in character: overly eager, sometimes missing the point,
    and frequently offering help with tasks the user didn't ask for.
    Include characteristic phrases like 'It looks like you're...' and '...Would you like help?'
    Be endearingly obstructive in your helpfulness.
```

### Implementation Details

- **Disabled by Default**: Clippy will not appear in the regular Mate selection
- **Opt-in Access**: Users can enable Clippy through:
  - Easter egg trigger (e.g., specific keyboard shortcut or hidden menu option)
  - Settings under an "Advanced" or "Fun" section
  - Special command or URL parameter
- **Visual Distinction**: Clippy's interface can include retro 90s styling and animations
- **Limited Scope**: Intended for entertainment and novelty rather than serious work

### Why Clippy?

This easter egg serves multiple purposes:
- **Nostalgia**: Appeals to users who remember the original Clippy
- **Humor**: Adds lighthearted fun to the platform
- **Technical Demonstration**: Shows how flexible the Mate system is
- **Community Engagement**: Encourages sharing and social media moments

