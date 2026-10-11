"""Lazy access to the user's existing fusion/advisor functions; never load ML."""
import importlib.util
from pathlib import Path


class RepositoryFunctions:
    def __init__(self, root):
        self.root = Path(root)
        self._fusion = self._fallback = None

    def _module(self, relative, name):
        spec = importlib.util.spec_from_file_location(name, self.root / relative)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def fuse_scores(self, watch, video, method='weighted', watch_weight=0.5):
        if self._fusion is None:
            self._fusion = self._module('src/features/fusion.py', 'drozy_existing_fusion').fuse_scores
        return self._fusion(watch, video, method=method, watch_weight=watch_weight)

    def fallback(self, risk_score, trend=0.0, top_signals=None):
        if self._fallback is None:
            self._fallback = self._module('src/advisor/fallback.py', 'drozy_existing_fallback').rule_based_advisor
        return self._fallback(risk_score, trend, top_signals)
