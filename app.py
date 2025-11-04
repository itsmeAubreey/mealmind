# app.py — MealMind (working routes for your templates)
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


# ---------- helpers ----------
def _parse_date(s):
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _calc_age(bday):
    if not bday:
        return None
    today = date.today()
    return today.year - bday.year - ((today.month, today.day) < (bday.month, bday.day))


def _to_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


# ---------- app factory ----------
def create_app():
    app = Flask(__name__)

    # choose an Azure-safe sqlite path
    env_uri = os.getenv("SQLALCHEMY_DATABASE_URI") or os.getenv("DATABASE_URL")
    if env_uri and env_uri.startswith("sqlite:///"):
        db_path = env_uri.replace("sqlite:///", "")
        folder = os.path.dirname(db_path)
        if folder and not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)
        db_uri = env_uri
    else:
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

    # put age() in templates
    app.jinja_env.globals["age"] = _calc_age

    # ---------- context & decorators ----------
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
        return session.get("user", {}).get("role")

    # ---------- AUTH ----------
    @app.route("/")
    def home():
        if "user" in session:
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = (request.form.get("username") or "").strip().lower()
            password = (request.form.get("password") or "").strip()

            user = User.query.filter(
                or_(User.username.ilike(username), User.employee_id.ilike(username))
            ).first()

            stored = None
            if user:
                stored = getattr(user, "password_hash", None) or getattr(user, "password", None)

            ok = False
            if user and stored:
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

    # ---------- DASHBOARD ----------
    @app.route("/dashboard")
    @login_required
    def dashboard():
        user = session.get("user", {})
        return render_template("dashboard.html", user=user)

    # ---------- RESIDENTS ----------
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
                    Resident.illnesses.ilike(like),
                )
            )
        residents = query.order_by(Resident.last_name, Resident.first_name).all()
        return render_template("residents_list.html", residents=residents, q=q)

    @app.route("/residents/new", methods=["GET", "POST"])
    @login_required
    def residents_new():
        if current_role() not in ("Manager", "Dietitian"):
            flash("No access.", "error")
            return redirect(url_for("residents_list"))
        if request.method == "POST":
            first_name = (request.form.get("first_name") or "").strip()
            last_name = (request.form.get("last_name") or "").strip()
            birthday = _parse_date(request.form.get("birthday"))
            diet = (request.form.get("diet") or "").strip()
            allergies = (request.form.get("allergies") or "").strip()
            illnesses = (request.form.get("illnesses") or "").strip()
            meds = (request.form.get("medications") or "").strip()
            fluids = (request.form.get("fluids") or "").strip()
            notes = (request.form.get("notes") or "").strip()

            if not first_name or not last_name or not birthday:
                flash("First name, last name, and birthday are required.", "error")
                return render_template("residents_form.html", mode="new", values=request.form)

            r = Resident(
                first_name=first_name,
                last_name=last_name,
                birthday=birthday,
                diet=diet,
                allergies=allergies,
                illnesses=illnesses,
                medications=meds,
                fluids=fluids,
                notes=notes,
            )
            r.age = _calc_age(birthday)
            db.session.add(r)
            db.session.commit()
            return redirect(url_for("residents_list"))

        return render_template("residents_form.html", mode="new", values={})

    @app.route("/residents/<int:rid>/edit", methods=["GET", "POST"])
    @login_required
    def residents_edit(rid):
        if current_role() not in ("Manager", "Dietitian"):
            flash("No access.", "error")
            return redirect(url_for("residents_list"))
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
            if r.birthday:
                r.age = _calc_age(r.birthday)
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

    @app.route("/resident/<int:rid>/print")
    @login_required
    def resident_print(rid):
        r = Resident.query.get_or_404(rid)
        return render_template("resident_print.html", r=r)

    # ---------- STAFF ----------
    @app.route("/staff")
    @login_required
    def staff_list():
        if current_role() != "Manager":
            flash("No access.", "error")
            return redirect(url_for("dashboard"))
        users = User.query.order_by(User.last_name, User.first_name).all()
        return render_template("staff_list.html", users=users)

    # ---------- INVENTORY ----------
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
        if current_role() not in ("Manager", "Cook"):
            flash("No access.", "error")
            return redirect(url_for("inventory_list"))
        if request.method == "POST":
            name = (request.form.get("name") or "").strip()
            unit = (request.form.get("unit") or "").strip()
            qty = _to_float(request.form.get("quantity"), 0.0)
            low = _to_float(request.form.get("low_stock_threshold"), 0.0)
            if not name or unit not in INVENTORY_UNITS:
                flash("Name and valid unit required.", "error")
                return render_template("inventory_form.html", mode="new", values=request.form, units=INVENTORY_UNITS, limited=False)
            it = InventoryItem(name=name, unit=unit, quantity=qty, low_stock_threshold=low)
            db.session.add(it)
            db.session.commit()
            return redirect(url_for("inventory_list"))
        return render_template("inventory_form.html", mode="new", values={}, units=INVENTORY_UNITS, limited=False)

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

    # this is the one your inventory_list.html was calling
    @app.route("/inventory/<int:iid>/bump", methods=["POST"])
    @login_required
    def inventory_bump(iid):
        delta = _to_float(request.form.get("delta"), 0.0)
        it = InventoryItem.query.get_or_404(iid)
        it.quantity = (it.quantity or 0.0) + delta
        db.session.commit()
        # preserve filters
        q = request.args.get("q") or ""
        show = request.args.get("show") or "all"
        return redirect(url_for("inventory_list", q=q, show=show))

    # ---------- MENU ----------
    @app.route("/menu")
    @login_required
    def menu_hub():
        return render_template("menu_hub.html")

    # your menu_hub.html links to these, so give them routes
    @app.route("/menu/builder")
    @login_required
    def menu_builder():
        return render_template("menu_builder.html")

    @app.route("/menu/scheduler")
    @login_required
    def menu_scheduler():
        return render_template("menu_scheduler.html")

    @app.route("/menu/planned")
    @login_required
    def planned_menus():
        # your uploaded template name was planned_menu_week.html
        return render_template("planned_menu_week.html")

    # ---------- health ----------
    @app.route("/healthz")
    def healthz():
        return "ok", 200

    return app


# ---------- app entry ----------
app = create_app()
with app.app_context():
    # seed a manager if DB empty
    if not User.query.first():
        m = User(
            username="manager",
            employee_id="00000000",
            email="manager@example.com",
            role="Manager",
        )
        m.set_password("1234")
        db.session.add(m)
        db.session.commit()
        print("Seeded manager / 1234")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
