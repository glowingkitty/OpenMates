// Pure Node check: execute the maintained TypeScript function bodies, without
// importing browser services or substituting a second hand-written reference.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const root = process.env.OPENMATES_SOURCE_ROOT || path.resolve(__dirname, '../../../../../../..');
const fixture = process.env.OPENMATES_MESSAGE_POLICY_FIXTURE || path.join(root, 'tests/sdk-conformance/fixtures/browser-message-merge-policy.json');
const rustFixture = process.env.OPENMATES_MESSAGE_POLICY_RUST_FIXTURE || path.join(root, 'packages/openmates-rust/tests/fixtures/browser-message-merge-policy.json');
assert.deepEqual(fs.readFileSync(fixture), fs.readFileSync(rustFixture), 'common and packaged Rust fixtures must stay byte-identical');
const filename = path.join(root, 'frontend/packages/ui/src/services/db/messageOperations.ts');
const source = fs.readFileSync(filename, 'utf8');
const ast = ts.createSourceFile(filename, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
const names = new Set(['shouldUpdateMessage', 'hasNewEncryptedFields', 'hasNewerStoredRevision']);
const selected = [];
for (const statement of ast.statements) {
  if (ts.isFunctionDeclaration(statement) && statement.name && names.has(statement.name.text)) {
    selected.push(statement.getText(ast).replace(/^export\s+/, ''));
    names.delete(statement.name.text);
  } else if (ts.isVariableStatement(statement) && statement.declarationList.declarations.some(d => ts.isIdentifier(d.name) && d.name.text === 'STATUS_PRIORITY')) {
    selected.push(statement.getText(ast));
  }
}
assert.equal(names.size, 0, 'all maintained predicates must be AST-extracted');
assert.equal(selected.length, 4, 'extract priority map and exactly three predicates');
const output = ts.transpileModule(selected.join('\n') + '\n globalThis.policy = {shouldUpdateMessage,hasNewEncryptedFields,hasNewerStoredRevision};', {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.None }, reportDiagnostics: true,
});
assert.equal((output.diagnostics || []).filter(d => d.category === ts.DiagnosticCategory.Error).length, 0);
const context = vm.createContext({});
vm.runInContext(output.outputText, context, {timeout: 1000});
const cases = JSON.parse(fs.readFileSync(fixture, 'utf8')).cases;
for (const c of cases) {
  assert.deepEqual({
    should_update_message: context.policy.shouldUpdateMessage(c.existing,c.incoming),
    has_new_encrypted_fields: context.policy.hasNewEncryptedFields(c.existing,c.incoming),
    has_newer_stored_revision: context.policy.hasNewerStoredRevision(c.existing,c.incoming),
  }, c.expected, c.name);
}
for (const field of ['encrypted_content','encrypted_sender_name','encrypted_category','encrypted_model_name','encrypted_thinking_content','encrypted_thinking_signature','encrypted_pii_mappings']) {
  assert.equal(context.policy.hasNewEncryptedFields({}, {[field]:'cipher'}), true, field);
  assert.equal(context.policy.hasNewEncryptedFields({[field]:'old'}, {[field]:'new'}), false, field);
}
console.log(`Actual maintained TypeScript policy: ${cases.length} shared cases plus seven encrypted-field isolation pairs passed.`);
const duplicateDeclaration=ast.statements.find(s=>ts.isFunctionDeclaration(s)&&s.name?.text==='isContentDuplicate');
assert.ok(duplicateDeclaration,'maintained duplicate policy must exist');
const duplicateOutput=ts.transpileModule(duplicateDeclaration.getText(ast).replace(/^export\s+/,'')+'\nglobalThis.duplicate=isContentDuplicate;', {compilerOptions:{target:ts.ScriptTarget.ES2020,module:ts.ModuleKind.None},reportDiagnostics:true});
assert.equal((duplicateOutput.diagnostics||[]).filter(d=>d.category===ts.DiagnosticCategory.Error).length,0);
vm.runInContext(duplicateOutput.outputText,context,{timeout:1000});
for(const [a,b] of [['physical_a','physical_b'],['opaque / a','opaque / b'],['\u{10000}','\ue000']]){
 const old={message_id:a,chat_id:'same-chat',role:'user',created_at:1,encrypted_content:'identical-cipher',encrypted_sender_name:'same-sender'};
 assert.equal(context.duplicate(old,{...old,message_id:b}),false,'different physical user IDs remain separate submissions');
 assert.equal(context.duplicate({...old,role:'assistant'},{...old,role:'assistant',message_id:b}),true,'assistant insertion cannot bypass cross-ID duplicate scan');
}
console.log('Actual maintained duplicate policy: three physical/opaque user-ID cases and assistant negative controls passed.');
