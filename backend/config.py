"""Load configuration from environment variables / .env file."""

import os
from dotenv import load_dotenv

load_dotenv()

KASEYA_BASE_URL = os.getenv("KASEYA_BASE_URL", "https://10.78.78.178")
KASEYA_USERNAME = os.getenv("KASEYA_USERNAME", "")
KASEYA_TOKEN = os.getenv("KASEYA_TOKEN", "")
KASEYA_CRED_HASH = os.getenv("KASEYA_CRED_HASH", "")
KASEYA_SESSION_TOKEN = os.getenv("KASEYA_SESSION_TOKEN", "")
BACKEND_HOST = os.getenv("BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "3333"))
TOKEN_CACHE_TTL = int(os.getenv("TOKEN_CACHE_TTL", "1500"))
