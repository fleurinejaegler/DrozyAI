import logging
import uvicorn
from .main import create_app

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
uvicorn.run(create_app(), host="127.0.0.1", port=8000, log_level="info")
