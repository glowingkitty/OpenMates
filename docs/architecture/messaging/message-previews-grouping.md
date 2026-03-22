# Message Previews Grouping Architecture

## Overview

The message previews grouping system provides a dynamic, extensible architecture for grouping consecutive embed nodes of the same type in the message input. This system allows multiple embeds (websites, code blocks, documents, spreadsheets) to be visually grouped together while maintaining individual functionality.

## Supported Embed Types

Currently, the system supports grouping for:
- **Websites** (`web-website`) - Regular websites with metadata
- **Videos** (`videos-video`) - YouTube URLs and other video content
- **Code blocks** (`code-code`) - All programming languages grouped together
- **Documents** (`docs-doc`) - HTML documents and similar content
- **Spreadsheets** (`sheets-sheet`) - Table-based data

## Architecture Components

### 1. Group Handler Interface (`EmbedGroupHandler`)

The core interface that defines how each embed type handles grouping behavior.

**Implementation**: `frontend/packages/ui/src/message_parsing/groupHandlers.ts`

### 2. Group Handler Registry (`GroupHandlerRegistry`)

Central registry that manages all group handlers and provides unified access:

- **Registration**: Automatically registers handlers for supported embed types
- **Handler lookup**: Finds appropriate handlers for embed types and group types
- **Grouping logic**: Determines if two embeds can be grouped together
- **Delegation**: Routes operations to the correct handler

### 3. Specific Group Handlers

#### WebWebsiteGroupHandler
- Groups `web-website` embeds together
- Handles URL-based content with metadata
- Supports both successful (with metadata) and failed (URL-only) states

#### VideosVideoGroupHandler
- Groups `videos-video` embeds together (YouTube URLs, etc.)
- Handles video thumbnails and metadata
- Supports both successful (with thumbnail) and failed (URL-only) states

#### CodeCodeGroupHandler
- Groups all `code-code` embeds regardless of programming language
- Maintains language and filename information for individual items
- Supports processing and finished states

#### DocsDocGroupHandler
- Groups `docs-doc` embeds (HTML documents)
- Preserves title information
- Handles document_html fence conversion

#### SheetsSheetGroupHandler
- Groups `sheets-sheet` embeds (spreadsheets/tables)
- Maintains row/column information
- Supports table markdown conversion

**Implementation**: All handlers are in `frontend/packages/ui/src/message_parsing/groupHandlers.ts`

### 4. Group Renderer (`GroupRenderer`)

Generic renderer that handles visual display of all group types:

- **Dynamic rendering**: Adapts display based on embed type
- **Consistent layout**: Uses unified CSS classes and structure
- **Item display**: Renders individual items within groups
- **Header generation**: Creates appropriate group headers (e.g., "3 websites", "2 code files")

**Implementation**: `frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/GroupRenderer.ts`

## Grouping Process

### 1. Document Parsing

**Flow**: Markdown → Individual Embeds → Document Enhancement → Grouping → Final Document

1. **Parse embed nodes**: Extract individual embeds from markdown
2. **Enhance document**: Replace json_embed blocks with embed nodes
3. **Group consecutive embeds**: Use group handlers to create groups
4. **Generate final document**: Return TipTap document with groups

**Implementation**: `frontend/packages/ui/src/message_parsing/parse_message.ts`

### 2. Grouping Logic

The system groups embeds when:
- They are consecutive in the document (only whitespace between them)
- They are of compatible types (determined by group handlers)
- There are 2 or more consecutive compatible embeds

**Implementation**: `frontend/packages/ui/src/message_parsing/embedGrouping.ts` - See `groupConsecutiveEmbedsInParagraph` function

### 3. Group Creation

When creating groups:
1. **Sort items**: Processing status first, then finished
2. **Generate group ID**: Unique identifier for the group
3. **Set group type**: `{embedType}-group` (e.g., `web-website-group`)
4. **Store metadata**: Group count and individual item data

**Implementation**: Each group handler's `createGroup` method in `frontend/packages/ui/src/message_parsing/groupHandlers.ts`

## Backspace Behavior

The system provides sophisticated backspace handling for groups:

### Split Group
When backspacing a group with multiple items:
1. Remove the last item from the group
2. Keep remaining items as individual rendered embeds
3. Convert the last item back to editable text/markdown

### Convert to Text
When backspacing a single-item group:
1. Convert the group back to individual embed
2. Then convert to editable markdown format

### Delete Group
When backspacing an empty group:
1. Simply delete the entire group node

**Implementation**: `handleGroupBackspace` method in each group handler + keyboard shortcuts in `frontend/packages/ui/src/components/enter_message/extensions/Embed.ts`

## Serialization

Groups are serialized back to markdown by:
1. **Individual serialization**: Each item in the group is serialized separately
2. **Appropriate spacing**: Items are separated by newlines or spaces
3. **Format preservation**: Original markdown format is maintained

Example:
````markdown
// Website group serializes to:
```json_embed
{"type": "website", "url": "https://example.com"}
```

```json_embed
{"type": "website", "url": "https://test.com"}
```

// Code group serializes to:
```javascript:main.js
```

```python:app.py
```
````

## Rendering System

### Group Display Structure
```html
<div class="{type}-preview-group">
  <div class="group-header">3 websites</div>
  <div class="group-scroll-container">
    <div class="embed-unified-container" data-embed-type="website">
      <!-- Individual item content -->
    </div>
    <!-- More items... -->
  </div>
</div>
```

### CSS Classes
- `.{type}-preview-group`: Main group container
- `.group-header`: Group title/count display
- `.group-scroll-container`: Horizontal scrollable container
- `.embed-unified-container`: Individual item wrapper

## Extensibility

### Adding New Embed Types

1. **Create Group Handler**:
```typescript
export class NewTypeGroupHandler implements EmbedGroupHandler {
  embedType = 'newtype';
  
  canGroup(nodeA, nodeB) {
    return nodeA.type === 'newtype' && nodeB.type === 'newtype';
  }
  
  // Implement other methods...
}
```

2. **Register Handler**:
```typescript
// In GroupHandlerRegistry constructor
this.register(new NewTypeGroupHandler());
```

3. **Add Renderer Support**:
```typescript
// In embed_renderers/index.ts
'newtype-group': new GroupRenderer(),
```

4. **Update GroupRenderer**:
```typescript
// Add rendering logic for the new type
private renderNewTypeItem(item: EmbedNodeAttributes): string {
  // Custom rendering logic
}
```

### Configuration

The system is designed to be configurable:
- **Group size limits**: Can be configured per embed type
- **Grouping criteria**: Customizable through handler logic
- **Display options**: Flexible rendering through GroupRenderer
- **Serialization format**: Customizable per embed type

## Error Handling

The system includes robust error handling:
- **Missing handlers**: Graceful fallback to individual embeds
- **Invalid group data**: Safe defaults and error logging
- **Serialization errors**: Fallback to basic text representation
- **Rendering errors**: Error boundaries and safe defaults

## Performance Considerations

- **Lazy evaluation**: Groups are only created when needed
- **Efficient lookups**: Handler registry uses Map for O(1) lookups
- **Minimal DOM updates**: Groups update only when content changes
- **Memory management**: Proper cleanup of group resources

## Testing

The system includes comprehensive tests:
- **Unit tests**: Individual handler functionality
- **Integration tests**: Full grouping workflow
- **Edge cases**: Empty groups, single items, mixed types
- **Performance tests**: Large numbers of embeds

## Future Enhancements

Planned improvements:
- **Drag & drop**: Reordering items within groups
- **Nested groups**: Groups within groups for complex content
- **Custom grouping rules**: User-defined grouping criteria
- **Group templates**: Predefined group layouts
- **Analytics**: Group usage tracking and optimization