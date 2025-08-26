// Quick test for the inline parsing functionality
// Run this with Node.js to test the parsing logic

import { parse_message } from './parse_message.js';

// Test cases
const testCases = [
  {
    name: "Unclosed code fence with text before",
    input: "this is a test.  ```python  print('hello' world",
    expected: "Should detect unclosed code fence"
  },
  {
    name: "URL in text",
    input: "Check out https://example.com for more info",
    expected: "Should detect URL"
  },
  {
    name: "Table row without separator",
    input: "| Name | Age |\n| John | 25 |",
    expected: "Should detect incomplete table"
  },
  {
    name: "Complete code fence",
    input: "```python\nprint('hello')\n```",
    expected: "Should NOT detect as unclosed"
  }
];

console.log('Testing inline parsing functionality...\n');

testCases.forEach((testCase, index) => {
  console.log(`\n--- Test ${index + 1}: ${testCase.name} ---`);
  console.log(`Input: "${testCase.input}"`);
  console.log(`Expected: ${testCase.expected}`);
  
  try {
    const result = parse_message(testCase.input, 'write', { unifiedParsingEnabled: true });
    
    console.log('Result:');
    console.log(`- Embed count: ${result.content ? result.content.filter(n => n.type === 'embed').length : 0}`);
    console.log(`- Unclosed blocks: ${result._streamingData ? result._streamingData.unclosedBlocks.length : 0}`);
    
    if (result._streamingData && result._streamingData.unclosedBlocks.length > 0) {
      console.log('- Unclosed block types:', result._streamingData.unclosedBlocks.map(b => b.type));
    }
  } catch (error) {
    console.error('Error:', error.message);
  }
});

console.log('\n--- Test Complete ---');
