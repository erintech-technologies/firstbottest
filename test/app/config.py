from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    required_channel: str
    store_name: str
    database_url: str
    support_username: str


def get_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or token == "put_your_bot_token_here":
        raise RuntimeError("BOT_TOKEN را در فایل .env تنظیم کنید (از .env.example کپی بگیرید).")
    ids = frozenset(int(value.strip()) for value in os.getenv("ADMIN_IDS", "137217869").split(",") if value.strip())
    return Settings(token, ids, os.getenv("REQUIRED_CHANNEL", "@testchannelforerfan").strip(),
                    os.getenv("STORE_NAME", "فروشگاه تستی").strip(),
                    os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/shop.db").strip(),
                    os.getenv("SUPPORT_USERNAME", "").strip().lstrip("@"))

