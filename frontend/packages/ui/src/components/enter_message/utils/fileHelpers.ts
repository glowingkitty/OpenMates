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
    if (filename.toLowerCase() === 'dockerfile') {
        return true;
    }

    const codeExtensions = [
        'py', 'js', 'ts', 'html', 'css', 'json', 'svelte',
        'java', 'cpp', 'c', 'h', 'hpp', 'rs', 'go', 'rb', 'php', 'swift',
        'kt', 'txt', 'md', 'xml', 'yaml', 'yml', 'sh', 'bash',
        'sql', 'vue', 'jsx', 'tsx', 'scss', 'less', 'sass',
        'dockerfile'
    ];

    const extension = filename.split('.').pop()?.toLowerCase();
    return extension ? codeExtensions.includes(extension) : false;
}

/**
 * Gets the programming language from a filename.
 * @param filename The filename.
 * @returns The programming language (e.g., "python", "javascript") or "plaintext" if no language is detected.
 */
export function getLanguageFromFilename(filename: string): string {
    if (filename.toLowerCase() === 'dockerfile') {
        return 'dockerfile';
    }

    const ext = filename.split('.').pop()?.toLowerCase() || '';
    const languageMap: { [key: string]: string } = {
        'py': 'python',
        'js': 'javascript',
        'ts': 'typescript',
        'html': 'html',
        'css': 'css',
        'json': 'json',
        'svelte': 'svelte',
        'java': 'java',
        'cpp': 'cpp',
        'c': 'c',
        'h': 'c',
        'hpp': 'cpp',
        'rs': 'rust',
        'go': 'go',
        'rb': 'ruby',
        'php': 'php',
        'swift': 'swift',
        'kt': 'kotlin',
        'md': 'markdown',
        'xml': 'xml',
        'yaml': 'yaml',
        'yml': 'yaml',
        'sh': 'bash',
        'bash': 'bash',
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