# app.py  (MealMind)
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
)
from datetime import datetime, date
import os

from models import (
    db,
    User,
    Resident,
    InventoryItem,
    Menu,
    MenuIngredient,
    MenuSchedule,
    MenuScheduleItem,
)  # :contentReference[oaicite:1]{index=1}

# -------------------------------------------------
# app setup
# -------------------------------------------------
app = Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY", "dev-secret")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "SQLALCHEMY_DATABASE_URI", "sqlite:///app.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


# -------------------------------------------------
# helpers
# -------------------------------------------------
def login_required(view_func):
    """very small login guard"""
    from functools import wraps

    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped


@app.context_processor
def inject_user():
    """so base.html can do {{ current_username }}"""
    u = session.get("user") or {}
    return {
        "current_user": u,  # keep for backward compat
        "current_username": u.get("username") or u.get("first_name") or "",
        "current_role": u.get("role", ""),
    }


# -------------------------------------------------
# auth
# -------------------------------------------------
@app.route("/", methods=["GET"])
def root():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    # show page
    if request.method == "GET":
        return render_template("login.html")

    # handle form
    username = (request.form.get("username") or "").strip().lower()
    password = (request.form.get("password") or "").strip()

    user = (
        User.query.filter(
            (User.username.ilike(username)) | (User.employee_id.ilike(username))
        )
        .first()
    )

    if not user or not user.check_password(password):
        flash("Invalid credentials.", "error")
        return render_template("login.html"), 401

    session["user"] = {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "role": user.role or "",
    }
    return redirect(url_for("dashboard"))


@app.route("/logout", methods=["GET"])
def logout():
    """simple logout that always works on GET"""
    session.clear()
    return redirect(url_for("login"))


# -------------------------------------------------
# dashboard
# -------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


# =================================================
# =============== RESIDENTS =======================
# =================================================
@app.route("/residents")
@login_required
def residents_list():
    q = (request.args.get("q") or "").strip()
    query = Resident.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Resident.first_name.ilike(like)) | (Resident.last_name.ilike(like))
        )
    residents = query.order_by(Resident.last_name, Resident.first_name).all()
    return render_template("residents_list.html", residents=residents, q=q)


@app.route("/residents/new", methods=["GET", "POST"])
@login_required
def resident_new():
    if request.method == "POST":
        return _save_resident()
    # empty form
    return render_template("residents_form.html", resident=None)


@app.route("/residents/<int:resident_id>/edit", methods=["GET", "POST"])
@login_required
def resident_edit(resident_id):
    resident = Resident.query.get_or_404(resident_id)

    if request.method == "POST":
        return _save_resident(resident)

    # render form pre-filled
    return render_template("residents_form.html", resident=resident)


def _save_resident(resident: Resident | None = None):
    """create or update in one place"""
    if resident is None:
        resident = Resident()

    resident.first_name = request.form.get("first_name") or ""
    resident.last_name = request.form.get("last_name") or ""
    # birthday may be empty
    bday_str = request.form.get("birthday") or ""
    if bday_str:
        try:
            resident.birthday = datetime.strptime(bday_str, "%Y-%m-%d").date()
        except ValueError:
            # try mm/dd/yyyy if browser sends that
            try:
                resident.birthday = datetime.strptime(bday_str, "%m/%d/%Y").date()
            except ValueError:
                resident.birthday = None
    else:
        resident.birthday = None
    resident.medications = request.form.get("medications") or ""
    resident.illnesses = request.form.get("illnesses") or ""
    resident.allergies = request.form.get("allergies") or ""
    resident.fluids = request.form.get("fluids") or ""
    resident.diet = request.form.get("diet") or ""
    resident.notes = request.form.get("notes") or ""

    db.session.add(resident)
    db.session.commit()
    return redirect(url_for("residents_list"))


@app.route("/resident/<int:resident_id>/print")
@login_required
def resident_print(resident_id):
    """your template uses {{ r.* }} so pass r=resident"""
    auto = request.args.get("auto") == "1"
    r = Resident.query.get_or_404(resident_id)
    return render_template("resident_print.html", r=r, auto=auto)


# =================================================
# =============== INVENTORY =======================
# =================================================
@app.route("/inventory")
@login_required
def inventory_list():
    items = InventoryItem.query.order_by(InventoryItem.name).all()
    return render_template("inventory_list.html", items=items)


@app.route("/inventory/new", methods=["GET", "POST"])
@login_required
def inventory_new():
    if request.method == "POST":
        return _save_inventory()
    return render_template("inventory_form.html", item=None)


@app.route("/inventory/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def inventory_edit(item_id):
    item = InventoryItem.query.get_or_404(item_id)
    if request.method == "POST":
        return _save_inventory(item)
    return render_template("inventory_form.html", item=item)


def _save_inventory(item: InventoryItem | None = None):
    if item is None:
        item = InventoryItem()
    item.name = request.form.get("name") or ""
    item.unit = request.form.get("unit") or "unit"
    qty_str = request.form.get("quantity") or "0"
    try:
        item.quantity = float(qty_str)
    except ValueError:
        item.quantity = 0
    low_str = request.form.get("low_stock_threshold") or "0"
    try:
        item.low_stock_threshold = float(low_str)
    except ValueError:
        item.low_stock_threshold = 0

    db.session.add(item)
    db.session.commit()
    return redirect(url_for("inventory_list"))


# =================================================
# =============== MENU HUB / BUILDER ==============
# =================================================
@app.route("/menu")
@login_required
def menu_hub():
    menus = Menu.query.order_by(Menu.meal_type, Menu.title).all()
    return render_template("menu_hub.html", menus=menus)


@app.route("/menu/builder", methods=["GET", "POST"])
@login_required
def menu_builder():
    # get inventory items for the dropdown
    inventory_items = InventoryItem.query.order_by(InventoryItem.name).all()

    if request.method == "POST":
        meal_type = request.form.get("meal_type") or "Breakfast"
        title = request.form.get("title") or "Untitled Menu"
        description = request.form.get("description") or ""

        menu = Menu(meal_type=meal_type, title=title, description=description)
        db.session.add(menu)
        db.session.flush()  # so we get menu.id

        # ingredients come as arrays
        ids = request.form.getlist("ingredient_id[]")
        qtys = request.form.getlist("ingredient_qty[]")
        units = request.form.getlist("ingredient_unit[]")

        for inv_id, qty, unit in zip(ids, qtys, units):
            if not inv_id:
                continue
            try:
                inv_id_int = int(inv_id)
            except ValueError:
                continue
            try:
                qty_val = float(qty)
            except ValueError:
                qty_val = 0
            mi = MenuIngredient(
                menu_id=menu.id,
                inventory_id=inv_id_int,
                quantity=qty_val,
                unit=unit,
            )
            db.session.add(mi)

        db.session.commit()
        return redirect(url_for("menu_hub"))

    # GET
    # group existing menus for right side
    all_menus = Menu.query.order_by(Menu.meal_type, Menu.title).all()
    menus_by_meal = {"Breakfast": [], "Lunch": [], "Dinner": []}
    for m in all_menus:
        menus_by_meal.setdefault(m.meal_type, []).append(m)

    return render_template(
        "menu_builder.html",
        inventory_items=inventory_items,
        menus_by_meal=menus_by_meal,
    )


# =================================================
# =============== MENU SCHEDULER ==================
# =================================================
@app.route("/menu/scheduler", methods=["GET", "POST"])
@login_required
def menu_scheduler():
    # all reusable menus
    all_menus = Menu.query.order_by(Menu.meal_type, Menu.title).all()
    menus_by_meal = {"Breakfast": [], "Lunch": [], "Dinner": []}
    for m in all_menus:
        menus_by_meal.setdefault(m.meal_type, []).append(m)

    # handle save
    if request.method == "POST":
        date_str = request.form.get("date") or ""
        meal_type = request.form.get("meal_type") or ""
        menu_id = request.form.get("menu_id") or ""
        notes = request.form.get("notes") or ""

        try:
            when = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            when = date.today()

        sched = MenuSchedule(date=when, meal_type=meal_type, notes=notes)
        if menu_id:
            try:
                sched.menu_id = int(menu_id)
            except ValueError:
                sched.menu_id = None

        db.session.add(sched)
        db.session.commit()
        flash("Menu scheduled.", "success")
        return redirect(url_for("menu_scheduler"))

    # GET: show today + upcoming
    today = date.today()
    upcoming = (
        MenuSchedule.query.filter(MenuSchedule.date >= today)
        .order_by(MenuSchedule.date.asc())
        .all()
    )
    return render_template(
        "menu_scheduler.html",
        menus_by_meal=menus_by_meal,
        today=today,
        upcoming=upcoming,
    )


# =================================================
# =============== STAFF (uses User) ===============
# =================================================
@app.route("/staff")
@login_required
def staff_list():
    staff = User.query.order_by(User.last_name, User.first_name).all()
    return render_template("staff_list.html", staff=staff)


@app.route("/staff/new", methods=["GET", "POST"])
@login_required
def staff_new():
    if request.method == "POST":
        return _save_staff()
    return render_template("staff_form.html", staff=None)


@app.route("/staff/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
def staff_edit(user_id):
    staff = User.query.get_or_404(user_id)
    if request.method == "POST":
        return _save_staff(staff)
    return render_template("staff_form.html", staff=staff)


def _save_staff(user: User | None = None):
    if user is None:
        user = User()
    user.first_name = request.form.get("first_name") or ""
    user.last_name = request.form.get("last_name") or ""
    user.username = request.form.get("username") or ""
    user.role = request.form.get("role") or "Dietary Aide"
    pw = request.form.get("password") or ""
    if pw:
        user.set_password(pw)
    db.session.add(user)
    db.session.commit()
    return redirect(url_for("staff_list"))


# =================================================
# =============== APP START (local) ===============
# =================================================
if __name__ == "__main__":
    # create tables if running locally
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5000, debug=True)
