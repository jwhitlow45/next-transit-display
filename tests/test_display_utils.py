import unittest
from unittest import mock

import modules.display_utils as display_utils


class CapIfEnabledTest(unittest.TestCase):
    def test_disabled_cap_leaves_colors_unchanged(self):
        # a cap of 0 means disabled, where cap_color_luminance on its own would turn every lit color black
        with mock.patch.object(display_utils, "COLOR_LUMINANCE_CAP", 0):
            self.assertEqual(display_utils.cap_if_enabled((255, 255, 255)), (255, 255, 255))
            self.assertEqual(display_utils.cap_if_enabled((0, 0, 255)), (0, 0, 255))

    def test_enabled_cap_dims_bright_colors_keeping_their_hue(self):
        with mock.patch.object(display_utils, "COLOR_LUMINANCE_CAP", 100):
            self.assertEqual(display_utils.cap_if_enabled((255, 255, 255)), (100, 100, 100))

    def test_enabled_cap_leaves_dim_colors_unchanged(self):
        with mock.patch.object(display_utils, "COLOR_LUMINANCE_CAP", 100):
            self.assertEqual(display_utils.cap_if_enabled((70, 70, 70)), (70, 70, 70))


if __name__ == "__main__":
    unittest.main()
