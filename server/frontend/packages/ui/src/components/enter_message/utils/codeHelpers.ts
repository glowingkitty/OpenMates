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
    const codeKeywords = ['function', 'class', 'import', 'const', 'let', 'var', '=>', '{', '}', ';']
    const keywordCount = codeKeywords.reduce((count, keyword) => count + (text.includes(keyword) ? 1 : 0), 0)

    const result = lowlight.highlightAuto(text)
    return result.data?.language !== undefined || keywordCount >= 3 || text.length > 500
}

/**
 * Detects the programming language of a given text string.
 * @param text The text to analyze.
 * @returns The detected language (e.g., "javascript", "python") or "plaintext" if no language is detected.
 */
export function detectLanguage(text: string): string {
    const result = lowlight.highlightAuto(text)
    return result.data?.language || 'plaintext'
}