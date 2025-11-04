# models.py — MealMind data models
from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)

    # identity
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    username = db.Column(db.String(120), unique=True, index=True, nullable=False)
    employee_id = db.Column(db.String(50), unique=True, index=True)
    email = db.Column(db.String(200), index=True)

    # role: Manager, Cook, Dietitian, Dietary Aide
    role = db.Column(db.String(50), default="Dietary Aide")

    # passwords
    password_hash = db.Column(db.String(255))
    # legacy/plaintext field so old data still works
    password = db.Column(db.String(255))

    must_change_password = db.Column(db.Boolean, default=False)

    # MFA
    mfa_enabled = db.Column(db.Boolean, default=False)
    mfa_secret = db.Column(db.String(64))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, raw: str):
        self.password_hash = generate_password_hash(raw)
        # keep legacy blank so we don't store plain
        self.password = None

    def check_password(self, raw: str) -> bool:
        if self.password_hash:
            try:
                return check_password_hash(self.password_hash, raw)
            except Exception:
                pass
        # fallback to legacy plain text
        if self.password:
            return self.password == raw
        return False

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


class Resident(db.Model):
    __tablename__ = "resident"

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(120), nullable=False)
    last_name = db.Column(db.String(120), nullable=False)

    birthday = db.Column(db.Date)
    # some of your earlier versions stored age as a column
    age = db.Column(db.Integer)

    diet = db.Column(db.String(200))
    allergies = db.Column(db.String(300))
    illnesses = db.Column(db.String(300))
    medications = db.Column(db.String(300))
    fluids = db.Column(db.String(200))
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def calc_age(self):
        if not self.birthday:
            return None
        today = date.today()
        return today.year - self.birthday.year - (
            (today.month, today.day) < (self.birthday.month, self.birthday.day)
        )

    def __repr__(self):
        return f"<Resident {self.last_name}, {self.first_name}>"


class InventoryItem(db.Model):
    __tablename__ = "inventory_item"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    unit = db.Column(db.String(50), nullable=False, default="pcs")
    quantity = db.Column(db.Float, default=0.0)
    low_stock_threshold = db.Column(db.Float, default=0.0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<InventoryItem {self.name} ({self.quantity} {self.unit})>"


# ---------------- Menus ----------------

class Menu(db.Model):
    """
    A reusable meal template: Breakfast / Lunch / Dinner
    with a title and optional description, and ingredient lines that point to InventoryItem.
    """
    __tablename__ = "menu"

    id = db.Column(db.Integer, primary_key=True)
    meal_type = db.Column(db.String(50), nullable=False)  # Breakfast / Lunch / Dinner
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    ingredients = db.relationship(
        "MenuIngredient",
        backref="menu",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    def __repr__(self):
        return f"<Menu {self.meal_type} - {self.title}>"


class MenuIngredient(db.Model):
    """
    One ingredient inside a Menu, pointing to InventoryItem.
    """
    __tablename__ = "menu_ingredient"

    id = db.Column(db.Integer, primary_key=True)
    menu_id = db.Column(db.Integer, db.ForeignKey("menu.id"), nullable=False)
    inventory_id = db.Column(db.Integer, db.ForeignKey("inventory_item.id"), nullable=False)
    quantity = db.Column(db.Float, default=0.0)

    inventory_item = db.relationship("InventoryItem")

    def __repr__(self):
        return f"<MenuIngredient {self.inventory_id} x {self.quantity}>"


class MenuSchedule(db.Model):
    """
    A specific planned meal on a specific date (e.g. 2025-11-04 Lunch = Menu #12)
    """
    __tablename__ = "menu_schedule"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    meal_type = db.Column(db.String(50), nullable=False)
    menu_id = db.Column(db.Integer, db.ForeignKey("menu.id"))
    notes = db.Column(db.Text)

    menu = db.relationship("Menu")

    items = db.relationship(
        "MenuScheduleItem",
        backref="schedule",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    def __repr__(self):
        return f"<MenuSchedule {self.date} {self.meal_type}>"


class MenuScheduleItem(db.Model):
    """
    What inventory was consumed for that scheduled meal.
    """
    __tablename__ = "menu_schedule_item"

    id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey("menu_schedule.id"), nullable=False)
    inventory_id = db.Column(db.Integer, db.ForeignKey("inventory_item.id"), nullable=False)
    quantity_used = db.Column(db.Float, default=0.0)

    inventory_item = db.relationship("InventoryItem")

    def __repr__(self):
        return f"<MenuScheduleItem schedule={self.schedule_id} inv={self.inventory_id} qty={self.quantity_used}>"
