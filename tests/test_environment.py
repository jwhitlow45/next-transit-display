import os
import subprocess
import sys
import unittest


def _import_environment(**overrides):
    # environment.py validates at import, so each case runs in a fresh interpreter with the runner's environment
    result = subprocess.run(
        [sys.executable, "-B", "-c", "import modules.environment as e; print(e.LED_MATRIX_PWM_BITS, e.LED_MATRIX_LIMIT_REFRESH_RATE_HZ)"],
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path), **overrides},
        capture_output=True,
        text=True,
    )
    return result


class MatrixRefreshSettingsTest(unittest.TestCase):
    def test_unset_settings_keep_the_library_defaults(self):
        result = _import_environment()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["11", "0"])

    def test_accepts_settings_in_range(self):
        result = _import_environment(LED_MATRIX_PWM_BITS="9", LED_MATRIX_LIMIT_REFRESH_RATE_HZ="160")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["9", "160"])

    def test_rejects_pwm_bits_outside_1_to_11(self):
        for value in ("0", "12"):
            with self.subTest(value):
                result = _import_environment(LED_MATRIX_PWM_BITS=value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("LED_MATRIX_PWM_BITS must be between 1 and 11", result.stderr)

    def test_rejects_a_negative_refresh_cap(self):
        result = _import_environment(LED_MATRIX_LIMIT_REFRESH_RATE_HZ="-1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("LED_MATRIX_LIMIT_REFRESH_RATE_HZ must be 0 (no cap) or more", result.stderr)


if __name__ == "__main__":
    unittest.main()
