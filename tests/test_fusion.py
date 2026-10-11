"""Behavioral tests for thresholds, missing sources and fusion strategies."""
import unittest

from src.features.fusion import fuse_scores


class FusionTests(unittest.TestCase):
    def test_threshold_boundaries(self):
        for score, light, alert in [(0, "green", False), (.3999, "green", False),
                                    (.4, "orange", False), (.6999, "orange", False),
                                    (.7, "red", True), (1, "red", True)]:
            result = fuse_scores(score, None)
            self.assertEqual((result["traffic_light"], result["alert"]), (light, alert))

    def test_missing_sources_do_not_look_green(self):
        result = fuse_scores(None, None)
        self.assertIsNone(result["fused_score"])
        self.assertEqual(result["traffic_light"], "unavailable")
        self.assertFalse(result["alert"])
        self.assertEqual(fuse_scores(None, .8)["mode"], "facial_only")
        self.assertEqual(fuse_scores(.8, None)["mode"], "watch_only")

    def test_max_and_weighted_average(self):
        self.assertEqual(fuse_scores(.2, .8)["fused_score"], .8)
        self.assertAlmostEqual(fuse_scores(.2, .8, "weighted_average")["fused_score"], .5)
        self.assertAlmostEqual(fuse_scores(.2, .8, "weighted_average", .25)["fused_score"], .65)

    def test_invalid_scores_weights_and_methods(self):
        for value in [-.01, 1.01, float("nan"), float("inf"), True, "0.5"]:
            with self.assertRaises(ValueError):
                fuse_scores(value, .5)
            with self.assertRaises(ValueError):
                fuse_scores(.2, .5, "weighted_average", value)
        with self.assertRaises(ValueError):
            fuse_scores(.2, .5, "meta_classifier")


if __name__ == "__main__":
    unittest.main()
