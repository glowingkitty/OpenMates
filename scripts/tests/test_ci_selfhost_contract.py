# contract-test-file: tooling
"""Pure closed-scope, immutable-identity and sanitized evidence checks."""
import copy
import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).parents[1] / "ci_selfhost_contract.py"
spec = importlib.util.spec_from_file_location("staged_selfhost_contract", MODULE)
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


class SelfhostContractTests(unittest.TestCase):
    def steps(self):
        return [{"id": key, "name": value[0], "run": "unchanged-command"}
                for key, value in contract.STEPS.items()]

    def receipt(self, target):
        return {**contract.identity("a" * 40, "b" * 40, "c" * 64, "d" * 40),
                "run_id": "123", "browser_coverage_scope": "full-spec" if target == "selfhost-image" else "none",
                "target": target, "coverage_scope": "recipe-target", "coverage_complete": False,
                "exit_code": 0, "cleanup": {"containers_remaining": 0, "volumes_remaining": 0,
                    "private_account_files_removed": True, "errors": []}, "steps": [{"id": row["id"], "phase": "completed", "exit_code": 0,
                    "run_id": "123", "source_commit": "a" * 40}
                    for row in contract.recipe_steps(self.steps(), target)],
                "stats": {"expected": 4, "unexpected": 0, "flaky": 0, "skipped": 0}}

    def test_closed_dependency_map(self):
        for target in contract.TARGETS:
            steps = contract.recipe_steps(self.steps(), target)
            ids = [row["id"] for row in steps]
            self.assertEqual("selfhost-browser" in ids, target == "selfhost-image")
            self.assertEqual("selfhost-native-source" in ids, target == "selfhost-source")
            self.assertEqual("selfhost-legacy-source" in ids, target == "selfhost-legacy")
        for mutation in (self.steps()[:-1], self.steps() + [self.steps()[0]],
                         self.steps() + [{"id": "unclassified", "run": "unsafe"}],
                         list(reversed(self.steps())), [{"uses": "new/action@main"}] + self.steps()):
            with self.assertRaises(ValueError):
                contract.recipe_steps(mutation, "selfhost-image")
        for selection in ([], ["selfhost-source", "selfhost-image"], ["selfhost-smoke.spec.ts"], ["fake"]):
            with self.assertRaises(ValueError):
                contract.validate_targets(selection)

    def test_aggregate_requires_all_three_identical_scopes(self):
        receipts = [self.receipt(target) for target in contract.TARGETS]
        self.assertTrue(contract.aggregate_acceptance(receipts))
        for candidate in (receipts[:2], receipts + [receipts[0]], [receipts[0]] * 3):
            self.assertFalse(contract.aggregate_acceptance(candidate))
        for key in ("source_commit", "product_tree", "recipe_sha256", "harness_commit", "input_set_sha256"):
            changed = copy.deepcopy(receipts)
            changed[0][key] = "e" * len(changed[0][key])
            self.assertFalse(contract.aggregate_acceptance(changed))

    def test_failed_missing_step_or_skipped_browser_never_credits(self):
        receipts = [self.receipt(target) for target in contract.TARGETS]
        for mutate in (lambda row: row.update(exit_code=1),
                       lambda row: row.pop("cleanup"),
                       lambda row: row["steps"].pop(),
                       lambda row: row["steps"][0].update(phase="started"),
                       lambda row: row.update(coverage_complete=True)):
            candidate = copy.deepcopy(receipts)
            mutate(candidate[0])
            self.assertFalse(contract.aggregate_acceptance(candidate))
        for stats in ({"expected": 3, "unexpected": 0, "flaky": 0, "skipped": 1},
                      {"expected": 4, "unexpected": 0, "flaky": 1, "skipped": 0}):
            candidate = copy.deepcopy(receipts)
            candidate[1]["stats"] = stats
            self.assertFalse(contract.aggregate_acceptance(candidate))

    def test_journal_contains_only_allowlisted_stage_status_and_time(self):
        raw = {"step": "cms-setup", "status": "in_progress", "path": "/secret",
               "stderr": "private", "targetImageTag": "private", "updated_at": "private"}
        self.assertEqual(contract.sanitize_journal(raw, 42),
                         {"stage": "cms-setup", "status": "in_progress", "observed_elapsed_ms": 42})
        for raw in ({"step": "secret", "status": "failed"}, {"step": "up", "status": "secret"}, None):
            self.assertIsNone(contract.sanitize_journal(raw, 42))

    def test_recipe_has_exact_closed_inventory_and_budget(self):
        import yaml
        root = MODULE.parents[1]
        recipe = yaml.safe_load((root / contract.RECIPE).read_text())["jobs"]["install-smoke"]
        self.assertEqual(recipe["timeout-minutes"], 120)
        for target in contract.TARGETS:
            contract.recipe_steps(recipe["steps"], target)
        self.assertIn("selfhost-smoke.spec.ts", next(row["run"] for row in recipe["steps"]
                      if row.get("id") == "selfhost-browser"))
        adapter = MODULE.with_name("ci_selfhost.py").read_text()
        self.assertIn("SELFHOST_WORK_SECONDS = 105 * 60", adapter)
        self.assertIn("SELFHOST_CLEANUP_SECONDS = 117 * 60", adapter)


if __name__ == "__main__":
    unittest.main()
