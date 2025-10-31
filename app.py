# app.py — Full app with Menu Builder, Scheduler, Legacy daily page (/menu/legacy),
# Inventory, Residents, Staff, Dashboard, and strong pre-checks before deductions.
# Weekly grid FIX: days objects now include {"dow", "date"} to match planned_menu_week.html.

import os, io, csv
from functools import wraps
from datetime import datetime, timedelta, date
from collections import defaultdict

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, send_file, flash, jsonify
)
from flask_migrate import Migrate
from sqlalchemy import or_, func   # func used by CSV export filters

# models.py must be in the same folder
from models import (
    db, User, Resident, InventoryItem,
    # New menu system models
    Menu, MenuIngredient, MenuSchedule, MenuScheduleItem
)

# Optional .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


# -------------------------- helpers --------------------------
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
    t = date.today()
    return t.year - bday.year - ((t.month, t.day) < (bday.month, bday.day))

def _to_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default

def model_has_column(model, name):
    try:
        return hasattr(model, "__table__") and name in model.__table__.c.keys()
    except Exception:
        return False

def register_age_helper(app):
    app.jinja_env.globals["age"] = _calc_age

# ---- Role-based dashboard tiles (which big cards to show) ----
def dashboard_tiles_for(role: str):
    # Each tile: (label, href, color_key)
    # color_key is optional if you style by CSS classes in your template.
    manager = [
        ("Residents", url_for("residents_list"), "purple"),
        ("Inventory", url_for("inventory_list"), "green"),
        ("Menu", url_for("menu_hub"), "blue"),
        ("Staff", url_for("staff_list"), "red"),
    ]
    dietitian = [
        ("Residents", url_for("residents_list"), "purple"),
        ("Inventory", url_for("inventory_list"), "green"),
        ("Menu", url_for("menu_hub"), "blue"),
        # no Staff
    ]
    cook = [
        ("Residents", url_for("residents_list"), "purple"),
        ("Inventory", url_for("inventory_list"), "green"),
        ("Menu", url_for("menu_hub"), "blue"),
        # no Staff
    ]
    aide = [
        ("Residents", url_for("residents_list"), "purple"),
        ("Inventory", url_for("inventory_list"), "green"),
        # Menu → planned only; we’ll hide builder/scheduler inside menu hub template
        ("Menu", url_for("planned_menus"), "blue"),
        # no Staff
    ]
    mapping = {
        "Manager": manager,
        "Dietitian": dietitian,
        "Cook": cook,
        "Dietary Aide": aide,
    }
    return mapping.get(role or "", aide)



# -------------------------- factory --------------------------
def create_app():
    app = Flask(__name__)

    sqlite_uri = "sqlite:///" + os.path.join(os.getcwd(), "instance", "app.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", sqlite_uri)
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-key")
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True
    os.makedirs(os.path.join(os.getcwd(), "instance"), exist_ok=True)

    db.init_app(app)
    Migrate(app, db)
    register_age_helper(app)

    INVENTORY_UNITS = [
        "kg", "g", "bags", "cases", "dozen", "cans", "liters", "jugs",
        "bunches", "heads", "loaves", "packs", "bottles", "jars", "boxes", "pcs"
    ]
    ROLES = ["Manager", "Cook", "Dietitian", "Dietary Aide"]

    # Make `current_user` available in all templates
    @app.context_processor
    def inject_current_user():
        return {"current_user": session.get("user")}

    # ---------------- guards ----------------
    def login_required(f):
        @wraps(f)
        def w(*a, **kw):
            if "user" not in session:
                return redirect(url_for("login"))
            return f(*a, **kw)
        return w

    def current_role():
        return session.get("user", {}).get("role")

    def roles_required(*roles):
        def decorate(f):
            @wraps(f)
            def wrapped(*a, **kw):
                r = current_role()
                if r not in roles:
                    flash("You do not have access to that page.", "error")
                    return redirect(url_for("dashboard"))
                return f(*a, **kw)
            return wrapped
        return decorate

    @app.before_request
    def enforce_pw_change():
        allowed = {"login", "logout", "change_password", "static"}
        u = session.get("user")
        if not u:
            return
        obj = User.query.get(u["id"])
        if obj and getattr(obj, "must_change_password", False):
            if request.endpoint not in allowed:
                return redirect(url_for("change_password"))

    # ---------------- auth ----------------
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = (request.form.get("username") or "").strip().lower()
            password = (request.form.get("password") or "").strip()
            user = User.query.filter(
                or_(User.username.ilike(username), User.employee_id.ilike(username))
            ).first()
            if user and user.check_password(password):
                session["user"] = {
                    "id": user.id,
                    "username": user.username,
                    "role": user.role,
                    "first_name": getattr(user, "first_name", "") or "",
                    "last_name": getattr(user, "last_name", "") or "",
                }
                if getattr(user, "must_change_password", False):
                    return redirect(url_for("change_password"))
                return redirect(url_for("dashboard"))
            flash("Invalid credentials.", "error")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/change-password", methods=["GET", "POST"])
    def change_password():
        uinfo = session.get("user")
        if not uinfo:
            return redirect(url_for("login"))
        user = User.query.get_or_404(uinfo["id"])
        error = None
        if request.method == "POST":
            new = (request.form.get("new_password") or "")
            cfm = (request.form.get("confirm_password") or "")
            if new != cfm:
                error = "Passwords do not match."
            elif len(new) < 8:
                error = "Password must be at least 8 characters."
            else:
                user.set_password(new)
                user.must_change_password = False
                db.session.commit()
                flash("Password updated.", "success")
                return redirect(url_for("dashboard"))
        return render_template("change_password.html", error=error)

    # ---------------- home / dashboard ----------------
    @app.route("/")
    def home():
        return redirect(url_for("dashboard") if "user" in session else url_for("login"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        role = session.get("user", {}).get("role")
        tiles = dashboard_tiles_for(role)
        return render_template("dashboard.html", tiles=tiles)


    # ======================================================================
    # Residents
    # ======================================================================
    @app.route("/residents")
    @login_required
    def residents_list():
        q = (request.args.get("q") or "").strip()
        query = Resident.query
        if q:
            like = f"%{q}%"
            filters = []
            if hasattr(Resident, "first_name"):  filters.append(Resident.first_name.ilike(like))
            if hasattr(Resident, "last_name"):   filters.append(Resident.last_name.ilike(like))
            if hasattr(Resident, "diet"):        filters.append(Resident.diet.ilike(like))
            if hasattr(Resident, "allergies"):   filters.append(Resident.allergies.ilike(like))
            if hasattr(Resident, "illnesses"):   filters.append(Resident.illnesses.ilike(like))
            if hasattr(Resident, "medications"): filters.append(Resident.medications.ilike(like))
            if hasattr(Resident, "fluids"):      filters.append(Resident.fluids.ilike(like))
            if filters:
                query = query.filter(or_(*filters))
        residents = query.order_by(
            getattr(Resident, "last_name", Resident.id),
            getattr(Resident, "first_name", Resident.id),
        ).all()
        return render_template("residents_list.html", residents=residents, q=q)

    @app.route("/residents/new", methods=["GET", "POST"])
    @login_required
    @roles_required("Manager", "Dietitian")
    def residents_new():
        if request.method == "POST":
            first_name = (request.form.get("first_name") or "").strip()
            last_name  = (request.form.get("last_name") or "").strip()
            birthday   = _parse_date(request.form.get("birthday"))
            diet       = (request.form.get("diet") or "").strip()
            allergies  = (request.form.get("allergies") or "").strip()
            illnesses  = (request.form.get("illnesses") or "").strip()
            meds       = (request.form.get("medications") or "").strip()
            fluids     = (request.form.get("fluids") or "").strip()
            notes      = (request.form.get("notes") or "").strip()

            errors = []
            if not first_name: errors.append("First name is required.")
            if not last_name:  errors.append("Last name is required.")
            if not birthday:   errors.append("Birthday is required.")
            if errors:
                return render_template("residents_form.html", mode="new", values=request.form, errors=errors)

            r = Resident(
                first_name=first_name, last_name=last_name, birthday=birthday,
                diet=diet, allergies=allergies, illnesses=illnesses,
                medications=meds, fluids=fluids, notes=notes
            )
            if model_has_column(Resident, "age") and birthday:
                r.age = _calc_age(birthday)
            db.session.add(r)
            db.session.commit()
            flash("Resident created.", "success")
            return redirect(url_for("residents_list"))

        return render_template("residents_form.html", mode="new", values={})

    @app.route("/residents/<int:rid>/edit", methods=["GET", "POST"])
    @login_required
    @roles_required("Manager", "Dietitian")
    def residents_edit(rid):
        r = Resident.query.get_or_404(rid)
        if request.method == "POST":
            first_name = (request.form.get("first_name") or "").strip()
            last_name  = (request.form.get("last_name") or "").strip()
            birthday   = _parse_date(request.form.get("birthday"))
            diet       = (request.form.get("diet") or "").strip()
            allergies  = (request.form.get("allergies") or "").strip()
            illnesses  = (request.form.get("illnesses") or "").strip()
            meds       = (request.form.get("medications") or "").strip()
            fluids     = (request.form.get("fluids") or "").strip()
            notes      = (request.form.get("notes") or "").strip()

            errors = []
            if not first_name: errors.append("First name is required.")
            if not last_name:  errors.append("Last name is required.")
            if not birthday:   errors.append("Birthday is required.")
            if errors:
                return render_template("residents_form.html", mode="edit", values=request.form, rid=rid, errors=errors)

            r.first_name = first_name
            r.last_name  = last_name
            r.birthday   = birthday
            r.diet       = diet
            r.allergies  = allergies
            r.illnesses  = illnesses
            r.medications = meds
            r.fluids     = fluids
            r.notes      = notes

            if model_has_column(Resident, "age") and birthday:
                r.age = _calc_age(birthday)

            db.session.commit()
            flash("Resident updated.", "success")
            return redirect(url_for("residents_list"))

        values = {
            "first_name":  r.first_name or "",
            "last_name":   r.last_name or "",
            "birthday":    r.birthday.strftime("%Y-%m-%d") if r.birthday else "",
            "diet":        r.diet or "",
            "allergies":   r.allergies or "",
            "illnesses":   r.illnesses or "",
            "medications": r.medications or "",
            "fluids":      r.fluids or "",
            "notes":       r.notes or "",
        }
        return render_template("residents_form.html", mode="edit", values=values, rid=r.id)

    @app.route("/residents/<int:rid>/delete", methods=["POST"])
    @login_required
    @roles_required("Manager", "Dietitian")
    def residents_delete(rid):
        r = Resident.query.get_or_404(rid)
        db.session.delete(r)
        db.session.commit()
        flash("Resident deleted.", "success")
        return redirect(url_for("residents_list"))

    @app.route("/resident/<int:rid>/print")
    @login_required
    def resident_print(rid):
        r = Resident.query.get_or_404(rid)
        auto = bool(request.args.get("auto"))
        return render_template("resident_print.html", r=r, auto_print=auto)

    # ======================================================================
    # Staff (Manager only)
    # ======================================================================
    @app.route("/staff")
    @login_required
    @roles_required("Manager")
    def staff_list():
        q = (request.args.get("q") or "").strip()
        role_filter = (request.args.get("role") or "all").strip()
        query = User.query
        if role_filter != "all":
            query = query.filter(User.role == role_filter)
        if q:
            like = f"%{q}%"
            query = query.filter(or_(
                User.first_name.ilike(like),
                User.last_name.ilike(like),
                User.username.ilike(like),
                User.employee_id.ilike(like),
                User.email.ilike(like),
            ))
        users = query.order_by(User.last_name, User.first_name, User.username).all()
        return render_template("staff_list.html", users=users, roles=ROLES, role_filter=role_filter, q=q)

    @app.route("/staff/new", methods=["GET", "POST"])
    @login_required
    @roles_required("Manager")
    def staff_new():
        if request.method == "POST":
            first_name  = (request.form.get("first_name")  or "").strip()
            last_name   = (request.form.get("last_name")   or "").strip()
            username    = (request.form.get("username")    or "").strip().lower()
            employee_id = (request.form.get("employee_id") or "").strip()
            email       = (request.form.get("email")       or "").strip()
            role        = (request.form.get("role")        or "Dietary Aide").strip()
            temp_pw     = (request.form.get("temp_password") or "").strip()

            errors = []
            if not username:    errors.append("Username is required.")
            if not employee_id: errors.append("Employee ID is required.")
            if not temp_pw:     errors.append("Temporary password is required.")
            if User.query.filter(
                or_(User.username.ilike(username), User.employee_id.ilike(employee_id))
            ).first():
                errors.append("Username or Employee ID already exists.")

            if errors:
                return render_template("staff_form.html", mode="new", values=request.form, roles=ROLES, errors=errors)

            u = User(
                first_name=first_name, last_name=last_name, username=username,
                employee_id=employee_id, email=email, role=role, must_change_password=True,
            )
            u.set_password(temp_pw)
            db.session.add(u)
            db.session.commit()
            return redirect(url_for("staff_list"))

        return render_template("staff_form.html", mode="new", values={}, roles=ROLES)

    @app.route("/staff/<int:uid>/edit", methods=["GET", "POST"])
    @login_required
    @roles_required("Manager")
    def staff_edit(uid):
        u = User.query.get_or_404(uid)
        if request.method == "POST":
            first_name  = (request.form.get("first_name")  or "").strip()
            last_name   = (request.form.get("last_name")   or "").strip()
            username    = (request.form.get("username")    or "").strip().lower()
            employee_id = (request.form.get("employee_id") or "").strip()
            email       = (request.form.get("email")       or "").strip()
            role        = (request.form.get("role")        or "Dietary Aide").strip()

            errors = []
            if not username:    errors.append("Username is required.")
            if not employee_id: errors.append("Employee ID is required.")
            dup = User.query.filter(
                User.id != u.id,
                or_(User.username.ilike(username), User.employee_id.ilike(employee_id))
            ).first()
            if dup:
                errors.append("Another user already has that username or employee ID.")

            if errors:
                return render_template("staff_form.html", mode="edit", values=request.form, roles=ROLES, errors=errors, user_id=u.id)

            u.first_name  = first_name
            u.last_name   = last_name
            u.username    = username
            u.employee_id = employee_id
            u.email       = email
            u.role        = role
            db.session.commit()
            return redirect(url_for("staff_list"))

        values = {
            "first_name":  u.first_name  or "",
            "last_name":   u.last_name   or "",
            "username":    u.username    or "",
            "employee_id": u.employee_id or "",
            "email":       u.email       or "",
            "role":        u.role        or "Dietary Aide",
        }
        return render_template("staff_form.html", mode="edit", values=values, roles=ROLES, user_id=u.id)

    @app.route("/staff/<int:uid>/delete", methods=["POST"])
    @login_required
    @roles_required("Manager")
    def staff_delete(uid):
        u = User.query.get_or_404(uid)
        if session.get("user", {}).get("id") == u.id:
            flash("You cannot delete your own account.", "error")
            return redirect(url_for("staff_list"))
        db.session.delete(u)
        db.session.commit()
        return redirect(url_for("staff_list"))

    # ======================================================================
    # Inventory
    # ======================================================================
    @app.route("/inventory")
    @login_required
    @roles_required("Manager", "Cook", "Dietary Aide")
    def inventory_list():
        q = (request.args.get("q") or "").strip()
        show = (request.args.get("show") or "all").strip()
        query = InventoryItem.query
        if q:
            query = query.filter(InventoryItem.name.ilike(f"%{q}%"))
        rows = query.order_by(InventoryItem.name).all()
        items = []
        for obj in rows:
            qty = obj.quantity or 0.0
            low = obj.low_stock_threshold or 0.0
            is_low = (qty <= low) if (obj.low_stock_threshold is not None) else False
            items.append({"obj": obj, "is_low": is_low})
        if show == "low":
            items = [x for x in items if x["is_low"]]
        return render_template("inventory_list.html", items=items, q=q, show=show)

    @app.route("/inventory/new", methods=["GET", "POST"])
    @login_required
    @roles_required("Manager", "Cook")
    def inventory_new():
        if request.method == "POST":
            name = (request.form.get("name") or "").strip()
            unit = (request.form.get("unit") or "").strip()
            qty  = _to_float(request.form.get("quantity"), 0.0)
            low  = _to_float(request.form.get("low_stock_threshold"), 0.0)

            errors = []
            if not name: errors.append("Item name is required.")
            if unit not in INVENTORY_UNITS: errors.append("Select a valid unit.")
            if InventoryItem.query.filter(
                InventoryItem.name.ilike(name), InventoryItem.unit.ilike(unit)
            ).first():
                errors.append("That item (name & unit) already exists.")

            if errors:
                return render_template("inventory_form.html", mode="new", values=request.form,
                                       units=INVENTORY_UNITS, errors=errors, limited=False)

            it = InventoryItem(name=name, unit=unit, quantity=qty, low_stock_threshold=low)
            db.session.add(it)
            db.session.commit()
            return redirect(url_for("inventory_list"))

        return render_template("inventory_form.html", mode="new", values={}, units=INVENTORY_UNITS, limited=False)

    @app.route("/inventory/<int:iid>/edit", methods=["GET", "POST"])
    @login_required
    @roles_required("Manager", "Cook", "Dietary Aide")
    def inventory_edit(iid):
        it = InventoryItem.query.get_or_404(iid)
        limited = (current_role() == "Dietary Aide")

        if request.method == "POST":
            qty  = _to_float(request.form.get("quantity"), 0.0)

            if limited:
                it.quantity = qty
                db.session.commit()
                flash("Quantity updated.", "success")
                return redirect(url_for("inventory_list"))

            name = (request.form.get("name") or "").strip()
            unit = (request.form.get("unit") or "").strip()
            low  = _to_float(request.form.get("low_stock_threshold"), 0.0)

            errors = []
            if not name: errors.append("Item name is required.")
            if unit not in INVENTORY_UNITS: errors.append("Select a valid unit.")
            dup = InventoryItem.query.filter(
                InventoryItem.id != it.id,
                InventoryItem.name.ilike(name),
                InventoryItem.unit.ilike(unit)
            ).first()
            if dup:
                errors.append("Another item with that name & unit exists.")

            if errors:
                return render_template("inventory_form.html", mode="edit", values=request.form,
                                       item_id=it.id, units=INVENTORY_UNITS, errors=errors, limited=limited)

            it.name, it.unit, it.quantity, it.low_stock_threshold = name, unit, qty, low
            db.session.commit()
            return redirect(url_for("inventory_list"))

        return render_template("inventory_form.html", mode="edit", values=it, item_id=it.id,
                               units=INVENTORY_UNITS, limited=limited)

    @app.route("/inventory/<int:iid>/delete", methods=["POST"])
    @login_required
    @roles_required("Manager", "Cook")
    def inventory_delete(iid):
        it = InventoryItem.query.get_or_404(iid)
        db.session.delete(it)
        db.session.commit()
        return redirect(url_for("inventory_list"))

    @app.route("/inventory/export")
    @app.route("/inventory/export.csv")
    @login_required
    def inventory_export():
        """
        Export Inventory as CSV, honoring current filters.
        Supported query params:
        - q: search term
        - status: 'low' | 'ok' | 'all'  (default 'all')
        """
        q = (request.args.get("q") or "").strip()
        status = (request.args.get("status") or "all").lower()

        qry = InventoryItem.query

        if q:
            qry = qry.filter(InventoryItem.name.ilike(f"%{q}%"))

        if status == "low":
            qry = qry.filter(
                func.coalesce(InventoryItem.quantity, 0) <= func.coalesce(InventoryItem.low_stock_threshold, 0)
            )
        elif status == "ok":
            qry = qry.filter(
                func.coalesce(InventoryItem.quantity, 0) > func.coalesce(InventoryItem.low_stock_threshold, 0)
            )

        items = qry.order_by(InventoryItem.name.asc()).all()

        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["Item", "Unit", "Quantity", "Low Stock Threshold", "Status"])

        for it in items:
            qty = float(it.quantity or 0)
            thr = float(it.low_stock_threshold or 0)
            status_label = "LOW" if qty <= thr else "OK"
            w.writerow([it.name, it.unit, qty, thr, status_label])

        mem = io.BytesIO(out.getvalue().encode("utf-8-sig"))
        mem.seek(0)
        filename = f"inventory_{status or 'all'}.csv"
        return send_file(mem, mimetype="text/csv", as_attachment=True, download_name=filename)
    
    @app.route("/inventory/<int:iid>/bump", methods=["POST"])
    @login_required
    @roles_required("Manager", "Cook", "Dietary Aide")
    def inventory_bump(iid):
        item = InventoryItem.query.get_or_404(iid)
        # Aide can only adjust quantity; Managers/Cooks also have full edit elsewhere
        try:
            delta = float(request.form.get("delta", "0"))
        except Exception:
            delta = 0.0
        item.quantity = (item.quantity or 0.0) + delta
        db.session.commit()
        # stay on same listing with prior filters if present
        return redirect(url_for("inventory_list", q=request.args.get("q", ""), show=request.args.get("show", "all")))


    # ======================================================================
    # Legacy One-Day Menu page  → now served at /menu/legacy
    # ======================================================================
    @app.route("/menu/legacy", methods=["GET", "POST"])
    @login_required
    def menu_legacy():
        """Shows (and lets Manager save) a one-day menu. Cook/Manager can apply to deduct inventory."""
        try:
            from models import MenuEntry, MenuIngredient as LegacyMenuIngredient
        except Exception:
            MenuEntry = LegacyMenuIngredient = None

        day_str = request.args.get("day") or date.today().strftime("%Y-%m-%d")
        day = _parse_date(day_str) or date.today()

        role = session.get("user", {}).get("role")
        can_edit = role in ("Manager",)
        can_apply = role in ("Manager", "Cook")

        entries = {}
        if MenuEntry:
            entries = {e.meal_type: e for e in MenuEntry.query.filter_by(day=day).all()}

        if request.method == "POST" and can_edit and MenuEntry and LegacyMenuIngredient:
            def _parse_menu_ingredients(lines):
                out = []
                for raw in (lines or "").splitlines():
                    line = raw.strip()
                    if not line:
                        continue
                    if ":" in line:
                        name, rest = line.split(":", 1)
                        name = name.strip()
                        rest = rest.strip()
                        parts = rest.split()
                        qty = 0.0
                        unit = ""
                        if parts:
                            try:
                                qty = float(parts[0])
                                unit = parts[1] if len(parts) > 1 else ""
                            except Exception:
                                unit = " ".join(parts)
                        out.append({"name": name, "quantity": qty, "unit": unit})
                    else:
                        parts = line.split()
                        if len(parts) >= 3:
                            try:
                                qty = float(parts[0]); unit = parts[1]; name = " ".join(parts[2:])
                                out.append({"name": name, "quantity": qty, "unit": unit}); continue
                            except Exception:
                                pass
                        out.append({"name": line, "quantity": 0.0, "unit": ""})
                return out

            for meal in ["Breakfast", "Lunch", "Dinner"]:
                title = (request.form.get(f"{meal}_title") or "").strip()
                descr = (request.form.get(f"{meal}_descr") or "").strip()
                lines = (request.form.get(f"{meal}_ingredients") or "").strip()

                entry = entries.get(meal)
                if not entry:
                    entry = MenuEntry(day=day, meal_type=meal, title=title, description=descr)
                    db.session.add(entry)
                    db.session.flush()
                    entries[meal] = entry
                else:
                    entry.title = title
                    entry.description = descr
                    if getattr(entry, "ingredients", None) is not None:
                        entry.ingredients.clear()

                for ing in _parse_menu_ingredients(lines):
                    qty = 0.0
                    try:
                        qty = float(ing.get("quantity", 0) or 0)
                    except Exception:
                        qty = 0.0
                    entry.ingredients.append(
                        LegacyMenuIngredient(
                            name=ing.get("name", "").strip(),
                            quantity=qty,
                            unit=(ing.get("unit", "") or "").strip()
                        )
                    )
            db.session.commit()
            flash("Menu saved.", "success")
            return redirect(url_for("menu_legacy", day=day.strftime("%Y-%m-%d")))

        def lines_for(entry):
            if not entry or not getattr(entry, "ingredients", None):
                return ""
            return "\n".join(f"{i.name}: {i.quantity:g} {i.unit}".rstrip() for i in entry.ingredients)

        ctx = {
            "day": day,
            "can_edit": can_edit,
            "can_apply": can_apply,
            "Breakfast": entries.get("Breakfast") if entries else None,
            "Lunch": entries.get("Lunch") if entries else None,
            "Dinner": entries.get("Dinner") if entries else None,
            "Breakfast_lines": lines_for(entries.get("Breakfast")) if entries else "",
            "Lunch_lines": lines_for(entries.get("Lunch")) if entries else "",
            "Dinner_lines": lines_for(entries.get("Dinner")) if entries else "",
        }
        try:
            return render_template("menu.html", **ctx)
        except Exception:
            return f"<h3>Menu for {day:%Y-%m-%d}</h3>", 200

    # ======================================================================
    # Menu Hub, Builder, API, Scheduler & Daily browser
    # ======================================================================
    @app.route("/menu")
    @login_required
    def menu_hub():
        return render_template("menu_hub.html")

    # ---- Builder ----------------------------------------------------------
    @app.route("/menu/builder", methods=["GET", "POST"])
    @login_required
    @roles_required("Manager", "Dietitian")
    def menu_builder():
        inventory_items = InventoryItem.query.order_by(InventoryItem.name.asc()).all()
        errors, values = [], {}

        if request.method == "POST":
            meal_type   = (request.form.get("meal_type") or "").strip()
            title       = (request.form.get("title") or "").strip()
            description = (request.form.get("description") or "").strip()
            ids  = request.form.getlist("ingredient_id")
            qtys = request.form.getlist("quantity")

            if meal_type not in ("Breakfast", "Lunch", "Dinner"):
                errors.append("Select a valid meal type.")
            if not title:
                errors.append("Menu title is required.")
            if not ids:
                errors.append("Add at least one ingredient.")

            if errors:
                menus = Menu.query.order_by(Menu.meal_type.asc(), Menu.title.asc()).all()
                values = {"meal_type": meal_type, "title": title, "description": description}
                return render_template(
                    "menu_builder.html",
                    inventory_items=inventory_items,
                    menus=menus,
                    errors=errors,
                    values=values,
                    editing=False,
                )

            m = Menu(meal_type=meal_type, title=title, description=description)
            db.session.add(m)
            db.session.flush()

            for inv_id, qty in zip(ids, qtys):
                if not inv_id or not qty:
                    continue
                inv = InventoryItem.query.get(int(inv_id))
                if not inv:
                    continue
                q = _to_float(qty, 0.0)
                m.ingredients.append(MenuIngredient(inventory_id=inv.id, quantity=q))

            db.session.commit()
            flash(f'Menu "{m.title}" added.', "success")
            return redirect(url_for("menu_builder"))

        menus = Menu.query.order_by(Menu.meal_type.asc(), Menu.title.asc()).all()
        return render_template(
            "menu_builder.html",
            inventory_items=inventory_items,
            menus=menus,
            errors=errors,
            values=values,
            editing=False,
        )

    @app.route("/menu/builder/<int:menu_id>/edit", methods=["GET", "POST"])
    @login_required
    @roles_required("Manager", "Dietitian")
    def menu_builder_edit(menu_id: int):
        m = Menu.query.get_or_404(menu_id)
        inventory_items = InventoryItem.query.order_by(InventoryItem.name.asc()).all()
        errors, values = [], {}

        if request.method == "POST":
            meal_type = request.form.get("meal_type") or m.meal_type
            title     = (request.form.get("title") or "").strip()
            descr     = (request.form.get("description") or "").strip()

            if meal_type not in ("Breakfast", "Lunch", "Dinner"):
                errors.append("Please choose a valid meal type.")
            if not title:
                errors.append("Menu title is required.")

            ids  = request.form.getlist("ingredient_id")
            qtys = request.form.getlist("quantity")

            if not errors:
                m.meal_type = meal_type
                m.title = title
                m.description = descr

                m.ingredients.clear()
                for inv_id, qty in zip(ids, qtys):
                    if not inv_id or not qty:
                        continue
                    inv = InventoryItem.query.get(int(inv_id))
                    if not inv:
                        continue
                    q = _to_float(qty, 0.0)
                    m.ingredients.append(MenuIngredient(inventory_id=inv.id, quantity=q))

                db.session.commit()
                flash(f'Menu "{m.title}" updated.', "success")
                return redirect(url_for("menu_builder"))

            values = {"title": title, "description": descr}

        return render_template(
            "menu_builder.html",
            inventory_items=inventory_items,
            menus=[],
            errors=errors,
            values=values,
            editing=True,
            current_menu=m
        )

    @app.route("/menu/builder/<int:menu_id>/delete", methods=["POST"])
    @login_required
    @roles_required("Manager", "Dietitian")
    def menu_builder_delete(menu_id: int):
        m = Menu.query.get_or_404(menu_id)
        title = m.title
        db.session.delete(m)
        db.session.commit()
        flash(f'Menu "{title}" deleted.', "success")
        return redirect(url_for("menu_builder"))

    @app.route("/api/menu/<int:menu_id>/items")
    @login_required
    def api_menu_items(menu_id):
        """Return a menu's items for dynamic fill in the scheduler."""
        m = Menu.query.get_or_404(menu_id)
        items = []
        for ing in m.ingredients:
            inv = InventoryItem.query.get(ing.inventory_id)
            items.append({
                "id": ing.id,
                "inventory_id": ing.inventory_id,
                "name": inv.name if inv else "",
                "quantity": ing.quantity,
                "unit": (inv.unit if inv else "")
            })
        return jsonify({"menu_id": m.id, "meal_type": m.meal_type, "title": m.title, "items": items})

    # ---- Scheduler --------------------------------------------------------
    @app.route("/menu/scheduler", methods=["GET", "POST"])
    @login_required
    @roles_required("Manager", "Cook", "Dietitian")
    def menu_scheduler():
        menus = Menu.query.order_by(Menu.meal_type, Menu.title).all()
        inventory_items = InventoryItem.query.order_by(InventoryItem.name).all()

        if request.method == "POST":
            selected_date = _parse_date(request.form.get("date")) or date.today()
            notes = (request.form.get("notes") or "").strip()

            # Collect chosen menus and per-ingredient overrides
            chosen = {}
            for meal_type in ["Breakfast", "Lunch", "Dinner"]:
                mid = request.form.get(f"{meal_type}_menu")
                if mid:
                    chosen[meal_type] = int(mid)

            if not chosen:
                flash("No menus selected; nothing saved.", "error")
                return redirect(url_for("menu_scheduler"))

            # 1) Pre-check: aggregate by inventory_id across all meals
            need_map = {}
            name_map = {}
            for meal_type, mid in chosen.items():
                base_menu = Menu.query.get(mid)
                for ing in base_menu.ingredients:
                    override_key = f"{meal_type}_qty_{ing.id}"
                    use_qty = _to_float(request.form.get(override_key), ing.quantity)
                    inv = InventoryItem.query.get(ing.inventory_id)
                    if not inv:
                        flash(f"Inventory item missing for a menu ingredient in {meal_type}.", "error")
                        return redirect(url_for("menu_scheduler"))
                    need_map[inv.id] = need_map.get(inv.id, 0.0) + (use_qty or 0.0)
                    name_map[inv.id] = (inv.name, inv.unit)

            insuff = []
            for inv_id, need in need_map.items():
                inv = InventoryItem.query.get(inv_id)
                have = inv.quantity or 0.0
                if have < need:
                    nm, un = name_map[inv_id]
                    insuff.append(f"{nm} needs {need:g}{un} (have {have:g})")

            if insuff:
                flash("Not saved. Issues: " + "; ".join(insuff), "error")
                return redirect(url_for("menu_scheduler"))

            # 2) Replace any existing schedule (same date + meal)
            deductions = []
            for meal_type, mid in chosen.items():
                MenuSchedule.query.filter_by(date=selected_date, meal_type=meal_type).delete(synchronize_session=False)

                sched = MenuSchedule(date=selected_date, meal_type=meal_type, menu_id=mid, notes=notes)
                db.session.add(sched)
                db.session.flush()

                base_menu = Menu.query.get(mid)
                for ing in base_menu.ingredients:
                    override_key = f"{meal_type}_qty_{ing.id}"
                    use_qty = _to_float(request.form.get(override_key), ing.quantity)
                    db.session.add(MenuScheduleItem(
                        schedule_id=sched.id,
                        inventory_id=ing.inventory_id,
                        quantity_used=use_qty
                    ))
                    inv = InventoryItem.query.get(ing.inventory_id)
                    inv.quantity = (inv.quantity or 0.0) - (use_qty or 0.0)
                    deductions.append(f"{inv.name} -{use_qty:g} {inv.unit}")

            db.session.commit()
            flash("Deducted: " + ", ".join(deductions[:8]) + (" ..." if len(deductions) > 8 else ""), "success")
            return redirect(url_for("menu_scheduler"))

        # GET
        day_str = request.args.get("date")
        selected_date = _parse_date(day_str) or date.today()
        existing = MenuSchedule.query.filter_by(date=selected_date).order_by(MenuSchedule.meal_type).all()

        by_meal = {"Breakfast": [], "Lunch": [], "Dinner": []}
        for m in menus:
            by_meal.get(m.meal_type, []).append(m)

        return render_template(
            "menu_scheduler.html",
            date_value=selected_date.strftime("%Y-%m-%d"),
            menus_by_meal=by_meal,
            inventory_items=inventory_items,
            existing=existing,
            suppress_global_flash=True
        )

    # ----- Planned Menus (weekly viewer) --------------------------------------
    @app.route("/menu/planned")
    @login_required
    def planned_menus():
        # offset handling
        try:
            offset = int(request.args.get("offset", 0))
        except Exception:
            offset = 0

        today = date.today()
        current_monday = today - timedelta(days=today.weekday())
        week_start = current_monday + timedelta(weeks=offset)
        week_end = week_start + timedelta(days=6)

        # FIX: days need {'dow','date'} (template expects d.dow and d.date)
        dows = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        days = [{"dow": dows[i], "date": (week_start + timedelta(days=i))} for i in range(7)]

        schedules = (
            MenuSchedule.query
            .filter(MenuSchedule.date >= week_start,
                    MenuSchedule.date <= week_end)
            .order_by(MenuSchedule.date.asc(), MenuSchedule.meal_type.asc())
            .all()
        )

        # grouped: { date: { meal_type: [ {id, menu_title} ] } }
        grouped = defaultdict(lambda: defaultdict(list))
        # preload titles to minimize queries
        menu_title_cache = {}
        def menu_title(mid):
            if mid in menu_title_cache:
                return menu_title_cache[mid]
            m = Menu.query.get(mid) if mid else None
            title = m.title if m else "(untitled)"
            menu_title_cache[mid] = title
            return title

        for s in schedules:
            grouped[s.date][s.meal_type].append({
                "id": s.id,
                "menu_title": menu_title(s.menu_id)
            })

        prev_url = url_for("planned_menus", offset=offset-1)
        next_url = url_for("planned_menus", offset=offset+1)

        return render_template(
            "planned_menu_week.html",
            grouped=grouped,
            week_start=week_start,
            week_end=week_end,
            days=days,
            prev_url=prev_url,
            next_url=next_url,
            offset=offset
        )

    @app.route("/menu/plan/<int:schedule_id>/delete")
    @login_required
    def delete_schedule(schedule_id):
        nxt = request.args.get("next") or url_for("planned_menus")
        s = MenuSchedule.query.get_or_404(schedule_id)
        db.session.delete(s)
        db.session.commit()
        flash("Scheduled menu removed.", "success")
        return redirect(nxt)

    @app.route("/menu/planned/<string:day_str>")
    @login_required
    def planned_menu_view(day_str):
        d = _parse_date(day_str)
        if not d:
            flash("Invalid date.", "error")
            return redirect(url_for("planned_menus"))

        schedules = (MenuSchedule.query
                    .filter_by(date=d)
                    .order_by(MenuSchedule.meal_type.asc())
                    .all())

        order = {"Breakfast": 0, "Lunch": 1, "Dinner": 2}
        schedules = sorted(schedules, key=lambda s: order.get(s.meal_type, 99))

        detail = []
        for s in schedules:
            rows = (MenuScheduleItem.query
                    .filter_by(schedule_id=s.id)
                    .order_by(MenuScheduleItem.id.asc())
                    .all())
            items = []
            for r in rows:
                inv = InventoryItem.query.get(r.inventory_id)
                items.append({
                    "name": inv.name if inv else "(deleted item)",
                    "unit": inv.unit if inv else "",
                    "qty":  r.quantity_used or 0.0
                })

            title = "(untitled)"
            if getattr(s, "menu_id", None):
                mm = Menu.query.get(s.menu_id)
                if mm:
                    title = mm.title

            detail.append({
                "meal": s.meal_type,
                "notes": getattr(s, "notes", None),
                "menu_title": title,
                "items": items,
            })

        return render_template("planned_menu_view.html", day_value=d, blocks=detail)

    # ---- Daily browser for legacy per-day saved menus ---------------------
    @app.route("/menu/daily")
    @login_required
    def menu_daily():
        from models import MenuEntry
        start = _parse_date(request.args.get("start"))
        end   = _parse_date(request.args.get("end"))

        q = MenuEntry.query
        if start: q = q.filter(MenuEntry.day >= start)
        if end:   q = q.filter(MenuEntry.day <= end)

        q = q.order_by(MenuEntry.day.desc(), MenuEntry.meal_type.asc())
        rows = q.all()

        days = {}
        for e in rows:
            days.setdefault(e.day, []).append(e)
        for d in days:
            days[d].sort(key=lambda x: {"Breakfast":0,"Lunch":1,"Dinner":2}.get(x.meal_type, 99))

        return render_template("menu_daily.html", days=days, start=start, end=end)

    @app.route("/menu/daily/<string:day_str>")
    @login_required
    def menu_daily_view(day_str):
        from models import MenuEntry
        d = _parse_date(day_str)
        if not d:
            flash("Invalid date.", "error")
            return redirect(url_for("menu_daily"))

        rows = MenuEntry.query.filter_by(day=d).order_by(MenuEntry.meal_type.asc()).all()
        return render_template("menu_daily_view.html", day=d, entries=rows)

    @app.route("/menu/daily/<string:day_str>/delete", methods=["POST"])
    @login_required
    @roles_required("Manager")
    def menu_daily_delete(day_str):
        from models import MenuEntry
        d = _parse_date(day_str)
        if not d:
            flash("Invalid date.", "error")
            return redirect(url_for("menu_daily"))
        MenuEntry.query.filter_by(day=d).delete()
        db.session.commit()
        flash(f"Deleted daily menu for {d}.", "success")
        return redirect(url_for("menu_daily"))

    # ---------------- end of routes ----------------
    return app


# -------------------------- dev entrypoint --------------------------
if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="manager").first():
            mgr = User(
                first_name="",
                last_name="",
                username="manager",
                employee_id="00000000",
                email="manager@example.com",
                role="Manager",
                must_change_password=False,
            )
            mgr.set_password("1234")
            db.session.add(mgr)
            db.session.commit()
            print("Seeded manager (manager / 1234)")
    app.run(debug=True)
