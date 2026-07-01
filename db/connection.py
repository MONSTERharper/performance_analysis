from functools import lru_cache

from pymongo import MongoClient
from pymongo.database import Database

from config import ANALYTICS_DATABASES, SYSTEM_DATABASES, get_mongo_uri


@lru_cache(maxsize=1)
def get_client() -> MongoClient:
    return MongoClient(get_mongo_uri(), serverSelectionTimeoutMS=15000)


def get_database(name: str) -> Database:
    return get_client()[name]


def list_analytics_databases() -> list[str]:
    client = get_client()
    return [
        db
        for db in client.list_database_names()
        if db not in SYSTEM_DATABASES
    ]


def list_all_collections() -> list[tuple[str, str]]:
    client = get_client()
    result = []
    for db_name in client.list_database_names():
        if db_name in SYSTEM_DATABASES:
            continue
        for coll_name in client[db_name].list_collection_names():
            result.append((db_name, coll_name))
    return sorted(result)
