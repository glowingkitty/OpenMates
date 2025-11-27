# Learning Mode

> Plannet feature. Not yet implemented.

## Overview

Learning Mode is a global chat setting that adjusts the AI's responses to prioritize explanation and educational value over quick solutions. When enabled, the AI focuses on helping users understand concepts, learn problem-solving approaches, and develop critical thinking skills. This mode is particularly useful for students, teenagers, and anyone seeking to deepen their understanding of a subject.

## What is Learning Mode?

Learning Mode modifies the system prompt across all chats (unless a specific app or focus mode overrides it) to:

- **Explain concepts**: Break down complex ideas into understandable components
- **Guide discovery**: Use Socratic questioning to help users arrive at solutions themselves
- **Provide rationale**: Explain the "why" behind solutions, not just the "what"
- **Encourage practice**: Suggest exercises to reinforce learning
- **Adapt difficulty**: Scale explanations to the user's knowledge level
- **Ask clarifying questions**: Understand the user's current understanding before responding

## How Learning Mode Works

### Global Setting

Learning Mode is a toggle in **Settings > Learning & Development > Learning Mode**:

- **Off (default)**: Normal chat behavior - the AI provides direct answers and solutions
- **On**: Learning-focused behavior - the AI prioritizes explanation and guided learning

### Behavior Changes

When enabled, the AI explains before coding, asks assessment questions, provides multiple approaches with pros/cons, suggests practice exercises, uses analogies, slows down pacing, and encourages follow-up questions.

### Example

**Without Learning Mode:**

```text
User: How do I reverse a string in Python?
AI: s = "hello"
reversed_s = s[::-1]
print(reversed_s)
```

**With Learning Mode:**

```text
User: How do I reverse a string in Python?
AI: Great question! Let me explain the concept first. In Python, we can use 
slice notation [::-1] which means: start from the end, go to the beginning, 
step by -1. Here are a few approaches:

1. Slicing (most Pythonic): s[::-1]
2. Using reversed(): ''.join(reversed(s))
3. Using a loop: Build the string character by character

Can you explain why the slicing approach works? What does the -1 do?
```

## Interaction with Focus Modes and Apps

**Priority Order:**

1. App-specific settings (e.g., Study app's focus modes)
2. Focus modes (when activated)
3. Learning Mode (applied to general conversations)

Learning Mode works across all apps: Code (algorithm explanation), Web (research methodology), Math (problem-solving steps), Writing (writing principles).

## Settings and Customization

When enabled, users can customize:

- **Explanation depth**: Basic / Intermediate / Advanced
- **Question frequency**: Low / Medium / High
- **Language level**: Simple or technical terminology
- **Include examples**: Toggle for code/worked examples
- **Practice suggestions**: Off / Sometimes / Always

Learning Mode respects app memories: current knowledge level, learning goals, preferred learning style, and previous topics.

## Technical Implementation

Learning Mode works by:

1. Detecting the setting from user preferences
2. Modifying system prompt with learning-specific instructions
3. Cascading to all responses unless overridden by focus modes or app-specific settings

**Storage**: Client-side preference synced to user profile for cross-device consistency. Each profile (child, teen, adult) can have different settings.

## Privacy and Safety

Learning Mode is purely an AI behavior modification:

- No data collection or tracking of learning performance
- Learning conversations aren't indexed separately
- User control: can be toggled on/off at any time
- Transparent: users know when Learning Mode is active

## For Parents and Educators

### Setting Up Learning Mode

1. Enable for teen profiles in **Settings > Learning & Development**
2. Customize preferences (explanation depth, language level)
3. Set learning goals in app memories
4. Monitor usage via conversation history

### Benefits

- Encourages critical thinking through Socratic questioning
- Reduces plagiarism by focusing on understanding
- Builds confidence through guided learning
- Supports diverse learning styles

**Future Integration**: Learning Mode could be combined with passcode protection and parental control options to ensure it remains enabled for educational profiles and prevent unauthorized changes.

## Limitations

- Not a replacement for teachers - should supplement, not replace, human instruction
- Requires active engagement for best results
- Limited to AI's training data and understanding
- No learning progress tracking or performance reports

## Future Enhancements

Potential improvements:

- Learning path recommendations based on goals
- Progress tracking for concepts learned and areas needing review
- Spaced repetition integration
- Performance analytics showing learning patterns
- Certification path guidance
- Integration with passcode protection and parental controls for enhanced safety

## Related Documentation

- [Study App Architecture](./apps/study.md) - Educational focus modes within the Study app
- [Focus Modes](./apps/focus_modes.md) - Temporary behavior modifications for specific tasks
- [App Settings and Memories](./apps/app_settings_and_memories.md) - How apps store user learning preferences
- [Mates Profiles](./mates.md) - Different profiles (child, teen, adult) with custom settings
