from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from .config import Settings
from .models import User, Category, Product, StockItem, Order, Transaction, TopUpRequest, CartItem
from .shop import get_user, purchase, stock_count

router = Router()


class AdminFlow(StatesGroup):
    category = State()
    product_title = State()
    product_price = State()
    product_description = State()
    stock_content = State()


class TopUpFlow(StatesGroup):
    amount = State()
    receipt = State()


def button(text, data):
    return InlineKeyboardButton(text=text, callback_data=data)


def main_menu(admin=False):
    rows = [[button("🛍 محصولات", "catalog"), button("🛒 سبد خرید", "cart")],
            [button("👤 حساب من", "profile"), button("💳 افزایش موجودی", "topup")],
            [button("📦 سفارش‌های من", "orders")]]
    if admin:
        rows.append([button("⚙️ مدیریت", "admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def member_ok(bot, user_id, channel):
    if not channel:
        return True
    try:
        member = await bot.get_chat_member(channel, user_id)
        return member.status in {"creator", "administrator", "member", "restricted"} and getattr(member, "is_member", True)
    except Exception:
        return False


def is_admin(tg_id, settings):
    return tg_id in settings.admin_ids


@router.message(CommandStart())
async def start(message: Message, settings: Settings, sessions):
    if not await member_ok(message.bot, message.from_user.id, settings.required_channel):
        await message.answer(f"برای استفاده ابتدا عضو کانال {settings.required_channel} شوید و دوباره /start را بزنید.")
        return
    async with sessions() as session:
        async with session.begin():
            await get_user(session, message.from_user)
    await message.answer(f"به {settings.store_name} خوش آمدید.", reply_markup=main_menu(is_admin(message.from_user.id, settings)))


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("عملیات لغو شد.")


@router.callback_query(F.data == "home")
async def home(call: CallbackQuery, settings: Settings):
    await call.message.edit_text("منوی اصلی", reply_markup=main_menu(is_admin(call.from_user.id, settings)))
    await call.answer()


@router.callback_query(F.data == "catalog")
async def catalog(call: CallbackQuery, sessions):
    async with sessions() as session:
        products = (await session.scalars(select(Product).where(Product.active.is_(True)).order_by(Product.id))).all()
    rows = [[button(f"{p.title} · {p.price:,} تومان", f"product:{p.id}")] for p in products]
    rows.append([button("بازگشت", "home")])
    await call.message.edit_text("محصولات" if products else "هنوز محصول فعالی ثبت نشده است.",
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@router.callback_query(F.data.startswith("product:"))
async def product_detail(call: CallbackQuery, sessions):
    pid = int(call.data.split(":")[1])
    async with sessions() as session:
        product = await session.get(Product, pid)
        count = await stock_count(session, pid) if product else 0
    if not product or not product.active:
        text, rows = "محصول پیدا نشد.", [[button("بازگشت", "catalog")]]
    else:
        text = f"{product.title}\n\n{product.description}\n\nقیمت: {product.price:,} تومان · موجودی: {count}"
        rows = [[button("افزودن به سبد", f"add:{pid}")], [button("خرید با کیف پول", f"buy:{pid}")], [button("بازگشت", "catalog")]]
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@router.callback_query(F.data.startswith("add:"))
async def add_cart(call: CallbackQuery, sessions):
    pid = int(call.data.split(":")[1])
    async with sessions() as session:
        async with session.begin():
            user = await session.scalar(select(User).where(User.telegram_id == call.from_user.id))
            product = await session.get(Product, pid)
            count = await stock_count(session, pid)
            if not product or not product.active or count < 1:
                msg = "این محصول موجود نیست."
            elif not user:
                msg = "ابتدا /start را بزنید."
            else:
                row = await session.scalar(select(CartItem).where(CartItem.user_id == user.id, CartItem.product_id == pid))
                if row:
                    row.quantity = 1
                else:
                    session.add(CartItem(user_id=user.id, product_id=pid))
                msg = "محصول به سبد خرید افزوده شد."
    await call.answer(msg, show_alert=True)


@router.callback_query(F.data == "cart")
async def cart(call: CallbackQuery, sessions):
    async with sessions() as session:
        user = await session.scalar(select(User).where(User.telegram_id == call.from_user.id))
        items = (await session.scalars(select(CartItem).where(CartItem.user_id == user.id))).all() if user else []
        pairs = [(item, await session.get(Product, item.product_id)) for item in items]
    pairs = [(item, product) for item, product in pairs if product and product.active]
    total = sum(item.quantity * product.price for item, product in pairs)
    rows = [[button(f"حذف {product.title}", f"remove:{item.product_id}")] for item, product in pairs]
    if pairs:
        rows.append([button(f"خرید همه · {total:,} تومان", "checkout")])
    rows.append([button("بازگشت", "home")])
    text = "سبد خرید خالی است." if not pairs else "سبد خرید:\n" + "\n".join(f"{p.title} — {p.price:,} تومان" for _, p in pairs) + f"\nجمع: {total:,} تومان"
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@router.callback_query(F.data.startswith("remove:"))
async def remove_cart(call: CallbackQuery, sessions):
    pid = int(call.data.split(":")[1])
    async with sessions() as session:
        async with session.begin():
            user = await session.scalar(select(User).where(User.telegram_id == call.from_user.id))
            row = await session.scalar(select(CartItem).where(CartItem.user_id == user.id, CartItem.product_id == pid)) if user else None
            if row:
                await session.delete(row)
    await call.answer("از سبد حذف شد.")
    await cart(call, sessions)


@router.callback_query(F.data == "checkout")
async def checkout(call: CallbackQuery, sessions):
    deliveries = []
    try:
        async with sessions() as session:
            async with session.begin():
                user = await session.scalar(select(User).where(User.telegram_id == call.from_user.id))
                rows = (await session.scalars(select(CartItem).where(CartItem.user_id == user.id))).all() if user else []
                if not rows:
                    raise ValueError("سبد خرید خالی است.")
                for row in rows:
                    product = await session.get(Product, row.product_id)
                    if not product or not product.active:
                        raise ValueError("یکی از محصولات دیگر فعال نیست.")
                    for _ in range(row.quantity):
                        _, content = await purchase(session, user, product.id)
                        deliveries.append((product.title, content))
                for row in rows:
                    await session.delete(row)
        await call.message.answer("خرید موفق:\n\n" + "\n\n".join(f"{title}:\n{content}" for title, content in deliveries))
        await call.answer("سفارش ثبت شد.")
    except ValueError as exc:
        await call.answer(str(exc), show_alert=True)


@router.callback_query(F.data.startswith("buy:"))
async def buy_one(call: CallbackQuery, sessions):
    pid = int(call.data.split(":")[1])
    try:
        async with sessions() as session:
            async with session.begin():
                user = await session.scalar(select(User).where(User.telegram_id == call.from_user.id))
                if not user:
                    raise ValueError("ابتدا /start را بزنید.")
                _, content = await purchase(session, user, pid)
        await call.message.answer(f"پرداخت موفق بود.\n\nتحویل محصول:\n{content}")
        await call.answer("سفارش ثبت شد.")
    except ValueError as exc:
        await call.answer(str(exc), show_alert=True)


@router.callback_query(F.data == "profile")
async def profile(call: CallbackQuery, sessions):
    async with sessions() as session:
        user = await session.scalar(select(User).where(User.telegram_id == call.from_user.id))
    await call.message.edit_text(f"شناسه تلگرام: {call.from_user.id}\nموجودی: {user.balance if user else 0:,} تومان",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button("تاریخچه تراکنش", "history")], [button("بازگشت", "home")]]))
    await call.answer()


@router.callback_query(F.data == "history")
async def history(call: CallbackQuery, sessions):
    async with sessions() as session:
        user = await session.scalar(select(User).where(User.telegram_id == call.from_user.id))
        entries = (await session.scalars(select(Transaction).where(Transaction.user_id == user.id).order_by(Transaction.id.desc()).limit(10))).all() if user else []
    text = "تراکنشی ثبت نشده است." if not entries else "\n".join(f"{e.amount:+,} تومان — {e.note}" for e in entries)
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button("بازگشت", "profile")]]))
    await call.answer()


@router.callback_query(F.data == "orders")
async def orders(call: CallbackQuery, sessions):
    async with sessions() as session:
        user = await session.scalar(select(User).where(User.telegram_id == call.from_user.id))
        records = (await session.scalars(select(Order).where(Order.user_id == user.id).order_by(Order.id.desc()).limit(20))).all() if user else []
        pairs = [(o, await session.get(Product, o.product_id)) for o in records]
    text = "هنوز سفارشی ثبت نشده است." if not records else "\n\n".join(
        f"سفارش #{o.id} — {p.title if p else 'محصول'} — {o.amount:,} تومان — {o.status}\nتحویل: {o.delivery or 'در انتظار بررسی'}" for o, p in pairs)
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button("بازگشت", "home")]]))
    await call.answer()


@router.callback_query(F.data == "topup")
async def topup_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(TopUpFlow.amount)
    await call.message.answer("مبلغ شارژ را به تومان وارد کنید؛ برای لغو /cancel را بزنید.")
    await call.answer()


@router.message(TopUpFlow.amount)
async def topup_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text.replace(",", "").strip())
        if amount < 1000 or amount > 100_000_000:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("مبلغ معتبر بین ۱٬۰۰۰ تا ۱۰۰٬۰۰۰٬۰۰۰ تومان وارد کنید.")
        return
    await state.update_data(amount=amount)
    await state.set_state(TopUpFlow.receipt)
    await message.answer("تصویر رسید را بفرستید. شارژ پس از بررسی مدیر انجام می‌شود.")


@router.message(TopUpFlow.receipt)
async def topup_receipt(message: Message, state: FSMContext, sessions, settings: Settings):
    if not message.photo:
        await message.answer("لطفاً تصویر رسید را به‌صورت عکس بفرستید یا /cancel بزنید.")
        return
    data = await state.get_data()
    async with sessions() as session:
        async with session.begin():
            user = await get_user(session, message.from_user)
            request = TopUpRequest(user_id=user.id, amount=data["amount"], receipt_file_id=message.photo[-1].file_id)
            session.add(request)
            await session.flush()
            req_id = request.id
    await state.clear()
    await message.answer(f"درخواست شارژ #{req_id} ثبت شد.")
    for admin_id in settings.admin_ids:
        try:
            await message.bot.send_photo(admin_id, message.photo[-1].file_id,
                caption=f"درخواست شارژ #{req_id}\nکاربر: {message.from_user.id}\nمبلغ: {data['amount']:,} تومان",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button("تأیید", f"topup:ok:{req_id}"), button("رد", f"topup:no:{req_id}")]]))
        except Exception:
            pass


@router.callback_query(F.data.startswith("topup:"))
async def topup_decision(call: CallbackQuery, sessions, settings: Settings):
    if not is_admin(call.from_user.id, settings):
        await call.answer("دسترسی ندارید.", show_alert=True)
        return
    _, decision, req_id = call.data.split(":")
    async with sessions() as session:
        async with session.begin():
            req = await session.get(TopUpRequest, int(req_id))
            if not req or req.status != "pending":
                await call.answer("درخواست قبلاً بررسی شده یا وجود ندارد.", show_alert=True)
                return
            req.status = "approved" if decision == "ok" else "rejected"
            user = await session.get(User, req.user_id)
            if decision == "ok":
                user.balance += req.amount
                session.add(Transaction(user_id=user.id, amount=req.amount, kind="topup", note=f"شارژ #{req.id}"))
            tg_id, amount = user.telegram_id, req.amount
    try:
        await call.bot.send_message(tg_id, f"درخواست شارژ شما {'تأیید شد' if decision == 'ok' else 'رد شد'}؛ مبلغ: {amount:,} تومان")
    except Exception:
        pass
    await call.message.edit_caption(caption=f"درخواست #{req_id} {'تأیید شد' if decision == 'ok' else 'رد شد'}.")
    await call.answer("ثبت شد.")


@router.callback_query(F.data == "admin")
async def admin_menu(call: CallbackQuery, settings: Settings):
    if not is_admin(call.from_user.id, settings):
        await call.answer("دسترسی ندارید.", show_alert=True)
        return
    rows = [[button("افزودن دسته‌بندی", "adm:cat")], [button("افزودن محصول", "adm:product")],
            [button("افزودن موجودی دیجیتال", "adm:stock")], [button("نمایش محصولات", "adm:list")], [button("بازگشت", "home")]]
    await call.message.edit_text("پنل مدیریت", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@router.callback_query(F.data.startswith("adm:"))
async def admin_action(call: CallbackQuery, state: FSMContext, settings: Settings, sessions):
    if not is_admin(call.from_user.id, settings):
        await call.answer("دسترسی ندارید.", show_alert=True)
        return
    action = call.data.split(":")[1]
    if action == "cat":
        await state.set_state(AdminFlow.category)
        await call.message.answer("نام دسته‌بندی را بفرستید.")
    elif action == "product":
        async with sessions() as session:
            cats = (await session.scalars(select(Category))).all()
        if cats:
            await call.message.answer("دسته‌بندی را انتخاب کنید:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button(c.title, f"pcat:{c.id}")] for c in cats]))
        else:
            await call.message.answer("ابتدا یک دسته‌بندی بسازید.")
    elif action == "stock":
        async with sessions() as session:
            products = (await session.scalars(select(Product).where(Product.active.is_(True)))).all()
        if products:
            await call.message.answer("محصول را انتخاب کنید:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button(p.title, f"stockp:{p.id}")] for p in products]))
        else:
            await call.message.answer("ابتدا محصول بسازید.")
    elif action == "list":
        async with sessions() as session:
            products = (await session.scalars(select(Product).order_by(Product.id))).all()
            lines = [f"#{p.id} {p.title} — {p.price:,} تومان — موجودی {await stock_count(session, p.id)}" for p in products]
        await call.message.answer("\n".join(lines) if lines else "محصولی ثبت نشده است.")
    await call.answer()


@router.callback_query(F.data.startswith("pcat:"))
async def admin_pick_category(call: CallbackQuery, state: FSMContext, settings: Settings):
    if not is_admin(call.from_user.id, settings):
        await call.answer("دسترسی ندارید.")
        return
    await state.update_data(category_id=int(call.data.split(":")[1]))
    await state.set_state(AdminFlow.product_title)
    await call.message.answer("نام محصول را وارد کنید:")
    await call.answer()


@router.callback_query(F.data.startswith("stockp:"))
async def admin_pick_stock(call: CallbackQuery, state: FSMContext, settings: Settings):
    if not is_admin(call.from_user.id, settings):
        await call.answer("دسترسی ندارید.")
        return
    await state.update_data(product_id=int(call.data.split(":")[1]))
    await state.set_state(AdminFlow.stock_content)
    await call.message.answer("هر کد/محتوا را در یک خط بفرستید؛ هر خط یک موجودی است:")
    await call.answer()


@router.message(AdminFlow.category)
async def admin_category(message: Message, state: FSMContext, settings: Settings, sessions):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    title = message.text.strip()[:100] if message.text else ""
    if not title:
        await message.answer("نام متنی معتبر بفرستید.")
        return
    async with sessions() as session:
        async with session.begin():
            if await session.scalar(select(Category).where(Category.title == title)):
                await message.answer("این دسته‌بندی از قبل وجود دارد.")
                return
            session.add(Category(title=title))
    await state.clear()
    await message.answer("دسته‌بندی ساخته شد.")


@router.message(AdminFlow.product_title)
async def admin_product_title(message: Message, state: FSMContext, settings: Settings):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    title = message.text.strip()[:160] if message.text else ""
    if not title:
        await message.answer("نام معتبر بفرستید.")
        return
    await state.update_data(title=title)
    await state.set_state(AdminFlow.product_price)
    await message.answer("قیمت را به تومان وارد کنید:")


@router.message(AdminFlow.product_price)
async def admin_product_price(message: Message, state: FSMContext, settings: Settings):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    try:
        price = int(message.text.replace(",", "").strip())
        if price <= 0 or price > 2_000_000_000:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("قیمت باید عدد مثبت و معتبر باشد.")
        return
    await state.update_data(price=price)
    await state.set_state(AdminFlow.product_description)
    await message.answer("توضیحات را بفرستید (یا - برای بدون توضیحات):")


@router.message(AdminFlow.product_description)
async def admin_product_description(message: Message, state: FSMContext, settings: Settings, sessions):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    data = await state.get_data()
    desc = (message.text or "").strip()
    async with sessions() as session:
        async with session.begin():
            session.add(Product(category_id=data["category_id"], title=data["title"], price=data["price"],
                                description="" if desc == "-" else desc[:2000]))
    await state.clear()
    await message.answer("محصول ساخته شد. اکنون موجودی آن را از پنل مدیریت اضافه کنید.")


@router.message(AdminFlow.stock_content)
async def admin_stock_content(message: Message, state: FSMContext, settings: Settings, sessions):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    lines = [line.strip() for line in (message.text or "").splitlines() if line.strip()]
    if not lines:
        await message.answer("حداقل یک خط محتوای دیجیتال بفرستید.")
        return
    data = await state.get_data()
    async with sessions() as session:
        async with session.begin():
            product = await session.get(Product, data["product_id"])
            if not product:
                await state.clear()
                await message.answer("محصول پیدا نشد.")
                return
            session.add_all(StockItem(product_id=product.id, content=line) for line in lines)
    await state.clear()
    await message.answer(f"{len(lines)} مورد موجودی اضافه شد.")


def create_dispatcher(settings, sessions):
    dp = Dispatcher()
    dp["settings"] = settings
    dp["sessions"] = sessions
    dp.include_router(router)
    return dp


async def run_bot(settings, sessions):
    bot = Bot(settings.bot_token)
    dp = create_dispatcher(settings, sessions)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
