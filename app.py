# app.py — MealMind (fixed MenuIngredient)
import os
from datetime import datetime, date
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash
)
from sqlalchemy import or_

from models import (
    db, User, Resident, InventoryItem,
    Menu, MenuIngredient, MenuSchedule, MenuScheduleItem
)


# -------------------------------------------------
# helpers
# -------------------------------------------------
def _parse_date(val):
    if not val:
        return None
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except ValueError:
        return None


def _calc_age(bday):
    if not bday:
        return None
    today = date.today()
    years = today.year - bday.year
    if (today.month, today.day) < (bday.month, bday.day):
        years -= 1
    return years


def _to_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


# -------------------------------------------------
# app factory
# -------------------------------------------------
def create_app():
    app = Flask(__name__)

    # DB path (Azure-friendly)
    db_uri = os.getenv("SQLALCHEMY_DATABASE_URI")
    if not db_uri:
        azure_dir = "/home/site/wwwroot"
        if os.path.exists(azure_dir):
            os.makedirs(azure_dir, exist_ok=True)
            db_uri = "sqlite:///" + os.path.join(azure_dir, "app.db")
        else:
            inst = os.path.join(os.getcwd(), "instance")
            os.makedirs(inst, exist_ok=True)
            db_uri = "sqlite:///" + os.path.join(inst, "app.db")

    app.config["SQLALCHEMY_DATABASE_URI"] = db_uri
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-key")

    db.init_app(app)
    with app.app_context():
        db.create_all()

    # let templates do {{ age(resident.birthday) }}
    app.jinja_env.globals["age"] = _calc_age

    # -------------------------------------------------
    # context + decorators
    # -------------------------------------------------
    @app.context_processor
    def inject_user():
        return {"current_user": session.get("user")}

    def login_required(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user" not in session:
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return wrapper

    def current_role():
        return session.get("user", {}).get("role", "")

    # -------------------------------------------------
    # AUTH
    # -------------------------------------------------
    @app.route("/", methods=["GET", "POST"])
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = (request.form.get("username") or "").strip().lower()
            password = (request.form.get("password") or "").strip()

            user = (
                User.query.filter(
                    or_(
                        User.username.ilike(username),
                        User.employee_id.ilike(username)
                    )
                ).first()
            )

            ok = False
            if user:
                stored = getattr(user, "password_hash", None) or getattr(user, "password", None)
                from werkzeug.security import check_password_hash
                try:
                    ok = check_password_hash(stored, password)
                except Exception:
                    ok = stored == password

            if user and ok:
                session["user"] = {
                    "id": user.id,
                    "username": user.username,
                    "role": user.role,
                    "first_name": user.first_name or "",
                    "last_name": user.last_name or "",
                }
                return redirect(url_for("dashboard"))

            flash("Invalid credentials.", "error")

        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # -------------------------------------------------
    # DASHBOARD
    # -------------------------------------------------
    @app.route("/dashboard")
    @login_required
    def dashboard():
        user = session.get("user", {})
        return render_template("dashboard.html", user=user)

    # -------------------------------------------------
    # RESIDENTS
    # -------------------------------------------------
    @app.route("/residents")
    @login_required
    def residents_list():
        q = (request.args.get("q") or "").strip()
        query = Resident.query
        if q:
            like = f"%{q}%"
            query = query.filter(
                or_(
                    Resident.first_name.ilike(like),
                    Resident.last_name.ilike(like),
                    Resident.diet.ilike(like),
                    Resident.allergies.ilike(like),
                )
            )
        rows = query.order_by(Resident.last_name, Resident.first_name).all()
        return render_template("residents_list.html", residents=rows, q=q)

    @app.route("/residents/new", methods=["GET", "POST"])
    @login_required
    def residents_new():
        if request.method == "POST":
            first_name = (request.form.get("first_name") or "").strip()
            last_name = (request.form.get("last_name") or "").strip()
            birthday = _parse_date(request.form.get("birthday"))
            if not first_name or not last_name:
                flash("First and last name are required.", "error")
                return render_template("residents_form.html", mode="new", values=request.form)

            r = Resident(
                first_name=first_name,
                last_name=last_name,
                birthday=birthday,
                medications=(request.form.get("medications") or "").strip(),
                illnesses=(request.form.get("illnesses") or "").strip(),
                allergies=(request.form.get("allergies") or "").strip(),
                fluids=(request.form.get("fluids") or "").strip(),
                diet=(request.form.get("diet") or "").strip(),
                notes=(request.form.get("notes") or "").strip(),
            )
            db.session.add(r)
            db.session.commit()
            return redirect(url_for("residents_list"))
        return render_template("residents_form.html", mode="new", values={})

    @app.route("/residents/<int:rid>/edit", methods=["GET", "POST"])
    @login_required
    def residents_edit(rid):
        r = Resident.query.get_or_404(rid)
        if request.method == "POST":
            r.first_name = (request.form.get("first_name") or "").strip()
            r.last_name = (request.form.get("last_name") or "").strip()
            r.birthday = _parse_date(request.form.get("birthday"))
            r.diet = (request.form.get("diet") or "").strip()
            r.allergies = (request.form.get("allergies") or "").strip()
            r.illnesses = (request.form.get("illnesses") or "").strip()
            r.medications = (request.form.get("medications") or "").strip()
            r.fluids = (request.form.get("fluids") or "").strip()
            r.notes = (request.form.get("notes") or "").strip()
            db.session.commit()
            return redirect(url_for("residents_list"))

        values = {
            "first_name": r.first_name,
            "last_name": r.last_name,
            "birthday": r.birthday.strftime("%Y-%m-%d") if r.birthday else "",
            "diet": r.diet or "",
            "allergies": r.allergies or "",
            "illnesses": r.illnesses or "",
            "medications": r.medications or "",
            "fluids": r.fluids or "",
            "notes": r.notes or "",
        }
        return render_template("residents_form.html", mode="edit", values=values, rid=r.id)

    @app.route("/residents/<int:rid>/delete", methods=["POST"])
    @login_required
    def residents_delete(rid):
        r = Resident.query.get_or_404(rid)
        db.session.delete(r)
        db.session.commit()
        return redirect(url_for("residents_list"))

    # -------------------------------------------------
    # STAFF
    # -------------------------------------------------
    @app.route("/staff")
    @login_required
    def staff_list():
        if current_role() != "Manager":
            flash("No access.", "error")
            return redirect(url_for("dashboard"))
        users = User.query.order_by(User.last_name, User.first_name).all()
        return render_template("staff_list.html", users=users)

    # -------------------------------------------------
    # INVENTORY
    # -------------------------------------------------
    INVENTORY_UNITS = [
        "kg", "g", "bags", "cases", "dozen", "cans", "liters", "jugs",
        "bunches", "heads", "loaves", "packs", "bottles", "jars", "boxes", "pcs"
    ]

    @app.route("/inventory")
    @login_required
    def inventory_list():
        q = (request.args.get("q") or "").strip()
        show = (request.args.get("show") or "all").strip()
        query = InventoryItem.query
        if q:
            query = query.filter(InventoryItem.name.ilike(f"%{q}%"))
        rows = query.order_by(InventoryItem.name).all()

        items = []
        for it in rows:
            qty = it.quantity or 0.0
            thr = it.low_stock_threshold or 0.0
            is_low = (qty <= thr) if it.low_stock_threshold is not None else False
            items.append({"obj": it, "is_low": is_low})
        if show == "low":
            items = [x for x in items if x["is_low"]]
        return render_template("inventory_list.html", items=items, q=q, show=show)

    @app.route("/inventory/new", methods=["GET", "POST"])
    @login_required
    def inventory_new():
        if request.method == "POST":
            name = (request.form.get("name") or "").strip()
            unit = (request.form.get("unit") or "").strip()
            quantity = _to_float(request.form.get("quantity"), 0.0)
            low = _to_float(request.form.get("low_stock_threshold"), 0.0)
            if not name or unit not in INVENTORY_UNITS:
                flash("Name and valid unit required.", "error")
                return render_template("inventory_form.html", mode="new", values=request.form, units=INVENTORY_UNITS)
            item = InventoryItem(
                name=name,
                unit=unit,
                quantity=quantity,
                low_stock_threshold=low,
            )
            db.session.add(item)
            db.session.commit()
            return redirect(url_for("inventory_list"))
        return render_template("inventory_form.html", mode="new", values={}, units=INVENTORY_UNITS)

    @app.route("/inventory/<int:item_id>/edit", methods=["GET", "POST"])
    @login_required
    def inventory_edit(item_id):
        it = InventoryItem.query.get_or_404(item_id)
        limited = current_role() == "Dietary Aide"
        if request.method == "POST":
            qty = _to_float(request.form.get("quantity"), 0.0)
            if limited:
                it.quantity = qty
                db.session.commit()
                return redirect(url_for("inventory_list"))
            name = (request.form.get("name") or "").strip()
            unit = (request.form.get("unit") or "").strip()
            low = _to_float(request.form.get("low_stock_threshold"), 0.0)
            if not name or unit not in INVENTORY_UNITS:
                flash("Name and valid unit required.", "error")
                return render_template("inventory_form.html", mode="edit", values=request.form, item_id=item_id, units=INVENTORY_UNITS, limited=limited)
            it.name = name
            it.unit = unit
            it.quantity = qty
            it.low_stock_threshold = low
            db.session.commit()
            return redirect(url_for("inventory_list"))
        return render_template("inventory_form.html", mode="edit", values=it, item_id=item_id, units=INVENTORY_UNITS, limited=limited)

    @app.route("/inventory/<int:iid>/bump", methods=["POST"])
    @login_required
    def inventory_bump(iid):
        delta = _to_float(request.form.get("delta"), 0.0)
        it = InventoryItem.query.get_or_404(iid)
        it.quantity = (it.quantity or 0.0) + delta
        db.session.commit()
        return redirect(url_for("inventory_list"))

    # -------------------------------------------------
    # MENU
    # -------------------------------------------------
    @app.route("/menu")
    @login_required
    def menu_hub():
        return render_template("menu_hub.html")

    # create menu
    @app.route("/menu/builder", methods=["GET", "POST"])
    @login_required
    def menu_builder():
        inventory_items = InventoryItem.query.order_by(InventoryItem.name).all()
        menus = Menu.query.order_by(Menu.meal_type, Menu.title).all()

        if request.method == "POST":
            errors = []
            meal_type = (request.form.get("meal_type") or "").strip()
            title = (request.form.get("title") or "").strip()
            description = (request.form.get("description") or "").strip()
            ing_ids = request.form.getlist("ingredient_id")
            ing_qtys = request.form.getlist("quantity")

            if meal_type not in ["Breakfast", "Lunch", "Dinner"]:
                errors.append("Please select a meal type.")
            if not title:
                errors.append("Title is required.")
            if not ing_ids:
                errors.append("Add at least 1 ingredient.")

            if errors:
                return render_template(
                    "menu_builder.html",
                    inventory_items=inventory_items,
                    menus=menus,
                    editing=False,
                    errors=errors,
                    values=request.form,
                )

            m = Menu(meal_type=meal_type, title=title, description=description)
            db.session.add(m)
            db.session.flush()

            for inv_id, qty in zip(ing_ids, ing_qtys):
                if not inv_id:
                    continue
                inv = InventoryItem.query.get(int(inv_id))
                if not inv:
                    continue
                mi = MenuIngredient(
                    menu_id=m.id,
                    inventory_id=inv.id,
                    quantity=_to_float(qty, 0.0),
                    # NOTE: no "unit=" here because your model doesn't have it
                )
                db.session.add(mi)

            db.session.commit()
            return redirect(url_for("menu_builder"))

        return render_template(
            "menu_builder.html",
            inventory_items=inventory_items,
            menus=menus,
            editing=False,
            errors=[],
            values={},
        )

    # edit menu
    @app.route("/menu/builder/<int:menu_id>", methods=["GET", "POST"])
    @login_required
    def menu_builder_edit(menu_id):
        inventory_items = InventoryItem.query.order_by(InventoryItem.name).all()
        menus = Menu.query.order_by(Menu.meal_type, Menu.title).all()
        current_menu = Menu.query.get_or_404(menu_id)

        if request.method == "POST":
            errors = []
            meal_type = (request.form.get("meal_type") or "").strip()
            title = (request.form.get("title") or "").strip()
            description = (request.form.get("description") or "").strip()
            ing_ids = request.form.getlist("ingredient_id")
            ing_qtys = request.form.getlist("quantity")

            if meal_type not in ["Breakfast", "Lunch", "Dinner"]:
                errors.append("Please select a meal type.")
            if not title:
                errors.append("Title is required.")

            if errors:
                return render_template(
                    "menu_builder.html",
                    inventory_items=inventory_items,
                    menus=menus,
                    editing=True,
                    errors=errors,
                    current_menu=current_menu,
                    values=request.form,
                )

            current_menu.meal_type = meal_type
            current_menu.title = title
            current_menu.description = description

            MenuIngredient.query.filter_by(menu_id=current_menu.id).delete()

            for inv_id, qty in zip(ing_ids, ing_qtys):
                if not inv_id:
                    continue
                inv = InventoryItem.query.get(int(inv_id))
                if not inv:
                    continue
                mi = MenuIngredient(
                    menu_id=current_menu.id,
                    inventory_id=inv.id,
                    quantity=_to_float(qty, 0.0),
                )
                db.session.add(mi)

            db.session.commit()
            return redirect(url_for("menu_builder"))

        return render_template(
            "menu_builder.html",
            inventory_items=inventory_items,
            menus=menus,
            editing=True,
            errors=[],
            current_menu=current_menu,
            values={
                "meal_type": current_menu.meal_type,
                "title": current_menu.title,
                "description": current_menu.description or "",
            },
        )

    @app.route("/menu/builder/<int:menu_id>/delete", methods=["POST"])
    @login_required
    def menu_builder_delete(menu_id):
        m = Menu.query.get_or_404(menu_id)
        MenuIngredient.query.filter_by(menu_id=m.id).delete()
        db.session.delete(m)
        db.session.commit()
        return redirect(url_for("menu_builder"))

    @app.route("/menu/scheduler")
    @login_required
    def menu_scheduler():
        return render_template("menu_scheduler.html")

    # seed a default manager if db empty
    @app.before_first_request
    def seed_user():
        if User.query.first():
            return
        m = User(
            username="manager",
            employee_id="00000000",
            email="manager@example.com",
            role="Manager",
        )
        m.set_password("1234")
        db.session.add(m)
        db.session.commit()

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
