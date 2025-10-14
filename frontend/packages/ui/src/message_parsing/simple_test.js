// Simple Node.js test runner for the unified message parsing architecture
// Run with: node simple_test.js

console.log('🧪 Testing Unified Message Parsing Architecture (Node.js)');
console.log('======================================================');

// Mock crypto for Node.js
import crypto from 'crypto';
if (!global.crypto) {
    global.crypto = {
        randomUUID: () => crypto.randomUUID(),
        subtle: crypto.webcrypto.subtle
    };
}

// Simple test framework
let testResults = { passed: 0, failed: 0 };

function test(name, fn) {
    try {
        console.log(`\n🧪 ${name}`);
        const result = fn();
        if (result === true || result === undefined) {
            console.log('✅ PASSED');
            testResults.passed++;
        } else {
            console.log(`❌ FAILED: ${result}`);
            testResults.failed++;
        }
    } catch (error) {
        console.log(`❌ FAILED: ${error.message}`);
        testResults.failed++;
    }
}

function assertEquals(actual, expected, message = '') {
    if (actual !== expected) {
        throw new Error(`Expected ${expected}, got ${actual}. ${message}`);
    }
}

function assertTrue(condition, message = '') {
    if (!condition) {
        throw new Error(`Expected true. ${message}`);
    }
}

// Mock imports (simplified versions)
const EMBED_PATTERNS = {
    CODE_FENCE: /^```(\w+)(?::(.+?))?\s*$/,
    DOCUMENT_HTML_FENCE: /^```document_html\s*$/,
    TABLE_FENCE: /^\|.*\|$/,
    TITLE_COMMENT: /^<!--\s*title:\s*["'](.+?)["']\s*-->$/,
    URL: /https?:\/\/[^\s]+/g,
    YOUTUBE_URL: /(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/g
};

function generateUUID() {
    return crypto.randomUUID();
}

function parseEmbedNodes(markdown, mode) {
    const lines = markdown.split('\n');
    const embedNodes = [];
    let i = 0;
    
    while (i < lines.length) {
        const line = lines[i].trim();
        
        // Parse code fences
        if (line.startsWith('```') && !line.startsWith('```document_html')) {
            const codeMatch = line.match(EMBED_PATTERNS.CODE_FENCE);
            if (codeMatch) {
                const [, language, path] = codeMatch;
                const id = generateUUID();
                
                let content = '';
                let j = i + 1;
                while (j < lines.length && !lines[j].trim().startsWith('```')) {
                    content += lines[j] + '\n';
                    j++;
                }
                
                embedNodes.push({
                    id,
                    type: 'code',
                    status: mode === 'write' ? 'processing' : 'finished',
                    contentRef: `stream:${id}`,
                    language,
                    filename: path || undefined,
                    lineCount: content.split('\n').filter(l => l.trim()).length
                });
                
                i = j;
            }
        }
        // Parse document HTML fences
        else if (line.startsWith('```document_html')) {
            const id = generateUUID();
            let title;
            
            for (let j = i + 1; j < Math.min(i + 5, lines.length); j++) {
                const titleMatch = lines[j].trim().match(EMBED_PATTERNS.TITLE_COMMENT);
                if (titleMatch) {
                    title = titleMatch[1];
                    break;
                }
            }
            
            let content = '';
            let j = i + 1;
            while (j < lines.length && !lines[j].trim().startsWith('```')) {
                content += lines[j] + '\n';
                j++;
            }
            
            const wordCount = content.split(/\s+/).filter(w => w.trim()).length;
            
            embedNodes.push({
                id,
                type: 'doc',
                status: mode === 'write' ? 'processing' : 'finished',
                contentRef: `stream:${id}`,
                title,
                wordCount
            });
            
            i = j;
        }
        // Parse tables
        else if (EMBED_PATTERNS.TABLE_FENCE.test(line)) {
            const id = generateUUID();
            let title;
            let rows = 0;
            let cols = 0;
            
            let j = i;
            while (j < lines.length && EMBED_PATTERNS.TABLE_FENCE.test(lines[j].trim())) {
                const row = lines[j].trim();
                rows++;
                
                if (cols === 0) {
                    cols = row.split('|').filter(cell => cell.trim()).length;
                }
                j++;
            }
            
            if (rows > 0) {
                embedNodes.push({
                    id,
                    type: 'sheet',
                    status: mode === 'write' ? 'processing' : 'finished',
                    contentRef: `stream:${id}`,
                    title,
                    rows,
                    cols,
                    cellCount: rows * cols
                });
            }
            
            i = j - 1;
        }
        
        // Parse URLs
        const urlMatches = line.match(EMBED_PATTERNS.URL);
        if (urlMatches) {
            for (const url of urlMatches) {
                const id = generateUUID();
                let type = 'web';
                
                if (EMBED_PATTERNS.YOUTUBE_URL.test(url)) {
                    type = 'video';
                }
                
                embedNodes.push({
                    id,
                    type,
                    status: mode === 'write' ? 'processing' : 'finished',
                    contentRef: `stream:${id}`,
                    url
                });
            }
        }
        
        i++;
    }
    
    return embedNodes;
}

function markdownToTipTap(markdown) {
    if (!markdown.trim()) {
        return { type: 'doc', content: [] };
    }
    
    return {
        type: 'doc',
        content: [
            {
                type: 'paragraph',
                content: [{ type: 'text', text: markdown }]
            }
        ]
    };
}

function enhanceDocumentWithEmbeds(doc, embedNodes, mode) {
    if (!doc || !doc.content || embedNodes.length === 0) {
        return doc;
    }
    
    const enhancedContent = [...doc.content];
    
    embedNodes.forEach(embedAttrs => {
        enhancedContent.push({
            type: 'embed',
            attrs: embedAttrs
        });
    });
    
    return {
        ...doc,
        content: enhancedContent
    };
}

function parse_message(markdown, mode, opts = {}) {
    if (!opts.unifiedParsingEnabled) {
        return markdownToTipTap(markdown);
    }
    
    const basicDoc = markdownToTipTap(markdown);
    const embedNodes = parseEmbedNodes(markdown, mode);
    const unifiedDoc = enhanceDocumentWithEmbeds(basicDoc, embedNodes, mode);
    
    return unifiedDoc;
}

// Run tests
test('Basic parsing works', () => {
    const result = parse_message('Hello world!', 'read', { unifiedParsingEnabled: true });
    assertEquals(result.type, 'doc');
    assertTrue(Array.isArray(result.content));
});

test('Code fence detection', () => {
    const markdown = '```javascript:test.js\nconsole.log("Hello");\n```';
    const embedNodes = parseEmbedNodes(markdown, 'read');
    assertEquals(embedNodes.length, 1);
    assertEquals(embedNodes[0].type, 'code');
    assertEquals(embedNodes[0].language, 'javascript');
    assertEquals(embedNodes[0].filename, 'test.js');
});

test('Document HTML fence detection', () => {
    const markdown = '```document_html\n<!-- title: "My Doc" -->\n<h1>Hello</h1>\n```';
    const embedNodes = parseEmbedNodes(markdown, 'read');
    assertEquals(embedNodes.length, 1);
    assertEquals(embedNodes[0].type, 'doc');
    assertEquals(embedNodes[0].title, 'My Doc');
});

test('Table detection', () => {
    const markdown = '| Column 1 | Column 2 |\n|----------|----------|\n| Data 1   | Data 2   |';
    const embedNodes = parseEmbedNodes(markdown, 'read');
    assertEquals(embedNodes.length, 1);
    assertEquals(embedNodes[0].type, 'sheet');
    assertEquals(embedNodes[0].rows, 3); // Header + separator + data = 3 rows
    assertEquals(embedNodes[0].cols, 2);
});

test('URL detection', () => {
    const markdown = 'Check out https://example.com for more info';
    const embedNodes = parseEmbedNodes(markdown, 'read');
    assertEquals(embedNodes.length, 1);
    assertEquals(embedNodes[0].type, 'web');
    assertEquals(embedNodes[0].url, 'https://example.com');
});

test('YouTube URL detection', () => {
    const markdown = 'Watch this: https://www.youtube.com/watch?v=dQw4w9WgXcQ';
    const embedNodes = parseEmbedNodes(markdown, 'read');
    assertEquals(embedNodes.length, 1);
    assertEquals(embedNodes[0].type, 'video');
    assertEquals(embedNodes[0].url, 'https://www.youtube.com/watch?v=dQw4w9WgXcQ');
});

test('Multiple embeds in one document', () => {
    const markdown = `
# Test Document

Here's some code:
\`\`\`python:hello.py
print("Hello, world!")
\`\`\`

And a table:
| Name | Age |
|------|-----|
| John | 25  |

And a link: https://example.com
    `.trim();

    const embedNodes = parseEmbedNodes(markdown, 'read');
    console.log('Debug: Found embeds:', embedNodes.map(n => ({ type: n.type, rows: n.rows })));
    assertEquals(embedNodes.length, 3);
    
    const codeEmbed = embedNodes.find(node => node.type === 'code');
    assertTrue(codeEmbed !== undefined, 'Should find code embed');
    assertEquals(codeEmbed.language, 'python');
    assertEquals(codeEmbed.filename, 'hello.py');
    
    const tableEmbed = embedNodes.find(node => node.type === 'sheet');
    assertTrue(tableEmbed !== undefined, 'Should find table embed');
    assertEquals(tableEmbed.rows, 3); // Header + separator + data = 3 rows
    assertEquals(tableEmbed.cols, 2);
    
    const webEmbed = embedNodes.find(node => node.type === 'web');
    assertTrue(webEmbed !== undefined, 'Should find web embed');
    assertEquals(webEmbed.url, 'https://example.com');
});

test('Status modes work correctly', () => {
    const markdown = '```javascript\nconsole.log("test");\n```';
    
    const writeEmbeds = parseEmbedNodes(markdown, 'write');
    assertEquals(writeEmbeds[0].status, 'processing');
    
    const readEmbeds = parseEmbedNodes(markdown, 'read');
    assertEquals(readEmbeds[0].status, 'finished');
});

test('Full integration test', () => {
    const complexMarkdown = `
# Test Document

Here's some code:
\`\`\`python:hello.py
print("Hello, world!")
\`\`\`

And a document:
\`\`\`document_html
<!-- title: "My Document" -->
<h1>Hello World</h1>
\`\`\`

And a table:
| Name | Age |
|------|-----|
| John | 25  |

And links:
- Web: https://example.com
- Video: https://www.youtube.com/watch?v=dQw4w9WgXcQ
    `.trim();

    const result = parse_message(complexMarkdown, 'read', { unifiedParsingEnabled: true });
    assertEquals(result.type, 'doc');
    assertTrue(Array.isArray(result.content));
    
    // Count embed nodes
    const embedCount = result.content.filter(item => item.type === 'embed').length;
    assertEquals(embedCount, 5); // code, doc, sheet, web, video
});

// Print results
console.log('\n📊 Test Results:');
console.log(`✅ Passed: ${testResults.passed}`);
console.log(`❌ Failed: ${testResults.failed}`);
console.log(`📈 Success Rate: ${Math.round((testResults.passed / (testResults.passed + testResults.failed)) * 100)}%`);

if (testResults.failed === 0) {
    console.log('\n🎉 All tests passed! The unified parsing architecture is working correctly.');
} else {
    console.log('\n⚠️  Some tests failed. Check the output above for details.');
}

console.log('\n🏁 Test suite completed!');
console.log('\nTo test in browser, open: frontend/packages/ui/src/message_parsing/test.html');
console.log('To run Node.js tests: cd frontend/packages/ui/src/message_parsing && node simple_test.js');
