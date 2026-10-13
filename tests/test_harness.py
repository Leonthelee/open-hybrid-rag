"""
tests/test_harness.py
Suite de pruebas unitarias para el Arnés de Agentes (Policy Gate, Observe & Trim, Verifier).
Ejecutar con: python -m unittest discover tests
"""
import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from harness.policy_gate import PolicyGate, PolicyAction
from harness.observe_trim import ObserveTrim
from harness.verifier import Verifier, VerificationVerdict

class TestPolicyGate(unittest.TestCase):
    def setUp(self):
        self.gate = PolicyGate()

    def test_safe_read_command_auto_approved(self):
        verdict = self.gate.evaluate("read_file", {"path": "src/main.py"})
        self.assertEqual(verdict.action, PolicyAction.ALLOW)
        self.assertEqual(verdict.risk_level, "LOW")

    def test_mutation_requires_human_approval(self):
        verdict = self.gate.evaluate("write_file", {"path": "src/main.py", "content": "..."})
        self.assertEqual(verdict.action, PolicyAction.REQUIRE_APPROVAL)
        self.assertEqual(verdict.risk_level, "MEDIUM")

    def test_destructive_rm_rf_strictly_denied(self):
        verdict = self.gate.evaluate("terminal", {"command": "rm -rf /"})
        self.assertEqual(verdict.action, PolicyAction.DENY)
        self.assertEqual(verdict.risk_level, "CRITICAL")
        self.assertIn("destructivo", verdict.reason.lower())

    def test_sql_drop_table_denied(self):
        verdict = self.gate.evaluate("execute_sql", {"command": "DROP TABLE users;"})
        self.assertEqual(verdict.action, PolicyAction.DENY)
        self.assertEqual(verdict.risk_level, "CRITICAL")


class TestObserveTrim(unittest.TestCase):
    def setUp(self):
        self.trimmer = ObserveTrim(max_output_lines=20)

    def test_trim_successful_output(self):
        raw_output = "\n".join([f"test_{i} ... ok" for i in range(100)] + ["100 passed in 2.1s"])
        res = self.trimmer.trim(raw_output, exit_code=0)
        self.assertFalse(res.has_failure)
        self.assertLess(res.trimmed_lines, 10)
        self.assertGreater(res.compression_ratio, 90.0)

    def test_trim_massive_failure_extracts_stack_trace(self):
        raw_lines = [
            "Collecting dependencies...",
            "Downloading https://packages.example.com/whl/dep.whl",
            "Running setup.py...",
            "=================== FAILURES ===================",
            "___ test_checkout_payment ___",
            "Traceback (most recent call last):",
            "  File \"checkout/test.py\", line 42, in test_checkout_payment",
            "    assert response.status_code == 200",
            "AssertionError: 500 != 200",
            "================ short test summary info ================",
            "FAILED checkout/test.py::test_checkout_payment - AssertionError: 500 != 200"
        ]
        # Multiplicar ruido irrelevante para simular miles de líneas
        noisy_output = "\n".join(["Installing package " + str(i) for i in range(500)] + raw_lines)
        res = self.trimmer.trim(noisy_output, exit_code=1)

        self.assertTrue(res.has_failure)
        self.assertIn("AssertionError", res.trimmed_output)
        self.assertIn("checkout/test.py", res.trimmed_output)
        self.assertGreater(res.compression_ratio, 95.0)


class TestVerifier(unittest.TestCase):
    def setUp(self):
        self.verifier = Verifier(max_turns=10)

    def test_ship_it_when_all_green(self):
        res = self.verifier.verify(
            current_turn=2,
            test_exit_code=0,
            test_summary="50 passed in 0.8s",
            lint_error_count=0,
            files_modified_count=1,
            model_claimed_done=True
        )
        self.assertEqual(res.verdict, VerificationVerdict.SHIP_IT)
        self.assertTrue(res.tests_passed)
        self.assertTrue(res.lint_clean)

    def test_reject_when_tests_still_fail(self):
        res = self.verifier.verify(
            current_turn=2,
            test_exit_code=1,
            test_summary="1 failed in test_checkout.py",
            lint_error_count=0,
            files_modified_count=1,
            model_claimed_done=True
        )
        self.assertEqual(res.verdict, VerificationVerdict.LOOP_AGAIN)
        self.assertIn("RECHAZADO 'ALL DONE'", res.feedback_for_model)

    def test_reject_when_model_claims_fixed_without_code_changes(self):
        res = self.verifier.verify(
            current_turn=2,
            test_exit_code=0,
            test_summary="ok",
            lint_error_count=0,
            files_modified_count=0, # Cero cambios
            model_claimed_done=True
        )
        self.assertEqual(res.verdict, VerificationVerdict.LOOP_AGAIN)
        self.assertIn("no se detectaron cambios reales", res.feedback_for_model)

    def test_abort_when_turn_budget_exceeded(self):
        res = self.verifier.verify(
            current_turn=11, # Máximo era 10
            test_exit_code=1,
            test_summary="fail",
            lint_error_count=0,
            files_modified_count=1,
            model_claimed_done=False
        )
        self.assertEqual(res.verdict, VerificationVerdict.BUDGET_EXCEEDED)


if __name__ == "__main__":
    unittest.main()
