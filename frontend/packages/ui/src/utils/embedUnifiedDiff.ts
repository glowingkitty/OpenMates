/** Existing legacy LF-preserving patch shape for encrypted embed history. */
export function buildUnifiedDiff(currentContent: string, restoredContent: string, currentVersion: number, newVersion: number): string {
	const oldLines = currentContent ? currentContent.split('\n') : [];
	const newLines = restoredContent ? restoredContent.split('\n') : [];
	return [
		`--- v${currentVersion}`,
		`+++ v${newVersion}`,
		`@@ -${oldLines.length ? 1 : 0},${oldLines.length} +${newLines.length ? 1 : 0},${newLines.length} @@`,
		...oldLines.map((line) => `-${line}`),
		...newLines.map((line) => `+${line}`)
	].join('\n');
}
