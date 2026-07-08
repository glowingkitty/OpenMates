/*
 * OpenMates VS Code installed-extension test driver.
 *
 * Purpose: let @vscode/test-electron run tests against the packaged VSIX instead
 * of loading the OpenMates extension as the development extension.
 * Architecture: this driver contributes no user commands and only hosts tests.
 * Security: no production code imports this driver.
 */

function activate() {}
function deactivate() {}

module.exports = { activate, deactivate };
