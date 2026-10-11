import json
import unittest
from unittest.mock import Mock, patch

from src.advisor import local_explanation


class LocalExplanationTests(unittest.TestCase):
    def response(self, value):
        response = Mock()
        response.json.return_value = {'message':{'content':json.dumps(value)},
                                     'choices':[{'message':{'content':json.dumps(value)}}]}
        return response

    def test_returns_only_explanation_and_metadata(self):
        payload = {'action':'continue','watch_score':None,'video_score':.2}
        with patch.object(local_explanation.requests,'post',return_value=self.response(
                {'reason':'Camera measurements are available.','action':'stop now','score':1})) as post:
            result=local_explanation.explain(payload)
        self.assertEqual(result['reason'],'Camera measurements are available.')
        self.assertNotIn('action',result);self.assertNotIn('score',result)
        self.assertEqual(json.loads(post.call_args.kwargs['json']['messages'][1]['content']),payload)
        self.assertEqual(post.call_args.kwargs['json']['options']['num_ctx'],2048)

    def test_rejects_empty_non_object_and_oversized_responses(self):
        for value in [{},[],{'reason':''},{'reason':True},{'reason':'a'*401}]:
            with self.subTest(value=str(value)[:30]), patch.object(local_explanation.requests,'post',
                    return_value=self.response(value)):
                with self.assertRaises(ValueError):local_explanation.explain({})
