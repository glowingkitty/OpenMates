"""Pure source-extracted checker/deadline regressions; no SDK imports or peers."""

# contract-test-file: tooling
import ast
import copy
import math
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).parent


def checker():
    tree = ast.parse((ROOT / "session_project_sources_server.py").read_text())
    node = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "exact_json_equal"
    )
    scope = {"math": math}
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), "peer-checker", "exec"), scope
    )
    return scope["exact_json_equal"]


class ExactJsonTests(unittest.TestCase):
    def test_nested_boolean_number_mutations(self):
        equal = checker()
        original = {
            "camelCase": [{"a/b.c": True, "__proto__": False}],
            "数": [None, 1.25],
        }
        for key, replacement in (("a/b.c", 1), ("__proto__", 0)):
            changed = copy.deepcopy(original)
            changed["camelCase"][0][key] = replacement
            self.assertFalse(equal(original, changed))
            self.assertFalse(equal(changed, original))
        self.assertTrue(equal(original, copy.deepcopy(original)))
        self.assertTrue(equal({"number": [1, 0.0]}, {"number": [1.0, 0]}))

    def test_non_json_and_nonfinite_are_refused_even_if_other_side_differs(self):
        equal = checker()
        for bad in (float("nan"), float("inf"), {1: "x"}, (1,), {"nested": [object()]}):
            for left, right in ((bad, None), (None, bad)):
                with self.assertRaises(ValueError):
                    equal(left, right)

    def test_both_real_assertion_sites_use_checker(self):
        peer = ast.parse((ROOT / "session_project_sources_server.py").read_text())
        runner = ast.parse((ROOT / "runners/session-project-sources.py").read_text())
        for tree in (peer, runner):
            checks = [
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.Assert)
                and isinstance(n.test, ast.Call)
                and isinstance(n.test.func, ast.Name)
                and n.test.func.id == "exact_json_equal"
            ]
            self.assertEqual(len(checks), 1)
        self.assertTrue(any(isinstance(n, ast.Await) for n in ast.walk(checks[0])))

    def test_node_actual_helpers_and_runner_with_mocked_resources(self):
        result = subprocess.run(
            [
                "node",
                "--input-type=module",
                "-e",
                NODE_TEST,
                str(ROOT / "runners/session-project-sources.mjs"),
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


NODE_TEST = r"""
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {EventEmitter} from 'node:events';
import vm from 'node:vm';
const source=readFileSync(process.argv[1],'utf8');
const helpers=source.slice(source.indexOf('async function bounded('),source.indexOf('// End pure deadline/cleanup helpers.'));
const runner=source.slice(source.indexOf('async function runVector('),source.indexOf('const args=process.argv.slice(2)'));
function scope(extra={}){const context={assert,AbortController,setTimeout,clearTimeout,Date,DEADLINE:20,VECTOR_DEADLINE:30,...extra};vm.createContext(context);vm.runInContext(helpers,context);return context;}
// Fetch returned headers, but the JSON body never finishes. Entire body must time out+abort.
let aborted=false;
const body=scope({fetch:async(_url,options)=>{options.signal.addEventListener('abort',()=>{aborted=true;});return {status:200,json:()=>new Promise(()=>{})};}});
await assert.rejects(body.controlJson('http://127.0.0.1:1',null,Date.now()+15),/fixture deadline/);
assert.equal(aborted,true);
// Graceful TERM is ignored; KILL must be issued and its exit observed/reaped.
const child=new EventEmitter();Object.assign(child,{pid:123,exitCode:null,signalCode:null});const signals=[];
child.kill=signal=>{signals.push(signal);if(signal==='SIGKILL')queueMicrotask(()=>{child.signalCode=signal;child.emit('exit');});};
await scope().stopPeer(child,8);assert.deepEqual(signals,['SIGTERM','SIGKILL']);assert.equal(child.signalCode,'SIGKILL');
// Neither signal reaps: cleanup is bounded and must fail, never invent success.
const stuck=new EventEmitter();Object.assign(stuck,{pid:124,exitCode:null,signalCode:null,kill:()=>{}});
await assert.rejects(scope().stopPeer(stuck,5),/fixture deadline/);
async function scenario(mode){let closed=0,stopped=0,attempts=0;const primary=new Error('setup private sentinel');
 const peer=new EventEmitter();Object.assign(peer,{pid:123,exitCode:null,signalCode:null,stdout:{}});peer.kill=()=>{stopped++;peer.exitCode=0;queueMicrotask(()=>peer.emit('exit'));};
 const lines={once:(event,callback)=>{if(event==='line')queueMicrotask(()=>callback('{"endpoint":"http://127.0.0.1:1"}'));},close:()=>{}};
 class Client{constructor(){if(mode==='constructor')throw primary;this.projects={createSource:async()=>{attempts++;return {};}};}importSession(){return mode==='setup'?new Promise(()=>{}):Promise.resolve();}setTeam(){return Promise.resolve();}exportSession(){return new Promise(()=>{});}close(){closed++;if(mode==='combined')throw new Error('cleanup sentinel');return Promise.resolve();}}
 const c=scope({spawn:()=>peer,createInterface:()=>lines,SessionClient:Client,ROOT:'.',process:{env:{},stderr:{write:()=>{}}},session:()=>({}),camelOuter:x=>x,refused:()=>{},structuredClone,
  fetch:async()=>({status:200,json:async()=>({failure:null,mutation_attempts:attempts,requests:attempts,cookie:'synthetic'})})});
 vm.runInContext(runner,c);
 const suite={team:{team_id:'synthetic'},project_id:'synthetic'},vector={id:'synthetic',mode:'normal',cases:mode==='export'?[{operation:'create',input:{},expected_mutation_attempts:1}]:[]};
 // Constructor failure is a primary error and must still reap the started child.
 if(mode==='combined'){Client.prototype.importSession=()=>{throw primary;};}
 let error;try{await c.runVector(suite,vector,'fixture');}catch(e){error=e;}
 assert.ok(error);assert.equal(stopped,1);assert.equal(closed,mode==='constructor'?0:1);
 if(mode==='combined'||mode==='constructor')assert.equal(error,primary);else assert.match(error.message,/fixture deadline/);
}
await scenario('setup');await scenario('export');await scenario('constructor');await scenario('combined');
"""


class SourceReadFixtureTests(unittest.TestCase):
    """Pure fixed-fixture checks; no peer, SDK import, account or network."""

    def document(self):
        import json

        return json.loads((ROOT / "fixtures/session-project-sources.json").read_bytes())

    def test_original_authoring_prefix_is_exact(self):
        import hashlib
        import json

        vectors = self.document()["capabilities"][
            "session.project-source-authoring.v1"
        ]["vectors"]
        self.assertEqual(len(vectors), 36)
        encoded = json.dumps(
            vectors[:25], sort_keys=True, separators=(",", ":")
        ).encode()
        self.assertEqual(
            hashlib.sha256(encoded).hexdigest(),
            "9e598011dbe0012001bb91d839012b777d70c6580b6bd7c9b92531a48b6af2da",
        )
        self.assertEqual(len({v["id"] for v in vectors}), 36)

    def test_schema_validates_and_rejects_missing_read_oracle_or_unknown_dispatch(self):
        import json
        from jsonschema import Draft202012Validator

        schema = json.loads(
            (ROOT / "schemas/session-project-sources.schema.json").read_bytes()
        )
        validator = Draft202012Validator(schema)
        original = self.document()
        self.assertEqual(list(validator.iter_errors(original)), [])
        for field in ("expected", "expected_read_attempts", "response"):
            changed = copy.deepcopy(original)
            del changed["capabilities"]["session.project-source-authoring.v1"][
                "vectors"
            ][25]["cases"][0][field]
            self.assertTrue(list(validator.iter_errors(changed)))
        changed = copy.deepcopy(original)
        changed["capabilities"]["session.project-source-authoring.v1"]["vectors"][25][
            "cases"
        ][0]["operation"] = "delete"
        self.assertTrue(list(validator.iter_errors(changed)))

    def test_raw_oracles_preserve_every_opaque_field_in_order(self):
        equal = checker()
        vectors = self.document()["capabilities"][
            "session.project-source-authoring.v1"
        ]["vectors"]
        for vector in vectors[25:]:
            for case in vector["cases"]:
                if case["operation"] == "list-raw" and case["expected_error"] is None:
                    self.assertTrue(
                        equal(case["expected"], case["response"].get("sources") or [])
                    )
        row = vectors[25]["cases"][0]["expected"][0]
        self.assertEqual(
            row["encrypted_metadata"], "intentionally-not-a-metadata-cipher"
        )
        changed = copy.deepcopy(row)
        changed["unknownCamelCase"]["a/b.c"][0] = 1
        self.assertFalse(equal(row, changed))

    def test_name_oracles_only_add_names_and_cipher_uses_actual_project_key(self):
        import base64
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        suite = self.document()["capabilities"]["session.project-source-authoring.v1"]
        case = suite["vectors"][27]["cases"][0]
        before = case["response"]["sources"]
        after = case["expected"]["sources"]
        self.assertEqual(case["expected"]["project_id"], suite["project_id"])
        self.assertEqual(len(before), len(after))
        for raw, named in zip(before, after):
            self.assertEqual(
                {k: v for k, v in named.items() if k != "display_name"}, raw
            )
        payload = base64.b64decode(before[0]["encrypted_display_name"], validate=True)
        self.assertEqual(payload[:2], b"OM")
        plain = (
            AESGCM(base64.b64decode(suite["project_key_b64"]))
            .decrypt(payload[6:18], payload[18:], None)
            .decode()
        )
        self.assertEqual(plain, after[0]["display_name"])
        self.assertEqual(
            [row["display_name"] for row in after[1:]], [""] * (len(after) - 1)
        )
        self.assertEqual(after[0]["status"], "")
        self.assertIsNone(after[1]["status"])

    def test_reads_cannot_silently_acquire_mutation_or_extra_key_requests(self):
        vectors = self.document()["capabilities"][
            "session.project-source-authoring.v1"
        ]["vectors"]
        for vector in vectors[25:]:
            for case in vector["cases"]:
                self.assertEqual(case["expected_mutation_attempts"], 0)
                if case["operation"] == "list-raw":
                    self.assertEqual(case["expected_project_attempts"], 0)
                    self.assertEqual(case["expected_team_attempts"], 0)
        for mode in (
            "read-cancel",
            "read-api-key",
            "read-unrelated-master",
            "read-expired",
        ):
            self.assertTrue(any(v["mode"] == mode for v in vectors[25:]))

    def test_core_raw_facet_has_no_master_resolve_or_metadata_crypto(self):
        source = (
            ROOT.parents[1] / "packages/openmates-rust/src/work/projects/source_read.rs"
        ).read_text()
        raw = source.split("pub async fn list_sources_raw", 1)[1].split(
            "pub async fn list_sources_decoded_names", 1
        )[0]
        self.assertNotIn(".resolve(", raw)
        self.assertNotIn(".master(", raw)
        self.assertNotIn("decrypt_combined(", raw)
        names = source.split("fn decode_names", 1)[1].split("impl Projects", 1)[0]
        self.assertIn('object.get("encrypted_display_name")', names)
        self.assertNotIn('get("encrypted_metadata")', names)
        self.assertIn("let response = self.backend.request", raw)
        self.assertLess(raw.index(".await"), raw.index("// Observe cancellation"))


if __name__ == "__main__":
    unittest.main()
