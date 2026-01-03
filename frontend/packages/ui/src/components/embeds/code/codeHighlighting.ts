/**
 * frontend/packages/ui/src/components/embeds/code/codeHighlighting.ts
 * 
 * Shared syntax highlighting configuration for code embeds.
 * Centralizes all highlight.js language imports and provides a unified
 * highlighting function used by both CodeEmbedPreview and CodeEmbedFullscreen.
 * 
 * This file:
 * - Imports and registers all supported languages (70+ languages)
 * - Registers 3rd party languages like Svelte
 * - Exports a configured hljs instance
 * - Exports a safe highlighting function with XSS protection
 */

import hljs from 'highlight.js/lib/core';
import DOMPurify from 'dompurify';

// ============================================================================
// Language Imports for Syntax Highlighting
// ============================================================================
// We import a comprehensive set of languages to support various code embeds.
// Using highlight.js/lib/core with explicit language registration for smaller bundle.
// Languages are grouped by category for maintainability.

// --- Web Development ---
import javascript from 'highlight.js/lib/languages/javascript';
import typescript from 'highlight.js/lib/languages/typescript';
import xml from 'highlight.js/lib/languages/xml';           // Covers HTML, XML, SVG
import css from 'highlight.js/lib/languages/css';
import scss from 'highlight.js/lib/languages/scss';
import less from 'highlight.js/lib/languages/less';
import json from 'highlight.js/lib/languages/json';
import graphql from 'highlight.js/lib/languages/graphql';
import handlebars from 'highlight.js/lib/languages/handlebars';   // Also covers Mustache templates
import twig from 'highlight.js/lib/languages/twig';

// --- Systems Programming ---
import c from 'highlight.js/lib/languages/c';
import cpp from 'highlight.js/lib/languages/cpp';
import rust from 'highlight.js/lib/languages/rust';
import go from 'highlight.js/lib/languages/go';
import zig from 'highlight.js/lib/languages/zig';

// --- Scripting & General Purpose ---
import python from 'highlight.js/lib/languages/python';
import ruby from 'highlight.js/lib/languages/ruby';
import perl from 'highlight.js/lib/languages/perl';
import lua from 'highlight.js/lib/languages/lua';
import php from 'highlight.js/lib/languages/php';
import r from 'highlight.js/lib/languages/r';
import julia from 'highlight.js/lib/languages/julia';

// --- JVM Languages ---
import java from 'highlight.js/lib/languages/java';
import kotlin from 'highlight.js/lib/languages/kotlin';
import scala from 'highlight.js/lib/languages/scala';
import groovy from 'highlight.js/lib/languages/groovy';
import clojure from 'highlight.js/lib/languages/clojure';

// --- .NET Languages ---
import csharp from 'highlight.js/lib/languages/csharp';
import fsharp from 'highlight.js/lib/languages/fsharp';
import vbnet from 'highlight.js/lib/languages/vbnet';

// --- Apple/Mobile ---
import swift from 'highlight.js/lib/languages/swift';
import objectivec from 'highlight.js/lib/languages/objectivec';
import dart from 'highlight.js/lib/languages/dart';

// --- Functional Languages ---
import haskell from 'highlight.js/lib/languages/haskell';
import elixir from 'highlight.js/lib/languages/elixir';
import erlang from 'highlight.js/lib/languages/erlang';
import ocaml from 'highlight.js/lib/languages/ocaml';
import elm from 'highlight.js/lib/languages/elm';
import lisp from 'highlight.js/lib/languages/lisp';
import scheme from 'highlight.js/lib/languages/scheme';

// --- Shell & CLI ---
import bash from 'highlight.js/lib/languages/bash';
import shell from 'highlight.js/lib/languages/shell';
import powershell from 'highlight.js/lib/languages/powershell';
import dos from 'highlight.js/lib/languages/dos';           // Windows batch files

// --- Database & Query Languages ---
import sql from 'highlight.js/lib/languages/sql';
import pgsql from 'highlight.js/lib/languages/pgsql';         // PostgreSQL

// --- Configuration & Data Formats ---
import yaml from 'highlight.js/lib/languages/yaml';
import ini from 'highlight.js/lib/languages/ini';           // Also covers TOML
import properties from 'highlight.js/lib/languages/properties';
import nginx from 'highlight.js/lib/languages/nginx';
import apache from 'highlight.js/lib/languages/apache';
import dockerfile from 'highlight.js/lib/languages/dockerfile';
import protobuf from 'highlight.js/lib/languages/protobuf';

// --- Build Tools & Markup ---
import makefile from 'highlight.js/lib/languages/makefile';
import cmake from 'highlight.js/lib/languages/cmake';
import gradle from 'highlight.js/lib/languages/gradle';
import markdown from 'highlight.js/lib/languages/markdown';
import latex from 'highlight.js/lib/languages/latex';
import diff from 'highlight.js/lib/languages/diff';

// --- Assembly & Low-level ---
import x86asm from 'highlight.js/lib/languages/x86asm';
import wasm from 'highlight.js/lib/languages/wasm';
import llvm from 'highlight.js/lib/languages/llvm';

// --- Other Notable Languages ---
import vim from 'highlight.js/lib/languages/vim';
import nix from 'highlight.js/lib/languages/nix';
import http from 'highlight.js/lib/languages/http';
import awk from 'highlight.js/lib/languages/awk';
import fortran from 'highlight.js/lib/languages/fortran';
import cobol from 'highlight.js/lib/languages/cobol';
import basic from 'highlight.js/lib/languages/basic';
import verilog from 'highlight.js/lib/languages/verilog';
import vhdl from 'highlight.js/lib/languages/vhdl';
import glsl from 'highlight.js/lib/languages/glsl';          // OpenGL Shading Language

// --- 3rd Party Language: Svelte ---
// Svelte is not built-in to highlight.js, requires separate package
import hljsSvelte from 'highlightjs-svelte';

// ============================================================================
// Register All Languages
// ============================================================================

// Web Development
hljs.registerLanguage('javascript', javascript);
hljs.registerLanguage('typescript', typescript);
hljs.registerLanguage('xml', xml);
hljs.registerLanguage('css', css);
hljs.registerLanguage('scss', scss);
hljs.registerLanguage('less', less);
hljs.registerLanguage('json', json);
hljs.registerLanguage('graphql', graphql);
hljs.registerLanguage('handlebars', handlebars);
hljs.registerLanguage('twig', twig);

// Systems Programming
hljs.registerLanguage('c', c);
hljs.registerLanguage('cpp', cpp);
hljs.registerLanguage('rust', rust);
hljs.registerLanguage('go', go);
hljs.registerLanguage('zig', zig);

// Scripting & General Purpose
hljs.registerLanguage('python', python);
hljs.registerLanguage('ruby', ruby);
hljs.registerLanguage('perl', perl);
hljs.registerLanguage('lua', lua);
hljs.registerLanguage('php', php);
hljs.registerLanguage('r', r);
hljs.registerLanguage('julia', julia);

// JVM Languages
hljs.registerLanguage('java', java);
hljs.registerLanguage('kotlin', kotlin);
hljs.registerLanguage('scala', scala);
hljs.registerLanguage('groovy', groovy);
hljs.registerLanguage('clojure', clojure);

// .NET Languages
hljs.registerLanguage('csharp', csharp);
hljs.registerLanguage('fsharp', fsharp);
hljs.registerLanguage('vbnet', vbnet);

// Apple/Mobile
hljs.registerLanguage('swift', swift);
hljs.registerLanguage('objectivec', objectivec);
hljs.registerLanguage('dart', dart);

// Functional Languages
hljs.registerLanguage('haskell', haskell);
hljs.registerLanguage('elixir', elixir);
hljs.registerLanguage('erlang', erlang);
hljs.registerLanguage('ocaml', ocaml);
hljs.registerLanguage('elm', elm);
hljs.registerLanguage('lisp', lisp);
hljs.registerLanguage('scheme', scheme);

// Shell & CLI
hljs.registerLanguage('bash', bash);
hljs.registerLanguage('shell', shell);
hljs.registerLanguage('powershell', powershell);
hljs.registerLanguage('dos', dos);

// Database & Query Languages
hljs.registerLanguage('sql', sql);
hljs.registerLanguage('pgsql', pgsql);

// Configuration & Data Formats
hljs.registerLanguage('yaml', yaml);
hljs.registerLanguage('ini', ini);
hljs.registerLanguage('properties', properties);
hljs.registerLanguage('nginx', nginx);
hljs.registerLanguage('apache', apache);
hljs.registerLanguage('dockerfile', dockerfile);
hljs.registerLanguage('protobuf', protobuf);

// Build Tools & Markup
hljs.registerLanguage('makefile', makefile);
hljs.registerLanguage('cmake', cmake);
hljs.registerLanguage('gradle', gradle);
hljs.registerLanguage('markdown', markdown);
hljs.registerLanguage('latex', latex);
hljs.registerLanguage('diff', diff);

// Assembly & Low-level
hljs.registerLanguage('x86asm', x86asm);
hljs.registerLanguage('wasm', wasm);
hljs.registerLanguage('llvm', llvm);

// Other Notable Languages
hljs.registerLanguage('vim', vim);
hljs.registerLanguage('nix', nix);
hljs.registerLanguage('http', http);
hljs.registerLanguage('awk', awk);
hljs.registerLanguage('fortran', fortran);
hljs.registerLanguage('cobol', cobol);
hljs.registerLanguage('basic', basic);
hljs.registerLanguage('verilog', verilog);
hljs.registerLanguage('vhdl', vhdl);
hljs.registerLanguage('glsl', glsl);

// Register Svelte (3rd party)
hljsSvelte(hljs);

// ============================================================================
// Language Aliases
// ============================================================================
// Register common aliases for better language detection

// HTML is actually XML in highlight.js
hljs.registerAliases(['html', 'htm', 'xhtml', 'svg'], { languageName: 'xml' });

// JavaScript variants
hljs.registerAliases(['js', 'jsx', 'mjs', 'cjs', 'node'], { languageName: 'javascript' });
hljs.registerAliases(['ts', 'tsx', 'mts', 'cts'], { languageName: 'typescript' });

// C/C++ variants
hljs.registerAliases(['h', 'hpp', 'hxx', 'h++', 'cc', 'cxx', 'c++'], { languageName: 'cpp' });

// Shell variants
hljs.registerAliases(['sh', 'zsh', 'fish'], { languageName: 'bash' });
hljs.registerAliases(['bat', 'cmd'], { languageName: 'dos' });
hljs.registerAliases(['ps1', 'psm1', 'psd1'], { languageName: 'powershell' });

// Python variants
hljs.registerAliases(['py', 'pyw', 'gyp', 'ipynb'], { languageName: 'python' });

// Ruby variants
hljs.registerAliases(['rb', 'gemspec', 'podspec', 'thor', 'irb'], { languageName: 'ruby' });

// Config formats
hljs.registerAliases(['toml'], { languageName: 'ini' });
hljs.registerAliases(['yml'], { languageName: 'yaml' });
hljs.registerAliases(['docker', 'containerfile'], { languageName: 'dockerfile' });

// .NET
hljs.registerAliases(['cs', 'c#'], { languageName: 'csharp' });
hljs.registerAliases(['fs', 'f#'], { languageName: 'fsharp' });
hljs.registerAliases(['vb'], { languageName: 'vbnet' });

// Other common aliases
hljs.registerAliases(['golang'], { languageName: 'go' });
hljs.registerAliases(['rs'], { languageName: 'rust' });
hljs.registerAliases(['kt', 'kts'], { languageName: 'kotlin' });
hljs.registerAliases(['objc', 'obj-c', 'mm'], { languageName: 'objectivec' });
hljs.registerAliases(['tex'], { languageName: 'latex' });
hljs.registerAliases(['mk', 'mak', 'make'], { languageName: 'makefile' });
hljs.registerAliases(['hs'], { languageName: 'haskell' });
hljs.registerAliases(['ex', 'exs'], { languageName: 'elixir' });
hljs.registerAliases(['erl', 'hrl'], { languageName: 'erlang' });
hljs.registerAliases(['ml', 'mli'], { languageName: 'ocaml' });
hljs.registerAliases(['clj', 'cljs', 'cljc', 'edn'], { languageName: 'clojure' });
hljs.registerAliases(['postgres', 'postgresql'], { languageName: 'pgsql' });
hljs.registerAliases(['gql'], { languageName: 'graphql' });
hljs.registerAliases(['proto'], { languageName: 'protobuf' });
hljs.registerAliases(['asm', 'assembly'], { languageName: 'x86asm' });
hljs.registerAliases(['pl', 'pm'], { languageName: 'perl' });
hljs.registerAliases(['jl'], { languageName: 'julia' });
hljs.registerAliases(['f90', 'f95', 'f03', 'f08'], { languageName: 'fortran' });
hljs.registerAliases(['cbl', 'cob'], { languageName: 'cobol' });
hljs.registerAliases(['v', 'vh'], { languageName: 'verilog' });
hljs.registerAliases(['vhd'], { languageName: 'vhdl' });
hljs.registerAliases(['frag', 'vert'], { languageName: 'glsl' });

// ============================================================================
// Exported Configured Instance
// ============================================================================

export { hljs };

// ============================================================================
// Highlighting Functions
// ============================================================================

/**
 * Options for DOMPurify sanitization
 * Only allows span tags with class attributes (for syntax highlighting)
 */
const SANITIZE_OPTIONS = {
  ALLOWED_TAGS: ['span'],
  ALLOWED_ATTR: ['class']
};

/**
 * Apply syntax highlighting to code content
 * 
 * @param code - The source code to highlight
 * @param language - Optional language identifier (uses auto-detection if not provided)
 * @returns Sanitized HTML string with syntax highlighting spans
 * 
 * @example
 * const html = highlightCode('const x = 1;', 'javascript');
 * element.innerHTML = html;
 */
export function highlightCode(code: string, language?: string): string {
  if (!code) return '';
  
  try {
    let highlighted: string;
    
    // If language is provided and not plaintext, try to use it
    if (language && language !== 'text' && language !== 'plaintext') {
      try {
        highlighted = hljs.highlight(code, { language }).value;
      } catch {
        // Fallback to auto-detection if language not supported
        console.debug(`[codeHighlighting] Language '${language}' not supported, using auto-detection`);
        highlighted = hljs.highlightAuto(code).value;
      }
    } else {
      // Auto-detect language
      highlighted = hljs.highlightAuto(code).value;
    }
    
    // Sanitize the highlighted HTML to prevent XSS
    return DOMPurify.sanitize(highlighted, SANITIZE_OPTIONS);
  } catch (error) {
    console.warn('[codeHighlighting] Error highlighting code:', error);
    // Return escaped plain text on error
    return escapeHtml(code);
  }
}

/**
 * Apply syntax highlighting directly to a DOM element
 * This is useful when you need to update an element's innerHTML with highlighted code
 * 
 * @param element - The DOM element to update (typically a <code> element)
 * @param code - The source code to highlight
 * @param language - Optional language identifier
 */
export function highlightToElement(
  element: HTMLElement | null,
  code: string,
  language?: string
): void {
  if (!element) return;
  
  if (!code) {
    element.textContent = '';
    return;
  }
  
  const highlighted = highlightCode(code, language);
  if (highlighted) {
    element.innerHTML = highlighted;
  } else {
    // Fallback to plain text if highlighting fails
    element.textContent = code;
  }
}

/**
 * Escape HTML special characters for safe display
 * Used as fallback when highlighting fails
 */
function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * List of all supported language names
 * Useful for validation or UI display
 */
export const SUPPORTED_LANGUAGES = hljs.listLanguages();

/**
 * Check if a language is supported by the configured hljs instance
 * 
 * @param language - Language name or alias to check
 * @returns true if the language is supported
 */
export function isLanguageSupported(language: string): boolean {
  if (!language) return false;
  try {
    return hljs.getLanguage(language) !== undefined;
  } catch {
    return false;
  }
}

