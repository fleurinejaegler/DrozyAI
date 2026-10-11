"""Existing fusion connected to actual model outputs."""
from flask import Blueprint, current_app
from web.routes import json_object
router = Blueprint('fusion', __name__)

@router.post('/api/fusion')
def fused_score():
    return current_app.extensions['model_service'].offline(json_object())
