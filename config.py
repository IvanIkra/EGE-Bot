import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
DATABASE_URL: str = os.environ["DATABASE_URL"]
REDIS_URL: str = os.environ["REDIS_URL"]
ADMIN_LOGIN: str = os.environ["ADMIN_LOGIN"]
ADMIN_PASSWORD: str = os.environ["ADMIN_PASSWORD"]

ADMIN_PORT: int = int(os.getenv("ADMIN_PORT", "5000"))
