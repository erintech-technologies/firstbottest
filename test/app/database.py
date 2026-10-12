from pathlib import Path
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def make_database(url: str):
    if url.startswith("sqlite+") and "///" in url:
        raw_path = url.split("///", 1)[1]
        if raw_path and raw_path != ":memory:":
            Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(url, echo=False)
    return engine, async_sessionmaker(engine, expire_on_commit=False)

