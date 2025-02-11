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
    console.log('Analyzing text for code detection...');
    
    // Expanded list of code keywords and patterns
    const codePatterns = [
        // Function patterns
        'function', '=>', 'def ', 'class ', 'interface ', 'module.exports',
        // Variable declarations
        'const ', 'let ', 'var ', 'final ', 'private ', 'public ', 'protected ',
        // Common programming constructs
        'import ', 'export ', 'return ', 'if (', 'for (', 'while (', 'switch (',
        // Brackets and syntax
        '{', '}', ';', '()', '[]',
        // Common code patterns
        'async ', 'await ', 'try {', 'catch (', 'throw new',
        // Object-oriented patterns
        'extends ', 'implements ', 'constructor(',
        // Common method patterns
        '.map(', '.filter(', '.reduce(', '.forEach(',
        // Annotations/Decorators
        '@', '//'
    ];

    // Count pattern matches
    const patternCount = codePatterns.reduce((count, pattern) => {
        const hasPattern = text.includes(pattern);
        if (hasPattern) {
            console.log('Found code pattern:', pattern);
        }
        return count + (hasPattern ? 1 : 0);
    }, 0);

    console.log('Code pattern count:', patternCount);

    // Check for indentation patterns (common in code)
    const lines = text.split('\n');
    const hasIndentation = lines.some(line => line.startsWith('    ') || line.startsWith('\t'));
    if (hasIndentation) {
        console.log('Found code indentation patterns');
    }

    // Check for language-specific file patterns
    const filePatterns = [
        'package.json', 'tsconfig.json', 'webpack.config',
        '.gitignore', 'Dockerfile', 'Makefile'
    ];
    const hasFilePattern = filePatterns.some(pattern => text.includes(pattern));
    if (hasFilePattern) {
        console.log('Found code file patterns');
    }

    // Auto-detect language
    const result = lowlight.highlightAuto(text);
    console.log('Lowlight detected language:', result.data?.language);

    // Consider it code if:
    // 1. Has multiple code patterns (3 or more)
    // 2. Has indentation patterns
    // 3. Has file patterns
    // 4. Language is detected by lowlight
    // 5. Text is long and structured (>500 chars with patterns)
    const isCode = patternCount >= 3 || 
                  hasIndentation || 
                  hasFilePattern || 
                  result.data?.language !== undefined ||
                  (text.length > 500 && patternCount >= 2);

    console.log('Final code detection result:', isCode);
    return isCode;
}

/**
 * Detects the programming language of a given text string.
 * @param text The text to analyze.
 * @returns The detected language (e.g., "javascript", "python") or "plaintext" if no language is detected.
 */
export function detectLanguage(text: string): string {
    console.log('Detecting language for text...');
    
    // First check for TypeScript-specific features
    const tsFeatures = [
        'interface ',
        'type ',
        ': string',
        ': number',
        ': boolean',
        ': any',
        ': void',
        'export type',
        'namespace ',
    ];
    
    const hasTypeScriptFeatures = tsFeatures.some(feature => text.includes(feature));
    if (hasTypeScriptFeatures) {
        console.log('TypeScript features detected');
        return 'typescript';
    }
    
    const result = lowlight.highlightAuto(text, {
        // Specify subset of languages to check, prioritizing common ones
        subset: ['typescript', 'javascript', 'python', 'java', 'cpp', 'php']
    });
    
    console.log('Lowlight detected language:', result.data?.language);
    
    // Map some common language aliases
    const languageMap: { [key: string]: string } = {
        'js': 'javascript',
        'ts': 'typescript',
        'py': 'python',
        'jsx': 'javascript',
        'tsx': 'typescript'
    };

    const detectedLanguage = result.data?.language || 'plaintext';
    const mappedLanguage = languageMap[detectedLanguage] || detectedLanguage;
    
    console.log('Final mapped language:', mappedLanguage);
    return mappedLanguage;
}