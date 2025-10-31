# models.py
from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.orm import relationship

db = SQLAlchemy()

# -----------------------------
# User
# -----------------------------
class User(db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(80))
    last_name = db.Column(db.String(80))
    username = db.Column(db.String(80), unique=True, nullable=False)
    employee_id = db.Column(db.String(40), unique=True)
    email = db.Column(db.String(255))
    role = db.Column(db.String(40), nullable=False, default="Dietary Aide")
    password_hash = db.Column(db.String(255), nullable=False)
    must_change_password = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Password helpers
    def set_password(self, pw: str) -> None:
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw: str) -> bool:
        return check_password_hash(self.password_hash, pw)


# -----------------------------
# Resident  (NO 'room' column)
# -----------------------------
class Resident(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(80), nullable=False, index=True)
    last_name = db.Column(db.String(80), nullable=False, index=True)
    birthday = db.Column(db.Date, nullable=True)
    medications = db.Column(db.Text, nullable=True)
    illnesses = db.Column(db.Text, nullable=True)
    allergies = db.Column(db.Text, nullable=True)
    fluids = db.Column(db.String(80), nullable=True)
    diet = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def age(self) -> int | None:
        """Compute age from birthday (shown in list, not stored)."""
        if not self.birthday:
            return None
        today = date.today()
        years = today.year - self.birthday.year
        if (today.month, today.day) < (self.birthday.month, self.birthday.day):
            years -= 1
        return years


# -----------------------------
# InventoryItem
# -----------------------------
class InventoryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), index=True, unique=True, nullable=False)
    unit = db.Column(db.String(30), default="pcs")
    quantity = db.Column(db.Float, default=0)
    low_stock_threshold = db.Column(db.Float, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# =======================================================
# 🧾 MENU MANAGEMENT AND SCHEDULER SYSTEM
# =======================================================

# -----------------------------
# Menu: reusable titled menu (Breakfast/Lunch/Dinner)
# -----------------------------
class Menu(db.Model):
    __tablename__ = "menu"
    id = db.Column(db.Integer, primary_key=True)
    meal_type = db.Column(db.String(50), nullable=False)  # Breakfast, Lunch, Dinner
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    ingredients = relationship("MenuIngredient", backref="menu", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Menu {self.meal_type} - {self.title}>"


# -----------------------------
# MenuIngredient: links a Menu to Inventory items
# -----------------------------
class MenuIngredient(db.Model):
    __tablename__ = "menu_ingredient"
    id = db.Column(db.Integer, primary_key=True)
    menu_id = db.Column(db.Integer, db.ForeignKey("menu.id"), nullable=False)
    inventory_id = db.Column(db.Integer, db.ForeignKey("inventory_item.id"), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(50))

    inventory_item = relationship("InventoryItem")

    def __repr__(self):
        return f"<MenuIngredient {self.inventory_item.name if self.inventory_item else ''} {self.quantity}{self.unit}>"


# -----------------------------
# MenuSchedule: date-based menu plan
# -----------------------------
class MenuSchedule(db.Model):
    __tablename__ = "menu_schedule"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    meal_type = db.Column(db.String(50), nullable=False)
    menu_id = db.Column(db.Integer, db.ForeignKey("menu.id"))
    notes = db.Column(db.Text)
    items = relationship("MenuScheduleItem", backref="schedule", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<MenuSchedule {self.date} {self.meal_type}>"


# -----------------------------
# MenuScheduleItem: individual items applied per scheduled date
# -----------------------------
class MenuScheduleItem(db.Model):
    __tablename__ = "menu_schedule_item"
    id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey("menu_schedule.id"), nullable=False)
    inventory_id = db.Column(db.Integer, db.ForeignKey("inventory_item.id"), nullable=False)
    quantity_used = db.Column(db.Float, nullable=False)

    inventory_item = relationship("InventoryItem")

    def __repr__(self):
        return f"<MenuScheduleItem {self.inventory_item.name if self.inventory_item else ''} -{self.quantity_used}>"
