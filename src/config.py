import os
from dotenv import load_dotenv

load_dotenv()

PAGE_LOAD_TIMEOUT = int(os.getenv("PAGE_LOAD_TIMEOUT", "60000"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
LEETCODE_BASE_URL = os.getenv("LEETCODE_BASE_URL", "https://leetcode.com")
