"""Trusted controller around the reviewed existing SDK aggregate and real drivers.

Candidate main()/aggregate JSON is never executed or accepted as an oracle.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time
import types

try:
    from ci_sdk_conformance import (Refused, regular, require, sha, write,
                                    execution_plan, matrix_gaps, verify_programs, load_trust, compiler_diagnostics, snapshot,
                                    project_vector_diagnostic)
except ModuleNotFoundError:
    from scripts.ci_sdk_conformance import (Refused, regular, require, sha, write,
                                            execution_plan, matrix_gaps, verify_programs, load_trust, compiler_diagnostics, snapshot,
                                            project_vector_diagnostic)

LIMIT = 4 * 1024**2


def unique_failure_object(pairs):
    """Ambiguous duplicate fields cannot authorize a public diagnostic."""
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate failure field")
        value[key] = item
    return value


class Driver:
    def __init__(self, root, trust, plan, deadline):
        self.root, self.trust, self.plan, self.deadline = root, trust, plan, deadline
        self.launches = []
        self.failure = None
        self.inputs = {}

    def run(self, command, *, cwd, capture_output, text, timeout, env=None, check=False):
        require(cwd == self.root and capture_output and text, "driver_contract")
        verify_programs(self.root, self.trust)
        identity = None
        if "--capability" in command:
            require(len(self.launches) < len(self.plan), "driver_count")
            identity = self.plan[len(self.launches)]
            require(command == self.commands[len(self.launches)], "driver_order")
            self.launches.append({"capability": identity["capability"], "language": identity["language"],
                                  "status": "started", "commandSha256": sha(json.dumps(command).encode())})
        deadline = min(self.deadline, time.monotonic() + timeout)
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        outputs = {"stdout": bytearray(), "stderr": bytearray()}
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        try:
            while selector.get_map():
                require(time.monotonic() < deadline, "driver_deadline")
                for key, _ in selector.select(timeout=min(0.25, max(0, deadline - time.monotonic()))):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        outputs[key.data].extend(chunk)
                        require(len(outputs[key.data]) <= LIMIT, "driver_output_bound")
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
            result = subprocess.CompletedProcess(command, process.returncode,
                outputs["stdout"].decode("utf-8"), outputs["stderr"].decode("utf-8"))
            require(process.returncode == 0, "driver_failed")
            if identity:
                parsed = json.loads(result.stdout)
                actual = parsed.get("results", [])
                require(parsed.get("capability") == identity["capability"]
                        and parsed.get("language") == identity["language"]
                        and parsed.get("fixtureSha256") == identity["fixtureSha256"]
                        and parsed.get("status") == "passed" and isinstance(actual, list)
                        and len(actual) == len(identity["vectors"])
                        and all(isinstance(row, dict) and row.get("status") == "passed" for row in actual)
                        and {row.get("id") for row in actual} == set(identity["vectors"]), "driver_vector_result")
                self.launches[-1]["status"] = "passed"
            verify_programs(self.root, self.trust)
            return result
        except Exception as error:
            failed_ids = []
            diagnostic = None
            if identity:
                try:
                    parsed = json.loads(outputs["stdout"], object_pairs_hook=unique_failure_object)
                    if isinstance(parsed, dict) and parsed.get("capability") == identity["capability"]:
                        failed_ids = sorted({value["id"] for value in parsed.get("results", [])
                            if isinstance(value, dict) and value.get("id") in identity["vectors"]
                            and value.get("status") == "failed"})
                        if (parsed.get("language") == identity["language"]
                                and parsed.get("fixtureSha256") == identity["fixtureSha256"]
                                and parsed.get("status") == "failed"):
                            diagnostic = project_vector_diagnostic(parsed.get("diagnostic"), identity, failed_ids)
                except (ValueError, TypeError):
                    pass
            self.failure = {"code": str(error) if isinstance(error, Refused) else "driver_deadline" if isinstance(error, subprocess.TimeoutExpired) else "driver_unclassified",
                            "adapter": {key: identity[key] for key in ("capability", "language", "vectors")} if identity else "inventory",
                            "returncode": process.poll(), "failedVectorIds": failed_ids,
                            "stdoutBytes": len(outputs["stdout"]), "stderrBytes": len(outputs["stderr"]),
                            "stdoutSha256": sha(outputs["stdout"]), "stderrSha256": sha(outputs["stderr"]),
                            "compiler": compiler_diagnostics(outputs["stderr"], self.root, self.inputs)}
            if diagnostic is not None:
                self.failure["diagnostic"] = diagnostic
            raise
        finally:
            selector.close()
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
            if self.failure is not None:
                self.failure["terminatedReturncode"] = process.returncode
            process.stdout.close()
            process.stderr.close()
            # The outer owned stage group handles descendant cleanup on failure.


def execute(root, destination, deadline):
    trust = load_trust()
    verify_programs(root, trust)
    matrix = json.loads(regular(root / "config/sdk-capabilities.json"))
    plan = execution_plan(root, matrix)
    require(plan == trust["plan"] and matrix_gaps(matrix) == trust["gaps"], "reviewed_contract")
    driver = Driver(root, trust, plan, deadline)
    driver.inputs = snapshot(root)
    # Execute immutable verified bytes; candidate __main__/JSON cannot replace
    # this call sequence. __file__ retains existing generator/path semantics.
    namespace = {"__file__": str(root / "scripts/check_sdk_conformance.py"), "__name__": "reviewed_sdk_gate"}
    code = regular(root / "scripts/check_sdk_conformance.py")
    require(sha(code) == trust["programs"]["scripts/check_sdk_conformance.py"], "program_changed")
    exec(compile(code, namespace["__file__"], "exec"), namespace)
    driver.commands = [namespace["ADAPTER_OVERRIDES"].get(
        (row["language"], row["capability"]), namespace["RUNNERS"][row["language"]])
        + ["--fixture", str(root / row["fixture"]), "--capability", row["capability"]] for row in plan]
    namespace["subprocess"] = types.SimpleNamespace(run=driver.run)
    phase = "generated"
    try:
        namespace["check_generated"](root)
        phase = "inventory"
        inventory = namespace["discover_inventory"](root)
        phase = "matrix"
        independently_derived_gaps = namespace["validate_matrix"](matrix, inventory, root)
        require(independently_derived_gaps == trust["gaps"], "independent_gap_set")
        phase = "adapters"
        results = namespace["conformance"](matrix, root)
        require(len(driver.launches) == len(plan)
                and all(row["status"] == "passed" for row in driver.launches), "drivers_not_executed")
        verify_programs(root, trust)
        write(destination, {"matrixSha256": sha(regular(root / "config/sdk-capabilities.json")),
                            "openGaps": independently_derived_gaps, "releaseEligible": not independently_derived_gaps,
                            "conformance": results, "actualLaunches": driver.launches,
                            "trustedProgramsSha256": sha(json.dumps(trust["programs"], sort_keys=True).encode()),
                            "expectedPlan": plan})
    except Exception:
        write(destination.with_name("driver-failure.json"), driver.failure or {"code": "trusted_" + phase + "_failed"})
        raise


def main():
    try:
        require(len(sys.argv) == 4, "executor_arguments")
        execute(Path(sys.argv[1]), Path(sys.argv[2]), float(sys.argv[3]))
        return 0
    except Exception:
        # Public parent reads only the structured, closed private failure record.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
