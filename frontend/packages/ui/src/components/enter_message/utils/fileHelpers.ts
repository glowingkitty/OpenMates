// src/components/MessageInput/utils/fileHelpers.ts

/**
 * Checks if a file is a video file.
 * @param file The file to check.
 * @returns True if the file is a video, false otherwise.
 */
export function isVideoFile(file: File): boolean {
    const videoExtensions = [
        '.mp4', '.webm', '.ogg', '.mov', '.m4v',
        '.mkv', '.avi', '.3gp', '.wmv', '.flv'
    ];

    if (file.type.startsWith('video/')) {
        return true;
    }

    const fileName = file.name.toLowerCase();
    return videoExtensions.some(ext => fileName.endsWith(ext));
}

/**
 * Checks if a filename suggests a code or text file.
 * @param filename The filename to check.
 * @returns True if the filename suggests a code or text file, false otherwise.
 */
export function isCodeOrTextFile(filename: string): boolean {
    const lower = filename.toLowerCase();
    if (['dockerfile', 'makefile', 'rakefile', 'gemfile'].includes(lower)) {
        return true;
    }

    const codeExtensions = [
        'py', 'js', 'mjs', 'cjs', 'ts', 'html', 'css', 'json', 'jsonl', 'svelte',
        'java', 'cpp', 'cc', 'cxx', 'c', 'h', 'hpp', 'hh', 'hxx', 'rs', 'go', 'rb',
        'php', 'swift', 'kt', 'kts', 'cs', 'scala', 'r', 'pl', 'pm', 'lua', 'dart',
        'txt', 'md', 'mdx', 'xml', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf', 'env',
        'log', 'sh', 'bash', 'zsh', 'fish', 'ps1', 'bat', 'cmd', 'sql', 'vue', 'jsx',
        'tsx', 'scss', 'less', 'sass', 'dockerfile'
    ];

    const extension = filename.split('.').pop()?.toLowerCase();
    return extension ? codeExtensions.includes(extension) : false;
}

export function isDelimitedTableFile(filename: string): boolean {
    const extension = filename.split('.').pop()?.toLowerCase();
    return extension === 'csv' || extension === 'tsv';
}

export function isEmailFile(filename: string): boolean {
    const extension = filename.split('.').pop()?.toLowerCase();
    return extension === 'eml';
}

/**
 * Gets the programming language from a filename.
 * @param filename The filename.
 * @returns The programming language (e.g., "python", "javascript") or "plaintext" if no language is detected.
 */
export function getLanguageFromFilename(filename: string): string {
    const lower = filename.toLowerCase();
    if (lower === 'dockerfile') {
        return 'dockerfile';
    }
    if (lower === 'makefile') {
        return 'makefile';
    }

    const ext = filename.split('.').pop()?.toLowerCase() || '';
    const languageMap: { [key: string]: string } = {
        'py': 'python',
        'js': 'javascript',
        'mjs': 'javascript',
        'cjs': 'javascript',
        'ts': 'typescript',
        'html': 'html',
        'css': 'css',
        'json': 'json',
        'jsonl': 'jsonl',
        'svelte': 'svelte',
        'java': 'java',
        'cpp': 'cpp',
        'cc': 'cpp',
        'cxx': 'cpp',
        'c': 'c',
        'h': 'c',
        'hpp': 'cpp',
        'hh': 'cpp',
        'hxx': 'cpp',
        'rs': 'rust',
        'go': 'go',
        'rb': 'ruby',
        'php': 'php',
        'swift': 'swift',
        'kt': 'kotlin',
        'kts': 'kotlin',
        'cs': 'csharp',
        'scala': 'scala',
        'r': 'r',
        'pl': 'perl',
        'pm': 'perl',
        'lua': 'lua',
        'dart': 'dart',
        'txt': 'plaintext',
        'md': 'markdown',
        'mdx': 'markdown',
        'xml': 'xml',
        'yaml': 'yaml',
        'yml': 'yaml',
        'toml': 'toml',
        'ini': 'ini',
        'cfg': 'ini',
        'conf': 'ini',
        'env': 'dotenv',
        'log': 'log',
        'sh': 'bash',
        'bash': 'bash',
        'zsh': 'zsh',
        'fish': 'fish',
        'ps1': 'powershell',
        'bat': 'batch',
        'cmd': 'batch',
        'sql': 'sql',
        'vue': 'vue',
        'jsx': 'javascript',
        'tsx': 'typescript',
        'scss': 'scss',
        'less': 'less',
        'sass': 'sass',
        'dockerfile': 'dockerfile'
    };
    return languageMap[ext] || 'plaintext';
}
