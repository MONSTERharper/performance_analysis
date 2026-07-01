import os
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()

MONGO_HOST = os.getenv("MONGO_HOST", "10.10.1.124")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27018"))
MONGO_USERNAME = os.getenv("MONGO_USERNAME", "pe_reader")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD", "")
MONGO_AUTH_SOURCE = os.getenv("MONGO_AUTH_SOURCE", "admin")

SYSTEM_DATABASES = {"admin", "config", "local"}

ANALYTICS_DATABASES = ["local_analytics_db", "test_db2", "test_db3"]


def get_mongo_uri() -> str:
    user = quote_plus(MONGO_USERNAME)
    password = quote_plus(MONGO_PASSWORD)
    return (
        f"mongodb://{user}:{password}@{MONGO_HOST}:{MONGO_PORT}/"
        f"?authSource={MONGO_AUTH_SOURCE}"
    )
