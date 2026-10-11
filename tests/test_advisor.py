"""Compact local wire output expands into the original advisor contract."""
import unittest
from unittest.mock import Mock,patch
from src.advisor import llm_meta_advisor as advisor

class AdvisorContractTests(unittest.TestCase):
    def response(self,content):
        response=Mock();response.json.return_value={"choices":[{"message":{"content":content}}]}
        return response
    def test_compact_output_keeps_public_contract_and_python_arithmetic(self):
        with patch.object(advisor.requests,"post",return_value=self.response('[0.8,0.7,"Measured signals disagree."]')):
            result=advisor._call_llm({"watch_score":.2,"vision_score":.8})
        self.assertAlmostEqual(result["fused_score"],.32)
        self.assertEqual(result["action"],"continue")
        self.assertAlmostEqual(sum(result["weights"].values()),1)
        self.assertEqual(result["reason"],"Measured signals disagree.")
    def test_invalid_weight_falls_back(self):
        with patch.object(advisor.requests,"post",return_value=self.response('{"w":2,"r":"test","c":0.7}')):
            result=advisor.meta_advisor(.2,.8)
        self.assertTrue(result["source"].startswith("fallback"))
        self.assertAlmostEqual(result["fused_score"],.5)
    def test_non_object_response_falls_back(self):
        with patch.object(advisor.requests,"post",return_value=self.response('[]')):
            result=advisor.meta_advisor(.2,.8)
        self.assertTrue(result["source"].startswith("fallback"))
