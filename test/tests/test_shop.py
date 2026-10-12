import asyncio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.database import Base
from app.models import Category, Product, StockItem, User, Order, Transaction
from app.shop import purchase, stock_count


async def create_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_purchase_debits_wallet_records_order_and_delivers():
    async def scenario():
        engine, sessions = await create_db()
        async with sessions() as session:
            async with session.begin():
                category = Category(title="آزمایشی")
                session.add(category)
                await session.flush()
                product = Product(category_id=category.id, title="کد", description="", price=25000)
                user = User(telegram_id=44, first_name="خریدار", balance=40000)
                session.add_all([product, user])
                await session.flush()
                session.add(StockItem(product_id=product.id, content="SAMPLE-CODE-123"))
                await session.flush()
                pid = product.id
            user = await session.scalar(select(User).where(User.telegram_id == 44))
            await session.commit()
            async with session.begin():
                _, delivery = await purchase(session, user, pid)
            assert delivery == "SAMPLE-CODE-123"
            assert user.balance == 15000
            assert await stock_count(session, pid) == 0
            assert await session.scalar(select(Order).where(Order.user_id == user.id)) is not None
            tx = await session.scalar(select(Transaction).where(Transaction.user_id == user.id))
            assert tx.amount == -25000
        await engine.dispose()
    asyncio.run(scenario())


def test_purchase_refuses_insufficient_balance_without_changing_stock():
    async def scenario():
        engine, sessions = await create_db()
        async with sessions() as session:
            async with session.begin():
                category = Category(title="کالا")
                session.add(category)
                await session.flush()
                product = Product(category_id=category.id, title="محصول", price=5000)
                user = User(telegram_id=7, first_name="", balance=100)
                session.add_all([product, user])
                await session.flush()
                session.add(StockItem(product_id=product.id, content="secret"))
                await session.flush()
                pid = product.id
            user = await session.scalar(select(User).where(User.telegram_id == 7))
            await session.commit()
            with pytest.raises(ValueError, match="کیف پول"):
                async with session.begin():
                    await purchase(session, user, pid)
            refreshed_user = await session.scalar(select(User).where(User.telegram_id == 7))
            assert refreshed_user.balance == 100
            assert await stock_count(session, pid) == 1
        await engine.dispose()
    asyncio.run(scenario())
