# Embed Preview System

## Overview

The new embed preview system provides a unified, extensible architecture for displaying various types of embedded content in the message input. It supports websites, code blocks, spreadsheets, documents, videos, and more with consistent styling and responsive behavior.

## Key Features

- **Unified Design**: All embed types use the same 300x60px base container with 30px rounded edges
- **App-Specific Branding**: Each app type (web, code, sheets, docs, videos) has its own gradient and icon
- **Responsive Layout**: Automatically switches between mobile and desktop layouts based on container width
- **Extended Previews**: Hover to reveal 300x200px extended preview areas with type-specific content
- **Grouping Support**: Multiple embeds of the same type can be grouped together with horizontal scrolling
- **Loading States**: Visual indicators for processing and failed states
- **Accessibility**: Proper focus management and keyboard navigation

## Base Structure

### Individual Embed Container

```html
<div class="embed-unified-container">
  <!-- App Icon Circle (60x60px) -->
  <div class="embed-app-icon {app-type}">
    <span class="icon icon_{app-icon}"></span>
  </div>
  
  <!-- Content Area (right side) -->
  <div class="embed-content">
    <div class="embed-text-content">
      <!-- Optional favicon -->
      <div class="embed-favicon" style="background-image: url('favicon-url')"></div>
      
      <!-- Text lines (max 2) -->
      <div class="embed-text-line">Title or main text</div>
      <div class="embed-text-line">Subtitle or metadata</div>
    </div>
  </div>
  
  <!-- Extended Preview (300x200px, shown on hover) -->
  <div class="embed-extended-preview">
    <!-- Type-specific content -->
  </div>
</div>
```

### Grouped Embeds

```html
<div class="embed-group-container">
  <div class="group-header">3 websites</div>
  <div class="group-scroll-container">
    <!-- Multiple embed-unified-container elements -->
  </div>
</div>
```

## App Types and Styling

### Web App (`web`)
- **Gradient**: Red to orange (`#ff6b6b` to `#ffa500`)
- **Icon**: Globe (`icon_globe`)
- **Extended Preview**: OG image + description

### Code App (`code`)
- **Gradient**: Blue to purple (`#4a90e2` to `#7b68ee`)
- **Icon**: Code (`icon_code`)
- **Extended Preview**: Syntax-highlighted code preview

### Sheets App (`sheets`)
- **Gradient**: Green (`#00c851` to `#00a085`)
- **Icon**: Table (`icon_table`)
- **Extended Preview**: Handsontable preview

### Docs App (`docs`)
- **Gradient**: Purple to pink (`#9c27b0` to `#e91e63`)
- **Icon**: Document (`icon_document`)
- **Extended Preview**: Rich text preview

### Videos App (`videos`)
- **Gradient**: Orange to red (`#ff5722` to `#f44336`)
- **Icon**: Video (`icon_video`)
- **Extended Preview**: Video thumbnail + metadata

## States and Variations

### Loading State
```html
<div class="embed-unified-container embed-loading">
  <!-- Shows processing indicator -->
</div>
```

### Failed State
```html
<div class="embed-unified-container embed-failed">
  <!-- Shows error indicator -->
</div>
```

### Processing State (with modify icon)
```html
<div class="embed-unified-container">
  <div class="embed-content">
    <div class="embed-text-content">
      <div class="embed-modify-icon">
        <span class="icon icon_edit"></span>
      </div>
      <div class="embed-text-line">Write</div>
      <div class="embed-text-line">28 lines...</div>
    </div>
  </div>
</div>
```

## Responsive Behavior

### Desktop Layout (≥500px width)
- Individual embeds: Standard 300x60px layout
- Grouped embeds: Horizontal scrolling container

### Mobile Layout (<500px width)
- Individual embeds: Same as desktop (no change)
- Grouped embeds: Vertical stacking with `container-mobile` class

### Responsive Implementation
The system automatically applies mobile layout to grouped previews when the `editor-content` div is less than 500px wide. Individual (ungrouped) previews always use the desktop layout regardless of container width.

## CSS Classes Reference

### Container Classes
- `.embed-unified-container` - Main embed container
- `.embed-group-container` - Group wrapper
- `.container-mobile` - Mobile layout modifier

### App Icon Classes
- `.embed-app-icon` - Base icon container
- `.embed-app-icon.web` - Web app styling
- `.embed-app-icon.code` - Code app styling
- `.embed-app-icon.sheets` - Sheets app styling
- `.embed-app-icon.docs` - Docs app styling
- `.embed-app-icon.videos` - Videos app styling

### Content Classes
- `.embed-content` - Content area wrapper
- `.embed-text-content` - Text content container
- `.embed-text-line` - Individual text line
- `.embed-favicon` - Favicon container
- `.embed-modify-icon` - Processing state icon

### Extended Preview Classes
- `.embed-extended-preview` - Extended preview container
- `.website-preview` - Website-specific preview
- `.code-preview` - Code-specific preview
- `.sheet-preview` - Sheet-specific preview

### State Classes
- `.embed-loading` - Loading state
- `.embed-failed` - Failed state

## Implementation Notes

### Text Truncation
- Text lines automatically truncate with ellipsis (`...`) when content exceeds available width
- Maximum 2 lines of text per embed
- Favicon reduces available text width when present

### Hover Behavior
- Extended preview appears on hover
- Smooth transitions for all interactive elements
- Focus management for accessibility

### Grouping Logic
- Groups are created automatically when 2+ consecutive embeds of the same type are detected
- Group headers show count (e.g., "3 websites", "2 code files")
- Horizontal scrolling for desktop, vertical stacking for mobile

### Performance Considerations
- Extended previews are hidden by default to improve rendering performance
- Code previews show only first few lines to avoid DOM bloat
- Smooth animations use CSS transitions for optimal performance

## Extensibility

### Adding New App Types

1. **Add CSS Variables**:
```css
:root {
  --gradient-newapp: linear-gradient(135deg, #color1 0%, #color2 100%);
}
```

2. **Add App Icon Class**:
```css
:global(.ProseMirror .embed-unified-container .embed-app-icon.newapp) {
  background: var(--gradient-newapp);
}
```

3. **Add Extended Preview Support**:
```css
:global(.ProseMirror .embed-unified-container .embed-extended-preview .newapp-preview) {
  /* Custom preview styling */
}
```

4. **Update Group Handlers**: Add support in the grouping system for the new app type

### Customizing Gradients
All app gradients are defined as CSS custom properties in `:root`, making them easy to customize:

```css
:root {
  --gradient-web: linear-gradient(135deg, #your-color1 0%, #your-color2 100%);
}
```

## Browser Support

- Modern browsers with CSS Grid and Flexbox support
- CSS custom properties (CSS variables)
- CSS `line-clamp` with `-webkit-` fallback
- Smooth transitions and transforms

## Accessibility

- Proper focus management with visible focus indicators
- Semantic HTML structure
- Keyboard navigation support
- Screen reader friendly text content
- High contrast support through CSS custom properties
