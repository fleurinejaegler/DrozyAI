"""Run the saved watch pipeline on complete training-compatible features."""
from flask import Blueprint, current_app
from web.routes import json_object
router = Blueprint('watch_score', __name__)

def score_features(value):
    return current_app.extensions['model_service'].watch(value)['score']

@router.post('/api/score')
def watch_score():
    body = json_object()
    return current_app.extensions['model_service'].watch(body.get('features', body))
