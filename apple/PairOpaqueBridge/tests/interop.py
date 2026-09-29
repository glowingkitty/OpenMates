"""Cross-runtime OPAQUE test: published JS 1.1.0 and pinned native 4.0.0."""

import ctypes
import json
import os
import subprocess
from pathlib import Path

bridge = Path(__file__).resolve().parents[1]
driver = Path(__file__).with_name("js-driver.cjs")
subprocess.run([
    "cargo", "rustc", "--manifest-path", str(bridge / "Cargo.toml"),
    "--locked", "--lib", "--", "--crate-type", "cdylib",
], check=True, env=os.environ.copy(), capture_output=True)
library = ctypes.CDLL(str(bridge / "target/debug/libopenmates_pair_opaque.so"))
library.pair_opaque_call.argtypes = [ctypes.c_char_p]
library.pair_opaque_call.restype = ctypes.c_void_p
library.pair_opaque_free.argtypes = [ctypes.c_void_p]


def native(operation, **fields):
    pointer = library.pair_opaque_call(json.dumps({"operation": operation, **fields}).encode())
    try:
        result = json.loads(ctypes.string_at(pointer))
    finally:
        library.pair_opaque_free(pointer)
    if not result["ok"]:
        raise AssertionError(result["error"])
    return result["result"]


def js(operation, **fields):
    result = subprocess.run(
        ["node", str(driver)], input=json.dumps({"operation": operation, **fields}),
        text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout)


pin = "W7P3KQ"  # Fictional test PIN; fresh PAKE state is generated for every run.
context = '["openmates-pair",2,"ABCDEF","test-session","' + "a" * 64 + '","test-user",null]'
ids = {"client": "openmates-pair-v2/client/" + context, "server": "openmates-pair-v2/server/" + context}

# JS approver, native receiver.
registered = js("jsRegister", password=pin, userIdentifier=context, identifiers=ids)
client = native("startClientLogin", password=pin)
server = js("jsStartServer", **registered, startLoginRequest=client["startLoginRequest"], userIdentifier=context, identifiers=ids)
client_finish = native("finishClientLogin", password=pin, clientLoginState=client["clientLoginState"], loginResponse=server["loginResponse"], identifiers=ids)
server_finish = js("jsFinishServer", serverLoginState=server["serverLoginState"], finishLoginRequest=client_finish["finishLoginRequest"], identifiers=ids)
assert client_finish["sessionKey"] == server_finish["sessionKey"]

try:
    native("finishClientLogin", password=pin, clientLoginState=client["clientLoginState"],
           loginResponse=server["loginResponse"],
           identifiers={"client": "wrong-context", "server": "wrong-context"})
except AssertionError:
    pass
else:
    raise AssertionError("native receiver accepted mismatched context identifiers")

wrong_client = native("startClientLogin", password="W7P3KR")
wrong_server = js("jsStartServer", **registered,
                  startLoginRequest=wrong_client["startLoginRequest"],
                  userIdentifier=context, identifiers=ids)
try:
    native("finishClientLogin", password="W7P3KR",
           clientLoginState=wrong_client["clientLoginState"],
           loginResponse=wrong_server["loginResponse"], identifiers=ids)
except AssertionError:
    pass
else:
    raise AssertionError("native receiver accepted incorrect PIN")

# Native approver, JS receiver.
setup = native("createServerSetup")
registration = native("startClientRegistration", password=pin)
response = native("createServerRegistrationResponse", serverSetup=setup["serverSetup"], registrationRequest=registration["registrationRequest"], userIdentifier=context)
record = native("finishClientRegistration", password=pin, clientRegistrationState=registration["clientRegistrationState"], registrationResponse=response["registrationResponse"], identifiers=ids)
client = js("jsStartClient", password=pin)
server = native("startServerLogin", serverSetup=setup["serverSetup"], registrationRecord=record["registrationRecord"], startLoginRequest=client["startLoginRequest"], userIdentifier=context, identifiers=ids)
client_finish = js("jsFinishClient", password=pin, clientLoginState=client["clientLoginState"], loginResponse=server["loginResponse"], identifiers=ids)
server_finish = native("finishServerLogin", serverLoginState=server["serverLoginState"], finishLoginRequest=client_finish["finishLoginRequest"], identifiers=ids)
assert client_finish["sessionKey"] == server_finish["sessionKey"]

print("OPAQUE JS/native interop passed in both directions")
