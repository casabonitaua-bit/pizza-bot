import asyncio
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))


bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

carts = {}

# ===== БАЗА ДАНИХ =====
def init_db():
    conn = sqlite3.connect("database.db")
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            desc TEXT,
            photo TEXT,
            category TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            name TEXT,
            phone TEXT,
            address TEXT,
            items TEXT,
            total INTEGER,
            date TEXT,
            status TEXT DEFAULT 'Новий'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            username TEXT,
            first_name TEXT,
            order_count INTEGER DEFAULT 0
        )
    """)

    # Додаємо початкові товари якщо таблиця порожня
    cur.execute("SELECT COUNT(*) FROM products")
    if cur.fetchone()[0] == 0:
        initial_products = [
            ("Маргарита", 199, "Томат, моцарелла, базилик", None, "pizza"),
            ("Пепероні", 229, "Томат, моцарелла, пепероні", None, "pizza"),
            ("Чотири сири", 249, "Моцарелла, гауда, пармезан, дорблю", None, "pizza"),
            ("Гавайська", 219, "Томат, моцарелла, шинка, ананас", None, "pizza"),
            ("Кола 0.5л", 45, "Coca-Cola холодна", None, "drinks"),
            ("Сік апельсин", 55, "Свіжевичавлений сік", None, "drinks"),
            ("Вода 0.5л", 25, "Мінеральна вода", None, "drinks"),
            ("Тірамісу", 89, "Класичний італійський десерт", None, "desserts"),
            ("Чізкейк", 79, "Ніжний чізкейк з ягодами", None, "desserts"),
        ]
        cur.executemany(
            "INSERT INTO products (name, price, desc, photo, category) VALUES (?,?,?,?,?)",
            initial_products
        )

    conn.commit()
    conn.close()

def get_db():
    return sqlite3.connect("database.db")

# Отримати всі товари по категорії
def db_get_products(category):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, price, desc, photo FROM products WHERE category=?", (category,))
    rows = cur.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "price": r[2], "desc": r[3], "photo": r[4]} for r in rows]

# Отримати один товар
def db_get_product(product_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, price, desc, photo, category FROM products WHERE id=?", (product_id,))
    r = cur.fetchone()
    conn.close()
    if r:
        return {"id": r[0], "name": r[1], "price": r[2], "desc": r[3], "photo": r[4], "category": r[5]}
    return None

# Додати товар
def db_add_product(name, price, desc, photo, category):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (name, price, desc, photo, category) VALUES (?,?,?,?,?)",
        (name, price, desc, photo, category)
    )
    product_id = cur.lastrowid
    conn.commit()
    conn.close()
    return product_id

# Видалити товар
def db_delete_product(product_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM products WHERE id=?", (product_id,))
    conn.commit()
    conn.close()

# Оновити фото товару
def db_update_photo(product_id, photo):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE products SET photo=? WHERE id=?", (photo, product_id))
    conn.commit()
    conn.close()

# Зберегти замовлення
def db_save_order(user_id, username, name, phone, address, items_text, total):
    conn = get_db()
    cur = conn.cursor()
    date = datetime.now().strftime("%d.%m.%Y %H:%M")
    cur.execute(
        "INSERT INTO orders (user_id, username, name, phone, address, items, total, date) VALUES (?,?,?,?,?,?,?,?)",
        (user_id, username, name, phone, address, items_text, total, date)
    )
    order_id = cur.lastrowid

    # Оновлюємо лічильник замовлень користувача
    cur.execute("""
        INSERT INTO users (telegram_id, username, first_name, order_count)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(telegram_id) DO UPDATE SET order_count = order_count + 1
    """, (user_id, username, name))

    conn.commit()
    conn.close()
    return order_id

# Отримати замовлення користувача
def db_get_user_orders(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, items, total, date, status FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 5",
        (user_id,)
    )
    rows = cur.fetchall()
    conn.close()
    return rows

# Статистика для адміна
def db_get_stats():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), SUM(total) FROM orders")
    orders_row = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM users")
    users_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM products")
    products_count = cur.fetchone()[0]
    conn.close()
    return {
        "orders": orders_row[0] or 0,
        "revenue": orders_row[1] or 0,
        "users": users_count,
        "products": products_count
    }

# ===== СТАНИ =====
class OrderForm(StatesGroup):
    name = State()
    phone = State()
    address = State()

class AdminAdd(StatesGroup):
    category = State()
    name = State()
    price = State()
    desc = State()
    photo = State()

class AdminDelete(StatesGroup):
    product_id = State()

class AdminPhoto(StatesGroup):
    product_id = State()
    photo = State()

# ===== КЛАВІАТУРИ =====
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛍 Каталог")],
        [KeyboardButton(text="🛒 Кошик"), KeyboardButton(text="📦 Мої замовлення")],
        [KeyboardButton(text="📞 Контакти")]
    ],
    resize_keyboard=True
)

admin_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Додати товар"), KeyboardButton(text="🗑 Видалити товар")],
        [KeyboardButton(text="📸 Додати фото"), KeyboardButton(text="📋 Всі товари")],
        [KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="◀️ Вийти з адмін панелі")]
    ],
    resize_keyboard=True
)

cancel_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Скасувати")]],
    resize_keyboard=True
)

skip_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⏭ Пропустити фото")],
        [KeyboardButton(text="❌ Скасувати")]
    ],
    resize_keyboard=True
)

def catalog_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍕 Піца", callback_data="cat_pizza")],
        [InlineKeyboardButton(text="🥤 Напої", callback_data="cat_drinks")],
        [InlineKeyboardButton(text="🍰 Десерти", callback_data="cat_desserts")],
    ])

def products_keyboard(category):
    products = db_get_products(category)
    buttons = []
    for p in products:
        buttons.append([InlineKeyboardButton(
            text=f"{p['name']} — {p['price']} грн",
            callback_data=f"product_{p['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_catalog")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def add_to_cart_keyboard(product_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Додати в кошик", callback_data=f"add_{product_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_catalog")]
    ])

def cart_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Оформити замовлення", callback_data="checkout")],
        [InlineKeyboardButton(text="🗑 Очистити кошик", callback_data="clear_cart")],
        [InlineKeyboardButton(text="🛍 Продовжити покупки", callback_data="continue_shopping")]
    ])

def admin_category_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍕 Піца", callback_data="admin_cat_pizza")],
        [InlineKeyboardButton(text="🥤 Напої", callback_data="admin_cat_drinks")],
        [InlineKeyboardButton(text="🍰 Десерти", callback_data="admin_cat_desserts")],
    ])

# ===== ХЕНДЛЕРИ =====

@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"👋 Привіт, {message.from_user.first_name}!\n\n"
        f"Ласкаво просимо до нашої піцерії! 🍕\n"
        f"Виберіть що вас цікавить 👇",
        reply_markup=main_menu
    )

@dp.message(Command("admin"))
async def admin_panel(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔️ У вас немає доступу!")
        return
    await state.clear()
    await message.answer("👨‍💼 *Адмін панель*\n\nВиберіть дію:", parse_mode="Markdown", reply_markup=admin_menu)

@dp.message(F.text == "◀️ Вийти з адмін панелі")
async def exit_admin(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Повернулись в головне меню 👇", reply_markup=main_menu)

# Статистика
@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    stats = db_get_stats()
    await message.answer(
        f"📊 *Статистика магазину:*\n\n"
        f"📦 Всього замовлень: {stats['orders']}\n"
        f"💰 Загальна виручка: {stats['revenue']} грн\n"
        f"👤 Користувачів: {stats['users']}\n"
        f"🍕 Товарів в меню: {stats['products']}",
        parse_mode="Markdown"
    )

# Всі товари
@dp.message(F.text == "📋 Всі товари")
async def all_products(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    text = "📋 *Всі товари:*\n\n"
    cat_names = {"pizza": "🍕 Піца", "drinks": "🥤 Напої", "desserts": "🍰 Десерти"}
    for cat_key, cat_name in cat_names.items():
        products = db_get_products(cat_key)
        if products:
            text += f"*{cat_name}:*\n"
            for p in products:
                photo_status = "📸" if p["photo"] else "🚫"
                text += f"  {photo_status} ID:{p['id']} | {p['name']} — {p['price']} грн\n"
            text += "\n"
    await message.answer(text, parse_mode="Markdown")

# Додати фото
@dp.message(F.text == "📸 Додати фото")
async def add_photo_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    text = "📋 *Товари без фото:*\n\n"
    cat_names = {"pizza": "🍕 Піца", "drinks": "🥤 Напої", "desserts": "🍰 Десерти"}
    for cat_key in cat_names:
        for p in db_get_products(cat_key):
            if not p["photo"]:
                text += f"ID:{p['id']} | {p['name']}\n"
    text += "\nВведіть ID товару:"
    await state.set_state(AdminPhoto.product_id)
    await message.answer(text, parse_mode="Markdown", reply_markup=cancel_keyboard)

@dp.message(AdminPhoto.product_id)
async def admin_photo_get_id(message: types.Message, state: FSMContext):
    if message.text == "❌ Скасувати":
        await state.clear()
        await message.answer("Скасовано.", reply_markup=admin_menu)
        return
    if not message.text.isdigit():
        await message.answer("⚠️ Введіть тільки ID!")
        return
    product = db_get_product(int(message.text))
    if not product:
        await message.answer("⚠️ Товар не знайдено!")
        return
    await state.update_data(product_id=int(message.text))
    await state.set_state(AdminPhoto.photo)
    await message.answer(f"Надішліть фото для *{product['name']}*:", parse_mode="Markdown", reply_markup=cancel_keyboard)

@dp.message(AdminPhoto.photo, F.photo)
async def admin_save_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    product = db_get_product(data["product_id"])
    db_update_photo(data["product_id"], message.photo[-1].file_id)
    await message.answer(f"✅ Фото для *{product['name']}* збережено!", parse_mode="Markdown", reply_markup=admin_menu)
    await state.clear()

# Додати товар
@dp.message(F.text == "➕ Додати товар")
async def add_product_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.set_state(AdminAdd.category)
    await message.answer("Виберіть категорію:", reply_markup=admin_category_keyboard())

@dp.callback_query(F.data.startswith("admin_cat_"))
async def admin_choose_category(callback: types.CallbackQuery, state: FSMContext):
    category = callback.data.replace("admin_cat_", "")
    await state.update_data(category=category)
    await state.set_state(AdminAdd.name)
    await callback.message.answer("Введіть назву товару:", reply_markup=cancel_keyboard)
    await callback.answer()

@dp.message(AdminAdd.name)
async def admin_get_name(message: types.Message, state: FSMContext):
    if message.text == "❌ Скасувати":
        await state.clear()
        await message.answer("Скасовано.", reply_markup=admin_menu)
        return
    await state.update_data(name=message.text)
    await state.set_state(AdminAdd.price)
    await message.answer("Введіть ціну (тільки цифри):")

@dp.message(AdminAdd.price)
async def admin_get_price(message: types.Message, state: FSMContext):
    if message.text == "❌ Скасувати":
        await state.clear()
        await message.answer("Скасовано.", reply_markup=admin_menu)
        return
    if not message.text.isdigit():
        await message.answer("⚠️ Введіть тільки цифри!")
        return
    await state.update_data(price=int(message.text))
    await state.set_state(AdminAdd.desc)
    await message.answer("Введіть опис товару:")

@dp.message(AdminAdd.desc)
async def admin_get_desc(message: types.Message, state: FSMContext):
    if message.text == "❌ Скасувати":
        await state.clear()
        await message.answer("Скасовано.", reply_markup=admin_menu)
        return
    await state.update_data(desc=message.text)
    await state.set_state(AdminAdd.photo)
    await message.answer("Надішліть фото або пропустіть:", reply_markup=skip_keyboard)

@dp.message(AdminAdd.photo, F.photo)
async def admin_get_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await save_new_product(message, state)

@dp.message(AdminAdd.photo, F.text == "⏭ Пропустити фото")
async def admin_skip_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo=None)
    await save_new_product(message, state)

async def save_new_product(message: types.Message, state: FSMContext):
    data = await state.get_data()
    product_id = db_add_product(data["name"], data["price"], data["desc"], data.get("photo"), data["category"])
    cat_names = {"pizza": "🍕 Піца", "drinks": "🥤 Напої", "desserts": "🍰 Десерти"}
    await message.answer(
        f"✅ *Товар додано!*\n\n"
        f"ID: {product_id}\n"
        f"📦 {data['name']}\n"
        f"💰 {data['price']} грн\n"
        f"📝 {data['desc']}\n"
        f"📂 {cat_names[data['category']]}\n"
        f"📸 Фото: {'✅' if data.get('photo') else '🚫 немає'}",
        parse_mode="Markdown",
        reply_markup=admin_menu
    )
    await state.clear()

# Видалити товар
@dp.message(F.text == "🗑 Видалити товар")
async def delete_product_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    text = "📋 Введіть ID товару для видалення:\n\n"
    cat_names = {"pizza": "🍕 Піца", "drinks": "🥤 Напої", "desserts": "🍰 Десерти"}
    for cat_key, cat_name in cat_names.items():
        products = db_get_products(cat_key)
        if products:
            text += f"*{cat_name}:*\n"
            for p in products:
                text += f"  ID:{p['id']} | {p['name']}\n"
            text += "\n"
    await state.set_state(AdminDelete.product_id)
    await message.answer(text, parse_mode="Markdown", reply_markup=cancel_keyboard)

@dp.message(AdminDelete.product_id)
async def admin_delete_product(message: types.Message, state: FSMContext):
    if message.text == "❌ Скасувати":
        await state.clear()
        await message.answer("Скасовано.", reply_markup=admin_menu)
        return
    if not message.text.isdigit():
        await message.answer("⚠️ Введіть тільки ID!")
        return
    product = db_get_product(int(message.text))
    if not product:
        await message.answer("⚠️ Товар не знайдено!")
        return
    db_delete_product(int(message.text))
    await message.answer(f"✅ Товар *{product['name']}* видалено!", parse_mode="Markdown", reply_markup=admin_menu)
    await state.clear()

# Каталог
@dp.message(F.text == "🛍 Каталог")
async def catalog(message: types.Message):
    await message.answer("Виберіть категорію:", reply_markup=catalog_keyboard())

@dp.callback_query(F.data.startswith("cat_"))
async def show_category(callback: types.CallbackQuery):
    category = callback.data.replace("cat_", "")
    names = {"pizza": "🍕 Піца", "drinks": "🥤 Напої", "desserts": "🍰 Десерти"}
    await callback.message.edit_text(f"{names[category]}:", reply_markup=products_keyboard(category))

@dp.callback_query(F.data == "back_catalog")
async def back_to_catalog(callback: types.CallbackQuery):
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer("Виберіть категорію:", reply_markup=catalog_keyboard())
    else:
        await callback.message.edit_text("Виберіть категорію:", reply_markup=catalog_keyboard())

@dp.callback_query(F.data == "continue_shopping")
async def continue_shopping(callback: types.CallbackQuery):
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer("Виберіть категорію:", reply_markup=catalog_keyboard())
    else:
        await callback.message.edit_text("Виберіть категорію:", reply_markup=catalog_keyboard())

@dp.callback_query(F.data.startswith("product_"))
async def show_product(callback: types.CallbackQuery):
    product_id = int(callback.data.replace("product_", ""))
    product = db_get_product(product_id)
    if product:
        text = (
            f"🍕 *{product['name']}*\n\n"
            f"📝 {product['desc']}\n\n"
            f"💰 Ціна: *{product['price']} грн*"
        )
        if product["photo"]:
            await callback.message.delete()
            await callback.message.answer_photo(
                photo=product["photo"],
                caption=text,
                parse_mode="Markdown",
                reply_markup=add_to_cart_keyboard(product_id)
            )
        else:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=add_to_cart_keyboard(product_id))

@dp.callback_query(F.data.startswith("add_"))
async def add_to_cart(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    product_id = int(callback.data.replace("add_", ""))
    product = db_get_product(product_id)
    if user_id not in carts:
        carts[user_id] = []
    for item in carts[user_id]:
        if item["id"] == product_id:
            item["qty"] += 1
            await callback.answer(f"✅ {product['name']} ще раз додано!", show_alert=True)
            return
    carts[user_id].append({"id": product_id, "name": product["name"], "price": product["price"], "qty": 1})
    await callback.answer(f"✅ {product['name']} додано в кошик!", show_alert=True)

# Кошик
@dp.message(F.text == "🛒 Кошик")
async def show_cart(message: types.Message):
    user_id = message.from_user.id
    if user_id not in carts or len(carts[user_id]) == 0:
        await message.answer("🛒 Ваш кошик порожній!", reply_markup=main_menu)
        return
    text = "🛒 *Ваш кошик:*\n\n"
    total = 0
    for item in carts[user_id]:
        subtotal = item["price"] * item["qty"]
        total += subtotal
        text += f"• {item['name']} x{item['qty']} — {subtotal} грн\n"
    text += f"\n💰 *Разом: {total} грн*"
    await message.answer(text, parse_mode="Markdown", reply_markup=cart_keyboard())

@dp.callback_query(F.data == "clear_cart")
async def clear_cart(callback: types.CallbackQuery):
    carts[callback.from_user.id] = []
    await callback.message.edit_text("🗑 Кошик очищено!")
    await callback.answer()

# Мої замовлення
@dp.message(F.text == "📦 Мої замовлення")
async def my_orders(message: types.Message):
    orders = db_get_user_orders(message.from_user.id)
    if not orders:
        await message.answer("📦 У вас ще немає замовлень!", reply_markup=main_menu)
        return
    text = "📦 *Ваші останні замовлення:*\n\n"
    for o in orders:
        text += (
            f"🔸 *Замовлення №{o[0]}*\n"
            f"📅 {o[3]}\n"
            f"💰 Сума: {o[2]} грн\n"
            f"📊 Статус: {o[4]}\n\n"
        )
    await message.answer(text, parse_mode="Markdown")

# Оформлення замовлення
@dp.callback_query(F.data == "checkout")
async def checkout(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id not in carts or len(carts[user_id]) == 0:
        await callback.answer("Кошик порожній!", show_alert=True)
        return
    await state.set_state(OrderForm.name)
    await callback.message.answer(
        "📝 *Оформлення замовлення*\n\nКрок 1 з 3\n\nВведіть ваше ім'я та прізвище:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await callback.answer()

@dp.message(F.text == "❌ Скасувати")
async def cancel_order(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Скасовано.", reply_markup=main_menu)

@dp.message(OrderForm.name)
async def get_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(OrderForm.phone)
    await message.answer("Крок 2 з 3\n\n📞 Введіть номер телефону:")

@dp.message(OrderForm.phone)
async def get_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await state.set_state(OrderForm.address)
    await message.answer("Крок 3 з 3\n\n📍 Введіть адресу доставки:")

@dp.message(OrderForm.address)
async def get_address(message: types.Message, state: FSMContext):
    await state.update_data(address=message.text)
    data = await state.get_data()
    user_id = message.from_user.id
    cart = carts.get(user_id, [])
    total = sum(i["price"] * i["qty"] for i in cart)
    items_text = ""
    for item in cart:
        items_text += f"• {item['name']} x{item['qty']} — {item['price'] * item['qty']} грн\n"

    order_id = db_save_order(
        user_id,
        message.from_user.username or "",
        data["name"],
        data["phone"],
        data["address"],
        items_text,
        total
    )

    await message.answer(
        f"✅ *Замовлення №{order_id} прийнято!*\n\n"
        f"👤 Ім'я: {data['name']}\n"
        f"📞 Телефон: {data['phone']}\n"
        f"📍 Адреса: {data['address']}\n\n"
        f"🛒 *Ваше замовлення:*\n{items_text}\n"
        f"💰 *Разом: {total} грн*\n\n"
        f"🕐 Час доставки: 40-60 хвилин\n"
        f"Дякуємо за замовлення! 🍕",
        parse_mode="Markdown",
        reply_markup=main_menu
    )

    await bot.send_message(
        ADMIN_ID,
        f"🔔 *НОВЕ ЗАМОВЛЕННЯ №{order_id}!*\n\n"
        f"👤 Ім'я: {data['name']}\n"
        f"📞 Телефон: {data['phone']}\n"
        f"📍 Адреса: {data['address']}\n\n"
        f"🛒 *Склад замовлення:*\n{items_text}\n"
        f"💰 *Сума: {total} грн*\n\n"
        f"👤 Telegram ID: {user_id}",
        parse_mode="Markdown"
    )

    carts[user_id] = []
    await state.clear()

# Контакти
@dp.message(F.text == "📞 Контакти")
async def contacts(message: types.Message):
    await message.answer(
        "📞 *Контакти:*\n\n"
        "📱 Телефон: +380991234567\n"
        "📍 Адреса: вул. Хрещатик 1\n"
        "🕐 Режим роботи: 10:00 - 22:00\n"
        "📸 Instagram: @pizza_shop",
        parse_mode="Markdown"
    )
    

async def main():
    init_db()
    print("✅ База даних підключена!")
    print("✅ Бот запущен!")
    
    from aiohttp import web
    app = web.Application()
    async def health(request):
        return web.Response(text="OK")
    app.router.add_get("/", health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
   

if __name__ == "__main__":
    asyncio.run(main())
