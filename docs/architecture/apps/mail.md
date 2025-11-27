# Mail app architecture

> This file documents the Mail app, which can be used by asking the digital team mates in a chat and later also via the OpenMates API. This file is NOT about email functionality for the OpenMates platform itself (like verification emails).

The Mail app allows users to compose, send, and manage emails through their digital team mates.

## Skills

### Create draft

The "Create draft" skill allows users to create email drafts with custom MJML (Mailjet Markup Language) code for rich email formatting.

#### MJML Code Input

The skill accepts a `code` parameter that must contain **valid MJML code**. MJML is a markup language designed to reduce the pain of coding responsive emails. It provides a semantic syntax that makes responsive email easy.

**Important Requirements:**

1. **Valid MJML Required**: The input code must be valid MJML syntax. Invalid MJML will be rejected before processing.

2. **Pre-Processing Validation**: The system validates MJML code before processing it:
   - MJML validation occurs during the conversion from MJML to HTML
   - Invalid MJML syntax will raise a `ValueError` and the draft creation will fail
   - Error messages include position information to help identify syntax issues
   - The validation ensures that only properly formatted MJML can be used for email drafts

3. **MJML Processing**: Once validated, the MJML code is:
   - Processed for includes (CSS and MJML components)
   - Rendered with template variables (if any)
   - Converted to HTML for email client compatibility
   - Inlined with CSS styles for maximum email client support

**Example MJML Structure:**

```mjml
<mjml>
  <mj-body>
    <mj-section>
      <mj-column>
        <mj-text>
          Hello World!
        </mj-text>
      </mj-column>
    </mj-section>
  </mj-body>
</mjml>
```

**Validation Process:**

The validation happens in the email rendering pipeline:
- The MJML code is parsed using the `mjml2html` function
- If the MJML is invalid, a `ValueError` is raised with detailed error information
- Error messages include the position of the problematic code
- The draft creation is rejected if validation fails

**Error Handling:**

If invalid MJML is provided:
- The skill will return an error response
- Error messages include the position of the syntax error
- The system logs detailed information about the problematic MJML region
- No draft is created when validation fails

## Settings & memories

### Writing Styles

The Mail app supports writing styles settings that help personalize email composition based on context and recipient. Each writing style entry defines how emails should be written in specific scenarios, helping maintain consistency and personalization.

**Writing Style Properties:**

- `scenario`: The type of email scenario (e.g., 'formal_business', 'casual_business', 'professional_networking', 'customer_service', 'internal_team', 'personal', etc.)
- `tone`: The overall tone (formal, semi_formal, casual, friendly, professional, conversational, warm, direct)
- `verbosity`: How detailed emails should be (very_concise, concise, balanced, detailed, very_detailed)
- `greeting_style`: Preferred greeting style (formal, semi_formal, casual, none)
- `closing_style`: Preferred closing style (formal, semi_formal, casual, warm, professional, none)
- `use_emojis`: Whether to use emojis in emails of this type
- `use_bullet_points`: When to use bullet points or lists (always, when_helpful, rarely, never)
- `paragraph_length`: Preferred paragraph length (short, medium, long, mixed)
- `use_contractions`: Whether to use contractions
- `signature_style`: How detailed the email signature should be (full, minimal, none)
- `notes`: Additional notes or specific preferences for this writing style

### Privacy-Preserving Email Addresses

> Note: To be implemented - privacy preserving settings and memories for email addresses from doctors, friends, etc. The model won't receive the actual email address but only a placeholder which then gets replaced when sending to an API (for creating a draft). Example: user asks "ask my doctor about XY" and the system uses a placeholder like `{{doctor_email}}` which is replaced with the actual email address during draft creation.

## Email Template System

The Mail app uses an MJML-based email template system for rendering emails:

- **MJML Templates**: Email templates are written in MJML format
- **Template Processing**: Templates support includes for CSS and MJML components
- **Variable Rendering**: Templates use Jinja2 for variable substitution
- **Image Embedding**: Images can be embedded as base64 or referenced via URLs
- **Dark Mode Support**: Templates support both light and dark mode variants
- **Email Client Compatibility**: MJML is converted to HTML with inline CSS for maximum compatibility

## Technical Implementation

### MJML Validation

MJML validation is performed using the `mjml` Python package's `mjml2html` function:

- **Validation Location**: `backend/core/api/app/services/email/renderer.py`
- **Validation Method**: The `convert_mjml_to_html` function attempts to convert MJML to HTML
- **Error Detection**: Invalid MJML raises a `ValueError` with detailed error information
- **Error Logging**: Errors are logged with position information and context around the problematic code

### Email Rendering Pipeline

1. **MJML Input**: Receive MJML code from the skill
2. **Include Processing**: Process CSS and MJML component includes
3. **Template Rendering**: Render Jinja2 template variables (if any)
4. **Brand Processing**: Process brand name and mark tags
5. **Image Embedding**: Embed images as base64 or process image URLs
6. **MJML Validation**: Convert MJML to HTML (validation occurs here)
7. **HTML Processing**: Process links and apply styling
8. **CSS Inlining**: Inline CSS styles for email client compatibility
9. **Output**: Return rendered HTML ready for email clients