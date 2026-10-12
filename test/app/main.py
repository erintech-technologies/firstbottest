import asyncio
from .config import get_settings
from .database import Base, make_database
from . import models
from .bot import run_bot


async def main():
    settings = get_settings()
    engine, sessions = make_database(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        await run_bot(settings, sessions)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
