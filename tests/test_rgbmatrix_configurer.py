import unittest
from unittest import mock

import modules.rgbmatrix_configurer as rgbmatrix_configurer


def _options_for(**overrides):
    settings = {
        "rows": 32,
        "cols": 64,
        "chain_length": 1,
        "parallel": 1,
        "gpio_slowdown": 2,
        "hardware_mapping": "adafruit-hat",
        "matrix_brightness": 100,
        **overrides,
    }
    with mock.patch.object(rgbmatrix_configurer, "RGBMatrix") as matrix_class:
        rgbmatrix_configurer.get_rgb_matrix(**settings)
    return matrix_class.call_args.kwargs["options"]


class GetRgbMatrixTest(unittest.TestCase):
    def test_keeps_the_library_defaults_unless_told_otherwise(self):
        options = _options_for()
        self.assertEqual(options.pwm_bits, 11)
        self.assertEqual(options.limit_refresh_rate_hz, 0)

    def test_passes_the_refresh_cap_and_color_depth_through(self):
        options = _options_for(pwm_bits=9, limit_refresh_rate_hz=160)
        self.assertEqual(options.pwm_bits, 9)
        self.assertEqual(options.limit_refresh_rate_hz, 160)


if __name__ == "__main__":
    unittest.main()
