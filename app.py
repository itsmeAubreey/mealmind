import os
import csv
from io import StringIO
from datetime import datetime, date, timedelta
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    Response,
    jsonify,
)
from sqlalchemy import or_

# use the actual filename in your repo
from models import (
    db,
    User,
    Resident,
    InventoryItem,
    Menu,
    MenuIngredient,
    MenuSchedule,
    MenuScheduleItem,
)


# ---------- small helpers ----------
def _parse_date(s: str):
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _to_float(val, default=0.0):
    try:
        return float(val)
    except Exception:
        return default


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-key")

    # ---------- DB CONFIG (do this BEFORE db.init_app) ----------
    db_uri = os.getenv("SQLALCHEMY_DATABASE_URI")
    if not db_uri:
        # Azure persistent path
        azure_data = "/home/site/data"
        if os.path.exists(azure_data):
            db_uri = "sqlite:///" + os.path.join(azure_data, "app.db")
        else:
            db_uri = "sqlite:///mealmind.db"

    app.config["SQLALCHEMY_DATABASE_URI"] = db_uri
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # now init once
    db.init_app(app)

    # create tables and seed manager
    with app.app_context():
        db.create_all()
        if not User.query.first():
            u = User(
                username="manager",
                employee_id="00000000",
                email="manager@example.com",
                role="Manager",
            )
            u.set_password("1234")
            db.session.add(u)
            db.session.commit()

    # ---------- make {{ age(...) }} available to all templates ----------
    def age_from_date(d):
        if not d:
            return ""
        if isinstance(d, str):
            try:
                d = datetime.strptime(d, "%Y-%m-%d").date()
            except Exception:
                return ""
        today = date.today()
        years = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
        return years

    @app.context_processor
    def inject_helpers():
        u = session.get("user")
        return {"age": age_from_date, "current_user": u, "user": u}

    # ---------------- optional Azure OpenAI chat ----------------
    @app.route("/chat", methods=["POST"])
    @login_required
    def chat():
        # tiny API endpoint called by the floating widget
        try:
            import requests
        except ImportError:
            return jsonify({"reply": "Server: 'requests' package not installed."}), 500

        data = request.get_json(force=True) or {}
        user_message = (data.get("message") or "").strip()
        if not user_message:
            return jsonify({"reply": "Please type something."})

        # use the env vars you already showed in Azure
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv(
            "AZURE_OPENAI_ENDPOINT".lower()
        )
        api_key = (
            os.getenv("AZURE_OPENAI_API_KEY")
            or os.getenv("AZURE_OPENAI_KEY")
            or os.getenv("AZURE_OPENAI_KEY".lower())
        )
        deployment = (
            os.getenv("AZURE_OPENAI_DEPLOYMENT")
            or os.getenv("AZURE_OPENAI_MODEL")
            or "mealmind-chat"
        )
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

        if not endpoint or not api_key:
            return jsonify({"reply": "Azure OpenAI is not configured on the server."}), 500

        if not endpoint.endswith("/"):
            endpoint = endpoint + "/"

        url = f"{endpoint}openai/deployments/{deployment}/chat/completions?api-version={api_version}"
        headers = {"Content-Type": "application/json", "api-key": api_key}
        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": "You are MealMind, a friendly helper for a kitchen / dietary management app.",
                },
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.6,
            "max_tokens": 250,
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=15)
            resp.raise_for_status()
            body = resp.json()
            reply = body["choices"][0]["message"]["content"]
            return jsonify({"reply": reply})
        except Exception:
            # don’t crash the UI if Azure is unreachable
            return (
                jsonify(
                    {
                        "reply": "I couldn't reach Azure OpenAI right now, but the button is wired correctly."
                    }
                ),
                500,
            )

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

            ok = False
            if user:
                try:
                    ok = user.check_password(password)
                except Exception:
                    ok = user.password == password

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

    # ---------- AUTH ----------
    @app.route("/logout")
    @login_required
    def logout():
        # you only store the user in the session, so just clear it
        session.clear()
        # send them back to login
        return redirect(url_for("login"))

    # ---------- DASHBOARD ----------
    @app.route("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html")

    # ---------- RESIDENTS ----------
    @app.route("/residents")
    @login_required
    def residents_list():
        q = request.args.get("q", "").strip()
        query = Resident.query
        if q:
            like = f"%{q}%"
            query = query.filter(
                db.or_(
                    Resident.first_name.ilike(like),
                    Resident.last_name.ilike(like),
                    Resident.diet.ilike(like),
                    Resident.allergies.ilike(like),
                )
            )
        residents = query.order_by(Resident.last_name, Resident.first_name).all()
        return render_template("residents_list.html", residents=residents)

    @app.route("/residents/new", methods=["GET", "POST"])
    @login_required
    def residents_new():
        if request.method == "POST":
            r = Resident(
                first_name=request.form.get("first_name") or "",
                last_name=request.form.get("last_name") or "",
                birthday=_parse_date(request.form.get("birthday")),
                medications=request.form.get("medications") or "",
                illnesses=request.form.get("illnesses") or "",
                allergies=request.form.get("allergies") or "",
                fluids=request.form.get("fluids") or "",
                diet=request.form.get("diet") or "",
                notes=request.form.get("notes") or "",
            )
            db.session.add(r)
            db.session.commit()
            return redirect(url_for("residents_list"))

        return render_template(
            "residents_form.html",
            mode="new",
            values=None,
            rid=None,
        )

    @app.route("/residents/<int:rid>/edit", methods=["GET", "POST"])
    @login_required
    def residents_edit(rid):
        r = Resident.query.get_or_404(rid)
        if request.method == "POST":
            r.first_name = request.form.get("first_name") or ""
            r.last_name = request.form.get("last_name") or ""
            r.birthday = _parse_date(request.form.get("birthday"))
            r.medications = request.form.get("medications") or ""
            r.illnesses = request.form.get("illnesses") or ""
            r.allergies = request.form.get("allergies") or ""
            r.fluids = request.form.get("fluids") or ""
            r.diet = request.form.get("diet") or ""
            r.notes = request.form.get("notes") or ""
            db.session.commit()
            return redirect(url_for("residents_list"))

        # pass what the template expects
        return render_template(
            "residents_form.html",
            mode="edit",
            values=r,
            rid=r.id,
        )

    @app.route("/residents/<int:rid>/delete", methods=["POST"])
    @login_required
    def residents_delete(rid):
        r = Resident.query.get_or_404(rid)
        db.session.delete(r)
        db.session.commit()
        return redirect(url_for("residents_list"))

    @app.route("/resident/<int:rid>/print")
    @login_required
    def resident_print(rid):
        r = Resident.query.get_or_404(rid)
        auto = request.args.get("auto")
        # template was using "r", but route was only sending "resident"
        return render_template(
            "resident_print.html",
            resident=r,
            r=r,           # <-- add this so {{ r... }} in template works
            auto=auto,
        )

    # ---------- STAFF ----------
    def _staff_roles():
        return ["Manager", "Cook", "Dietary Aide", "Dietitian"]

    @app.route("/staff")
    @login_required
    def staff_list():
        q = (request.args.get("q") or "").strip()
        role_filter = (request.args.get("role") or "all").strip()

        query = User.query
        if q:
            like = f"%{q}%"
            query = query.filter(
                or_(
                    User.first_name.ilike(like),
                    User.last_name.ilike(like),
                    User.username.ilike(like),
                    User.email.ilike(like),
                    User.employee_id.ilike(like),
                )
            )
        if role_filter != "all":
            query = query.filter(User.role == role_filter)

        users = query.order_by(
            User.first_name.asc(), User.last_name.asc(), User.username.asc()
        ).all()

        return render_template(
            "staff_list.html",
            users=users,
            q=q,
            role_filter=role_filter,
            roles=_staff_roles(),
        )

    @app.route("/staff/new", methods=["GET", "POST"])
    @login_required
    def staff_new():
        roles = _staff_roles()
        errors = []
        values = {
            "first_name": "",
            "last_name": "",
            "username": "",
            "employee_id": "",
            "email": "",
            "role": "Dietary Aide",
        }

        if request.method == "POST":
            values["first_name"] = request.form.get("first_name", "").strip()
            values["last_name"] = request.form.get("last_name", "").strip()
            values["username"] = request.form.get("username", "").strip().lower()
            values["employee_id"] = request.form.get("employee_id", "").strip()
            values["email"] = request.form.get("email", "").strip()
            values["role"] = request.form.get("role", "Dietary Aide").strip()
            temp_password = request.form.get("temp_password", "").strip()

            if not values["username"]:
                errors.append("Username is required.")
            if not temp_password:
                temp_password = "1234"

            if not errors:
                u = User(
                    username=values["username"],
                    employee_id=values["employee_id"],
                    email=values["email"],
                    first_name=values["first_name"],
                    last_name=values["last_name"],
                    role=values["role"],
                )
                u.set_password(temp_password)
                db.session.add(u)
                db.session.commit()
                flash("Staff added.", "success")
                return redirect(url_for("staff_list"))

        return render_template(
            "staff_form.html", mode="new", values=values, errors=errors, roles=roles
        )

    @app.route("/staff/<int:uid>/edit", methods=["GET", "POST"])
    @login_required
    def staff_edit(uid):
        u = User.query.get_or_404(uid)
        roles = _staff_roles()
        errors = []
        values = {
            "first_name": u.first_name or "",
            "last_name": u.last_name or "",
            "username": u.username or "",
            "employee_id": u.employee_id or "",
            "email": u.email or "",
            "role": u.role or "Dietary Aide",
        }

        if request.method == "POST":
            values["first_name"] = request.form.get("first_name", "").strip()
            values["last_name"] = request.form.get("last_name", "").strip()
            values["username"] = request.form.get("username", "").strip().lower()
            values["employee_id"] = request.form.get("employee_id", "").strip()
            values["email"] = request.form.get("email", "").strip()
            values["role"] = request.form.get("role", "Dietary Aide").strip()

            if not values["username"]:
                errors.append("Username is required.")

            if not errors:
                u.first_name = values["first_name"]
                u.last_name = values["last_name"]
                u.username = values["username"]
                u.employee_id = values["employee_id"]
                u.email = values["email"]
                u.role = values["role"]
                db.session.commit()
                flash("Staff updated.", "success")
                return redirect(url_for("staff_list"))

        return render_template(
            "staff_form.html",
            mode="edit",
            values=values,
            errors=errors,
            roles=roles,
        )

    @app.route("/staff/<int:uid>/reset", methods=["GET", "POST"])
    @login_required
    def staff_reset(uid):
        u = User.query.get_or_404(uid)
        if request.method == "POST":
            pw = request.form.get("password") or "1234"
            u.set_password(pw)
            db.session.commit()
            flash("Password reset.", "success")
            return redirect(url_for("staff_list"))
        return render_template("reset.html", user=u)

    @app.route("/staff/<int:uid>/delete", methods=["POST"])
    @login_required
    def staff_delete(uid):
        u = User.query.get_or_404(uid)
        db.session.delete(u)
        db.session.commit()
        flash("Staff deleted.", "success")
        return redirect(url_for("staff_list"))

    # ---------- INVENTORY ----------
    @app.route("/inventory")
    @login_required
    def inventory_list():
        q = (request.args.get("q") or "").strip()
        show = (request.args.get("show") or "all").strip()

        query = InventoryItem.query
        if q:
            query = query.filter(InventoryItem.name.ilike(f"%{q}%"))
        rows = query.order_by(InventoryItem.name.asc()).all()

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
        units = ["pcs", "kg", "g", "L", "mL", "pack"]
        if request.method == "POST":
            it = InventoryItem(
                name=request.form.get("name") or "",
                unit=request.form.get("unit") or "pcs",
                quantity=_to_float(request.form.get("quantity"), 0.0),
                low_stock_threshold=_to_float(
                    request.form.get("low_stock_threshold"), 0.0
                ),
            )
            db.session.add(it)
            db.session.commit()
            return redirect(url_for("inventory_list"))
        return render_template(
            "inventory_form.html",
            mode="new",
            item_id=None,
            values={},
            errors=[],
            units=units,
            limited=False,
        )

    @app.route("/inventory/<int:iid>/edit", methods=["GET", "POST"])
    @login_required
    def inventory_edit(iid):
        it = InventoryItem.query.get_or_404(iid)
        units = ["pcs", "kg", "g", "L", "mL", "pack"]
        if request.method == "POST":
            it.name = request.form.get("name") or it.name
            it.unit = request.form.get("unit") or it.unit
            it.quantity = _to_float(request.form.get("quantity"), it.quantity or 0.0)
            it.low_stock_threshold = _to_float(
                request.form.get("low_stock_threshold"),
                it.low_stock_threshold or 0.0,
            )
            db.session.commit()
            return redirect(url_for("inventory_list"))

        values = {
            "name": it.name,
            "unit": it.unit,
            "quantity": it.quantity,
            "low_stock_threshold": it.low_stock_threshold,
        }
        return render_template(
            "inventory_form.html",
            mode="edit",
            item_id=it.id,
            values=values,
            errors=[],
            units=units,
            limited=False,
        )

    @app.route("/inventory/<int:iid>/bump", methods=["POST"])
    @login_required
    def inventory_bump(iid):
        it = InventoryItem.query.get_or_404(iid)
        delta = _to_float(request.form.get("delta"), 0.0)
        it.quantity = (it.quantity or 0.0) + delta
        db.session.commit()
        q = request.args.get("q") or ""
        show = request.args.get("show") or "all"
        return redirect(url_for("inventory_list", q=q, show=show))

    @app.route("/inventory/<int:iid>/delete", methods=["POST"])
    @login_required
    def inventory_delete(iid):
        it = InventoryItem.query.get_or_404(iid)
        db.session.delete(it)
        db.session.commit()
        return redirect(url_for("inventory_list"))

    @app.route("/inventory/export")
    @login_required
    def inventory_export():
        q = (request.args.get("q") or "").strip()
        status = (request.args.get("status") or "all").strip()
        query = InventoryItem.query
        if q:
            query = query.filter(InventoryItem.name.ilike(f"%{q}%"))
        rows = query.order_by(InventoryItem.name.asc()).all()

        out = StringIO()
        w = csv.writer(out)
        w.writerow(["Name", "Quantity", "Unit", "Low threshold"])
        for it in rows:
            qty = it.quantity or 0
            is_low = False
            if it.low_stock_threshold is not None:
                is_low = qty <= it.low_stock_threshold
            if status == "low" and not is_low:
                continue
            w.writerow([it.name, qty, it.unit or "", it.low_stock_threshold or ""])

        return Response(
            out.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=inventory.csv"},
        )

    # ---------- MENU ----------
    @app.route("/menu")
    @login_required
    def menu_hub():
        return render_template("menu_hub.html")

    @app.route("/menu/builder")
    @login_required
    def menu_builder():
        # FIX: send inventory so the dropdown isn’t empty
        inventory_items = InventoryItem.query.order_by(InventoryItem.name.asc()).all()
        return render_template("menu_builder.html", inventory_items=inventory_items)

    @app.route("/menu/daily")
    @login_required
    def menu_daily():
        inventory_items = InventoryItem.query.order_by(InventoryItem.name.asc()).all()
        return render_template("menu_daily.html", inventory_items=inventory_items)

    @app.route("/menu/daily/view")
    @login_required
    def menu_daily_view():
        inventory_items = InventoryItem.query.order_by(InventoryItem.name.asc()).all()
        return render_template("menu_daily_view.html", inventory_items=inventory_items)

    @app.route("/menu/scheduler")
    @login_required
    def menu_scheduler():
        menus = Menu.query.order_by(Menu.meal_type.asc(), Menu.title.asc()).all()
        menus_by_meal = {"Breakfast": [], "Lunch": [], "Dinner": []}
        for m in menus:
            menus_by_meal.setdefault(m.meal_type, []).append(m)

        today = date.today()
        monday = today - timedelta(days=today.weekday())
        week_end = monday + timedelta(days=6)

        schedules = (
            MenuSchedule.query.filter(
                MenuSchedule.date >= monday, MenuSchedule.date <= week_end
            )
            .order_by(MenuSchedule.date.asc(), MenuSchedule.meal_type.asc())
            .all()
        )

        grouped = {}
        for s in schedules:
            day_bucket = grouped.setdefault(s.date, {})
            day_bucket.setdefault(s.meal_type, []).append(s)

        days = [{"date": monday + timedelta(days=i)} for i in range(7)]
        inventory_items = InventoryItem.query.order_by(InventoryItem.name.asc()).all()

        return render_template(
            "menu_scheduler.html",
            menus_by_meal=menus_by_meal,
            days=days,
            grouped=grouped,
            inventory_items=inventory_items,
        )

    @app.route("/menu/planned")
    @login_required
    def planned_menus():
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        return redirect(url_for("planned_menu_week", base=monday.isoformat()))

    @app.route("/menu/planned/week")
    @login_required
    def planned_menu_week():
        base_str = request.args.get("base")
        if base_str:
            monday = _parse_date(base_str)
        else:
            today = date.today()
            monday = today - timedelta(days=today.weekday())
        week_start = monday
        week_end = week_start + timedelta(days=6)

        schedules = (
            MenuSchedule.query.filter(
                MenuSchedule.date >= week_start, MenuSchedule.date <= week_end
            )
            .order_by(MenuSchedule.date.asc(), MenuSchedule.meal_type.asc())
            .all()
        )
        grouped = {}
        for s in schedules:
            day_bucket = grouped.setdefault(s.date, {})
            day_bucket.setdefault(s.meal_type, []).append(s)

        days = [{"date": week_start + timedelta(days=i)} for i in range(7)]

        prev_url = url_for(
            "planned_menu_week", base=(week_start - timedelta(days=7)).isoformat()
        )
        next_url = url_for(
            "planned_menu_week", base=(week_start + timedelta(days=7)).isoformat()
        )

        return render_template(
            "planned_menu_week.html",
            week_start=week_start,
            week_end=week_end,
            days=days,
            grouped=grouped,
            prev_url=prev_url,
            next_url=next_url,
        )

    @app.route("/menu/planned/view")
    @login_required
    def planned_menu_view():
        return render_template("planned_menu_view.html")
    # ---------- health ----------
    @app.route("/healthz")
    def healthz():
        return "ok", 200

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
