# Onboarding Architecture

## Overview

The onboarding process introduces new users to OpenMates and captures key information to personalize their experience.

## Current State

Users sign up and immediately gain access to the full web app without guided onboarding.

## Planned Features

### Learning Goals & Context Collection

**Status:** Idea stage, not implemented

During onboarding, ask users about:
- What they want to learn
- Why they want to learn it

This information can then be included in AI requests when relevant to:
- Personalize responses to user's learning goals
- Provide context-aware assistance
- Track learning progress over time

**Implementation Considerations:**
- Store preferences encrypted (privacy-preserving)
- Make context inclusion opt-in/configurable
- Allow users to update learning goals at any time
- Consider how this integrates with the memories feature

## Related Documentation

- [Web App Architecture](web_app.md)
- [Signup/Login Flow](signup_login.md)
