import unittest
import numpy as np
import pandas as pd
from src.features.facial_sequence import FeatureConfig, aggregate_seconds, frame_events, landmark_ratios, summarize_window, FEATURES, extract_68point_window


class VideoFeatureTests(unittest.TestCase):
    def setUp(self):
        self.config = FeatureConfig(fps=10, session_seconds=10, calibration_seconds=1, window_seconds=5)
        self.eye = np.ones(100)
        self.mouth = np.zeros(100)
        self.valid = np.ones(100, dtype=bool)

    def extract(self, eye=None, mouth=None, valid=None):
        eye = self.eye if eye is None else eye
        return frame_events(eye, eye, self.mouth if mouth is None else mouth,
                            self.valid if valid is None else valid, self.config)

    def test_blink_duration_is_recorded_only_after_reopening(self):
        self.eye[10:13] = 0.3
        values, ends = self.extract()
        self.assertEqual(values[:13, 6].sum(), 0)
        self.assertEqual(values[13, 6], 1)
        self.assertAlmostEqual(float(values[13, 7]), 0.3, places=6)
        self.assertEqual(ends.tolist(), [1.3])

    def test_missing_frames_censor_a_blink_instead_of_bridging_it(self):
        self.eye[10:13] = 0.3
        self.valid[11] = False
        values, _ = self.extract()
        self.assertEqual(values[:, 6].sum(), 0)

    def test_long_closure_is_not_counted_as_a_normal_blink(self):
        self.eye[10:30] = 0.3
        values, _ = self.extract()
        self.assertEqual(values[:, 6].sum(), 0)
        self.assertEqual(values[:, 5].sum(), 1)
        self.assertAlmostEqual(float(values[29, 4]), 2.0)

    def test_future_frames_cannot_change_past_features(self):
        self.eye[10:30] = 0.3
        full, _ = self.extract()
        prefix, _ = frame_events(self.eye[:20], self.eye[:20], self.mouth[:20], self.valid[:20], self.config)
        np.testing.assert_array_equal(full[:20], prefix)

    def test_mouth_candidates_require_a_sustained_opening(self):
        self.mouth[10:15] = 0.9
        self.mouth[30:45] = 0.9
        values, _ = self.extract()
        self.assertEqual(values[:, 12].sum(), 1)
        self.assertAlmostEqual(float(values[:, 13].sum()), 1.5)

    def test_no_events_has_finite_zero_duration_and_zero_rate(self):
        values, ends = self.extract()
        seconds = aggregate_seconds(values, self.config)
        features = summarize_window(seconds[:5], ends, 0, self.config)
        self.assertEqual(list(features), FEATURES)
        self.assertTrue(np.isfinite(list(features.values())).all())
        self.assertEqual(features["blinks_per_minute"], 0)
        self.assertEqual(features["blink_duration_mean_seconds"], 0)

    def test_geometry_ratios_do_not_change_with_image_scale_or_position(self):
        points = {37:(0,0),38:(1,1),39:(3,1),40:(4,0),41:(3,-1),42:(1,-1),
                  43:(8,0),44:(9,1),45:(11,1),46:(12,0),47:(11,-1),48:(9,-1),
                  61:(0,4),62:(1,3),63:(2,3),64:(3,3),65:(4,4),66:(3,5),67:(2,5),68:(1,5)}
        row = {f"{axis}{i}": p[j] for i,p in points.items() for j,axis in enumerate("XY")}
        a = pd.DataFrame([row])
        b = a * 4 + 100
        np.testing.assert_allclose(landmark_ratios(a), [[0.5,0.5,0.5]])
        np.testing.assert_allclose(landmark_ratios(a), landmark_ratios(b))


class LandmarkWindowTests(unittest.TestCase):
    def frames(self, seconds=75):
        points = {37:(0,0),38:(1,1),39:(3,1),40:(4,0),41:(3,-1),42:(1,-1),
                  43:(8,0),44:(9,1),45:(11,1),46:(12,0),47:(11,-1),48:(9,-1),
                  61:(0,4),62:(1,3),63:(2,3),64:(3,3),65:(4,4),66:(3,5),67:(2,5),68:(1,5)}
        frames = np.zeros((seconds * 60, 68, 2))
        for index, point in points.items():
            frames[:, index - 1] = point
        return frames

    def test_window_matches_training_channel_layout(self):
        result = extract_68point_window(self.frames())
        sequence = np.asarray(result["sequence"])
        self.assertEqual(sequence.shape, (15, 60))
        np.testing.assert_allclose(sequence[[0, 1, 14]], 1)
        self.assertEqual(result["features"]["blinks_per_minute"], 0)

    def test_missing_grid_frames_are_not_invented(self):
        frames = self.frames()
        frames[-60:] = np.nan
        with self.assertRaisesRegex(ValueError, "coverage"):
            extract_68point_window(frames)

    def test_additional_future_frames_do_not_change_prior_seconds(self):
        frames = self.frames(76)
        prefix = np.asarray(extract_68point_window(frames[:75 * 60])["sequence"])
        frames[-60:, 37:39, 1] = 0.1
        full = np.asarray(extract_68point_window(frames)["sequence"])
        np.testing.assert_array_equal(prefix[:, 1:], full[:, :-1])


if __name__ == "__main__":
    unittest.main()
