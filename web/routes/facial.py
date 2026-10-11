"""Run the supplied TCN or logistic benchmark with its original schema."""
from flask import Blueprint, current_app
from web.routes import json_object
router = Blueprint('facial_score', __name__)

def score_payload(body):
    return current_app.extensions['model_service'].facial(body)

@router.post('/api/facial')
def facial_score():
    return score_payload(json_object())
