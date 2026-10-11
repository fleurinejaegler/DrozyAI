"""The existing page starts with ML disconnected. No weights or hardware used."""
import hashlib
import importlib
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


class ExistingPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).resolve().parents[2]
        # Workspace staging during development; actual web/ after installation.
        if (root/'integration_staging/web/app.py').exists():root=root/'integration_staging'
        sys.path.insert(0,str(root))
        cls.module=importlib.import_module('web.app')
        cls.tmp=tempfile.TemporaryDirectory()
        with patch.dict('os.environ',{'DROZY_LOG_DIRECTORY':cls.tmp.name}):
            cls.app=cls.module.create_app(prepare_only=True)
        cls.app.testing=True
        cls.client=cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.app.extensions['realtime_runtime'].close()
        bridge=cls.app.extensions['watch_bridge']
        bridge.submit(bridge.disconnect())
        owner=next((t for t in threading.enumerate() if t.ident==bridge.loop._thread_id),None)
        bridge.loop.call_soon_threadsafe(bridge.loop.stop)
        if owner:owner.join(timeout=2)
        bridge.loop.close()
        cls.tmp.cleanup()

    def test_preserves_original_page_and_assets(self):
        for url,name in [('/','index.html'),('/static/style.css','style.css'),('/static/app.js','app.js')]:
            with self.client.get(url) as response:
                self.assertEqual(response.status_code,200)
                self.assertEqual(hashlib.sha256(response.data).hexdigest(),
                    hashlib.sha256((Path(self.app.static_folder)/name).read_bytes()).hexdigest())

    def test_models_intentionally_unloaded_with_four_watch_inputs(self):
        health=self.client.get('/api/health').json
        self.assertEqual(health['models_loaded'],[])
        self.assertTrue(health['prepare_only'])
        schema=self.client.get('/api/models').json
        self.assertEqual(schema['watch']['features'],['hr_mean','rmssd','temp_trend','motion_var'])
        for endpoint in ['/api/score','/api/facial','/api/fusion']:
            response=self.client.post(endpoint,json={})
            self.assertEqual(response.status_code,503)
            self.assertIsNone(response.json['score'])
        self.assertNotIn('torch',sys.modules)
        self.assertNotIn('src.models.facial_baseline',sys.modules)

    def test_existing_local_request_controls_still_apply(self):
        self.assertEqual(self.client.get('/',headers={'Host':'example.com'}).status_code,403)
        self.assertEqual(self.client.post('/video/start',json={},headers={'Origin':'https://example.com'}).status_code,403)
        self.assertEqual(self.client.get('/health').status_code,200)


if __name__=='__main__':unittest.main()
