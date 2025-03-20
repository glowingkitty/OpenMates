// src/components/MessageInput/utils/codeHelpers.ts
import { common, createLowlight } from 'lowlight'
// Import specific languages you want to support. This reduces bundle size.
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import java from 'highlight.js/lib/languages/java'
import python from 'highlight.js/lib/languages/python'
import go from 'highlight.js/lib/languages/go'
import c from 'highlight.js/lib/languages/c'
import cpp from 'highlight.js/lib/languages/cpp'
import csharp from 'highlight.js/lib/languages/csharp'
import php from 'highlight.js/lib/languages/php'
import ruby from 'highlight.js/lib/languages/ruby'
import swift from 'highlight.js/lib/languages/swift'
import kotlin from 'highlight.js/lib/languages/kotlin'
import rust from 'highlight.js/lib/languages/rust'
import sql from 'highlight.js/lib/languages/sql'
import bash from 'highlight.js/lib/languages/bash'
import json from 'highlight.js/lib/languages/json'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'
import markdown from 'highlight.js/lib/languages/markdown'
import dockerfile from 'highlight.js/lib/languages/dockerfile'
import css from 'highlight.js/lib/languages/css'
import scss from 'highlight.js/lib/languages/scss'
import less from 'highlight.js/lib/languages/less'

// Register the languages with lowlight
const lowlight = createLowlight(common)
lowlight.register('javascript', javascript)
lowlight.register('typescript', typescript)
lowlight.register('java', java)
lowlight.register('python', python)
lowlight.register('go', go)
lowlight.register('c', c)
lowlight.register('cpp', cpp)
lowlight.register('csharp', csharp)
lowlight.register('php', php)
lowlight.register('ruby', ruby)
lowlight.register('swift', swift)
lowlight.register('kotlin', kotlin)
lowlight.register('rust', rust)
lowlight.register('sql', sql)
lowlight.register('bash', bash)
lowlight.register('json', json)
lowlight.register('xml', xml)
lowlight.register('yaml', yaml)
lowlight.register('markdown', markdown)
lowlight.register('dockerfile', dockerfile)
lowlight.register('css', css)
lowlight.register('scss', scss)
lowlight.register('less', less)
lowlight.register('html', xml) // lowlight uses 'xml' for HTML

/**
 * Checks if a given text string is likely to be code.
 * @param text The text to check.
 * @returns True if the text is likely code, false otherwise.
 */
export function isLikelyCode(text: string): boolean {
    console.debug('Analyzing text for code detection...');
    
    // More specific code patterns that are less likely to appear in regular text
    const codePatterns = [
        // Function declarations
        /function\s+\w+\s*\(/,
        /const\s+\w+\s*=\s*\([^)]*\)\s*=>/,
        /class\s+\w+(\s+extends\s+\w+)?(\s+implements\s+\w+)?\s*{/,
        
        // Variable declarations with types
        /(const|let|var)\s+\w+:\s*\w+/,
        
        // Import/export statements
        /import\s+{\s*[\w\s,]+}\s+from/,
        /export\s+(default\s+)?(function|class|const|let|var)/,
        
        // Common programming constructs with proper syntax
        /if\s*\([^)]+\)\s*{/,
        /for\s*\([^)]+\)\s*{/,
        /while\s*\([^)]+\)\s*{/,
        
        // Method definitions
        /public\s+\w+\s*\([^)]*\)\s*{/,
        /private\s+\w+\s*\([^)]*\)\s*{/,
        /protected\s+\w+\s*\([^)]*\)\s*{/,
        
        // Annotations/Decorators with proper syntax
        /@\w+\s*\([^)]*\)/,
        
        // HTML/XML tags (for markup languages)
        /<\/?[a-z][\s\S]*>/i,
    ];

    // Count regex pattern matches
    const patternCount = codePatterns.reduce((count, pattern) => {
        return count + (pattern.test(text) ? 1 : 0);
    }, 0);

    // Check for consistent indentation
    const lines = text.split('\n');
    const hasConsistentIndentation = lines.length > 3 && lines.slice(1).some(line => {
        return /^(\s{2,}|\t+)/.test(line);
    });

    // Check for balanced brackets/braces
    const bracketCount = (text.match(/[{[(]/g) || []).length;
    const closingBracketCount = (text.match(/[}\])]/g) || []).length;
    const hasBalancedBrackets = bracketCount > 0 && bracketCount === closingBracketCount;

    // Check for common file extensions in the text
    const hasCodeFileExtension = /\.(js|ts|py|java|cpp|cs|rb|php|go|rs|swift|kt|html|css|sql)/.test(text.toLowerCase());

    // Consider it code if:
    // 1. Multiple specific code patterns are found (2 or more)
    // 2. Has consistent indentation AND some code patterns
    // 3. Has balanced brackets AND some code patterns
    // 4. Contains code file extensions AND some patterns
    const isCode = (patternCount >= 2) ||
                  (hasConsistentIndentation && patternCount >= 1) ||
                  (hasBalancedBrackets && patternCount >= 1) ||
                  (hasCodeFileExtension && patternCount >= 1);

    console.debug('Code detection metrics:', {
        patternCount,
        hasConsistentIndentation,
        hasBalancedBrackets,
        hasCodeFileExtension,
        isCode
    });

    return isCode;
}

/**
 * Detects the programming language of a given text string.
 * @param text The text to analyze.
 * @returns The detected language or "plaintext" if no language is detected.
 */
export function detectLanguage(text: string): string {
    // Handle a few special cases that lowlight might miss
    if (text.match(/^#\s|^\*\*\s|^\-\s|^>\s|^```/m) && !text.includes('def ') && !text.includes('import ')) {
        return 'markdown';
    }
    
    if (text.startsWith('<?php')) {
        return 'php';
    }

    // Use lowlight's auto-detection with a focused subset of common languages
    const result = lowlight.highlightAuto(text, {
        subset: [
            'typescript',
            'javascript',
            'python',
            'java',
            'html',
            'css',
            'markdown',
            'sql',
            'bash',
            'json',
            'yaml',
            'php'
        ]
    });

    return result.data?.language || 'plaintext';
}