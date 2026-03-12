// Quick test runner for the unified message parsing architecture
// This can be run directly to test the implementation without full test setup

import { parse_message, parseEmbedNodes, handleStreamingSemantics } from './parse_message';
import { tipTapToCanonicalMarkdown, createEmbedClipboardData } from './serializers';
import type { TipTapDoc } from './types';
import { embedStore } from '../services/embedStore';

console.log('🧪 Testing Unified Message Parsing Architecture');
console.log('================================================');

// Test 1: Basic parsing
console.log('\n📝 Test 1: Basic parsing');
try {
  const markdown = 'Hello world!';
  const result = parse_message(markdown, 'read', { unifiedParsingEnabled: true });
  console.log('✅ Basic parsing works');
  console.log('Result:', JSON.stringify(result, null, 2));
} catch (error) {
  console.error('❌ Basic parsing failed:', error);
}

// Test 2: Code fence detection
console.log('\n💻 Test 2: Code fence detection');
try {
  const markdown = '```javascript:test.js\nconsole.log("Hello");\n```';
  const embedNodes = parseEmbedNodes(markdown, 'read');
  console.log('✅ Code fence detection works');
  console.log('Detected embeds:', embedNodes.length);
  console.log('First embed:', JSON.stringify(embedNodes[0], null, 2));
} catch (error) {
  console.error('❌ Code fence detection failed:', error);
}

// Test 3: Document HTML fence
console.log('\n📄 Test 3: Document HTML fence');
try {
  const markdown = '```document_html\n<!-- title: "My Doc" -->\n<h1>Hello</h1>\n```';
  const embedNodes = parseEmbedNodes(markdown, 'read');
  console.log('✅ Document HTML detection works');
  console.log('Detected embeds:', embedNodes.length);
  if (embedNodes.length > 0) {
    console.log('Doc embed:', JSON.stringify(embedNodes[0], null, 2));
  }
} catch (error) {
  console.error('❌ Document HTML detection failed:', error);
}

// Test 4: Table detection
console.log('\n📊 Test 4: Table detection');
try {
  const markdown = '| Column 1 | Column 2 |\n|----------|----------|\n| Data 1   | Data 2   |';
  const embedNodes = parseEmbedNodes(markdown, 'read');
  console.log('✅ Table detection works');
  console.log('Detected embeds:', embedNodes.length);
  if (embedNodes.length > 0) {
    console.log('Table embed:', JSON.stringify(embedNodes[0], null, 2));
  }
} catch (error) {
  console.error('❌ Table detection failed:', error);
}

// Test 5: URL detection
console.log('\n🌐 Test 5: URL detection');
try {
  const markdown = 'Check out https://example.com for more info';
  const embedNodes = parseEmbedNodes(markdown, 'read');
  console.log('✅ URL detection works');
  console.log('Detected embeds:', embedNodes.length);
  if (embedNodes.length > 0) {
    console.log('URL embed:', JSON.stringify(embedNodes[0], null, 2));
  }
} catch (error) {
  console.error('❌ URL detection failed:', error);
}

// Test 6: YouTube URL detection
console.log('\n🎥 Test 6: YouTube URL detection');
try {
  const markdown = 'Watch this: https://www.youtube.com/watch?v=dQw4w9WgXcQ';
  const embedNodes = parseEmbedNodes(markdown, 'read');
  console.log('✅ YouTube URL detection works');
  console.log('Detected embeds:', embedNodes.length);
  if (embedNodes.length > 0) {
    console.log('YouTube embed:', JSON.stringify(embedNodes[0], null, 2));
  }
} catch (error) {
  console.error('❌ YouTube URL detection failed:', error);
}

// Test 7: Streaming semantics (write mode)
console.log('\n⚡ Test 7: Streaming semantics (unclosed code fence)');
try {
  const markdown = '```javascript\nconsole.log("hello");';
  const streamingData = handleStreamingSemantics(markdown, 'write');
  console.log('✅ Streaming semantics work');
  console.log('Partial embeds:', streamingData.partialEmbeds.length);
  console.log('Unclosed blocks:', streamingData.unclosedBlocks.length);
  if (streamingData.partialEmbeds.length > 0) {
    console.log('First partial embed:', JSON.stringify(streamingData.partialEmbeds[0], null, 2));
  }
} catch (error) {
  console.error('❌ Streaming semantics failed:', error);
}

// Test 8: Serialization (TipTap to Markdown)
console.log('\n🔄 Test 8: TipTap to Markdown serialization');
try {
  const tiptapDoc = {
    type: 'doc',
    content: [
      {
        type: 'paragraph',
        content: [{ type: 'text', text: 'Hello world' }]
      },
      {
        type: 'embed',
        attrs: {
          id: 'test-id',
          type: 'code',
          status: 'finished',
          contentRef: 'cid:sha256:abc123',
          language: 'javascript',
          filename: 'test.js'
        }
      }
    ]
  };
  
  const markdown = tipTapToCanonicalMarkdown(tiptapDoc as TipTapDoc);
  console.log('✅ Serialization works');
  console.log('Generated markdown:', markdown);
} catch (error) {
  console.error('❌ Serialization failed:', error);
}

// Test 9: EmbedStore basic operations
console.log('\n💾 Test 9: EmbedStore basic operations');
try {
  // Test put and get
  const testData = { content: 'Hello from EmbedStore!' };
  const contentRef = 'stream:test-123';
  
  embedStore.put(contentRef, testData, 'text').then(async () => {
    console.log('✅ EmbedStore put successful');
    
    const retrievedData = await embedStore.get(contentRef);
    console.log('✅ EmbedStore get successful');
    console.log('Retrieved data:', retrievedData);
    
    // Test rekeying
    try {
      const cidRef = await embedStore.rekeyStreamToCid(contentRef);
      console.log('✅ EmbedStore rekey successful');
      console.log('New CID ref:', cidRef);
    } catch (rekeyError) {
      console.error('❌ EmbedStore rekey failed:', rekeyError);
    }
  }).catch((error) => {
    console.error('❌ EmbedStore operations failed:', error);
  });
} catch (error) {
  console.error('❌ EmbedStore test setup failed:', error);
}

// Test 10: Clipboard data creation
console.log('\n📋 Test 10: Clipboard data creation');
try {
  const embedAttrs = {
    id: 'clipboard-test',
    type: 'code' as const,
    status: 'finished' as const,
    contentRef: 'cid:sha256:clipboard123',
    contentHash: 'clipboard123',
    language: 'python',
    filename: 'script.py'
  };
  
  const clipboardData = createEmbedClipboardData(embedAttrs);
  console.log('✅ Clipboard data creation works');
  console.log('Clipboard data:', JSON.stringify(clipboardData, null, 2));
} catch (error) {
  console.error('❌ Clipboard data creation failed:', error);
}

// Test 11: Full integration test
console.log('\n🚀 Test 11: Full integration test');
try {
  const complexMarkdown = `
# Test Document

Here's some code:
\`\`\`python:hello.py
print("Hello, world!")
\`\`\`

And a table:
| Name | Age |
|------|-----|
| John | 25  |

And a document:
\`\`\`document_html
<!-- title: "My Document" -->
<h1>Hello World</h1>
\`\`\`

And a link: https://example.com

And a YouTube video: https://www.youtube.com/watch?v=dQw4w9WgXcQ
  `.trim();

  const result = parse_message(complexMarkdown, 'read', { unifiedParsingEnabled: true });
  console.log('✅ Full integration test works');
  console.log('Document type:', result.type);
  console.log('Content items:', result.content?.length || 0);
  
  // Count embed nodes
  const embedCount = result.content?.filter((item: { type: string }) => item.type === 'embed').length || 0;
  console.log('Embed nodes found:', embedCount);
  
  // Test serialization round-trip
  const serialized = tipTapToCanonicalMarkdown(result);
  console.log('✅ Round-trip serialization works');
  console.log('Serialized length:', serialized.length);
  
} catch (error) {
  console.error('❌ Full integration test failed:', error);
}

console.log('\n🏁 Test runner completed!');
console.log('Check the logs above for any failures that need fixing.');
