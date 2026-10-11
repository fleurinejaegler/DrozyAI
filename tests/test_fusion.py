"""Verify original fusion arrays and the connected API adapter."""
import unittest
import numpy as np
from src.features.fusion import fuse_scores
from web.model_service import combine
from src.advisor.fallback import rule_based_advisor
class FusionTests(unittest.TestCase):
    def test_original_methods(self):
        for method,expected in [('mean',.5),('weighted',.65),('max',.8),('product',.16)]:
            self.assertAlmostEqual(float(fuse_scores(np.array([.2]),np.array([.8]),method,.25)[0]),expected)
            self.assertAlmostEqual(combine(.2,.8,method,.25)['score'],expected)
    def test_single_modalities_and_missing(self):
        self.assertEqual(combine(None,.8)['mode'],'video_only')
        self.assertEqual(combine(.8,None)['mode'],'watch_only')
        with self.assertRaises(ValueError):combine(None,None)
    def test_action_boundaries(self):
        for score,action in [(.49,'continue'),(.5,'take a break at the next rest area'),(.75,'stop now')]:
            self.assertEqual(rule_based_advisor(score)['action'],action)
    def test_invalid_values(self):
        for v in [-1,2,float('nan'),float('inf'),True,'0.5']:
            with self.assertRaises(ValueError):combine(v,.5)
            with self.assertRaises(ValueError):combine(.5,.5,'weighted',v)
        with self.assertRaises(ValueError):combine(.2,.5,'unknown')
