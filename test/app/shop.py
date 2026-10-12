from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from .models import User, Category, Product, StockItem, Order, Transaction, CartItem


async def get_user(session: AsyncSession, tg_user) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == tg_user.id))
    if user is None:
        user = User(telegram_id=tg_user.id, first_name=tg_user.first_name or "", username=tg_user.username)
        session.add(user)
        await session.flush()
    else:
        user.first_name, user.username = tg_user.first_name or "", tg_user.username
    return user


async def purchase(session: AsyncSession, user: User, product_id: int):
    product = await session.get(Product, product_id)
    if not product or not product.active:
        raise ValueError("این محصول در دسترس نیست.")
    item = await session.scalar(select(StockItem).where(StockItem.product_id == product_id, StockItem.sold.is_(False)).limit(1))
    if not item:
        raise ValueError("موجودی محصول تمام شده است.")
    if user.balance < product.price:
        raise ValueError("موجودی کیف پول کافی نیست.")
    user.balance -= product.price
    item.sold = True
    session.add_all([Order(user_id=user.id, product_id=product.id, amount=product.price, status="paid", delivery=item.content),
                     Transaction(user_id=user.id, amount=-product.price, kind="purchase", note=f"خرید {product.title}")])
    return None, item.content


async def stock_count(session: AsyncSession, product_id: int) -> int:
    return int(await session.scalar(select(func.count(StockItem.id)).where(StockItem.product_id == product_id, StockItem.sold.is_(False))) or 0)

