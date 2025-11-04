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
)
from sqlalchemy import or_

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


# ---------------- helpers ----------------
def _parse_date(val: str):
    if not val:
        return None
    val = val.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None


def _to_float(val, default=0.0):
    try:
        return float(val)
    except Exception:
        return default


def current_user():
    return session.get("user")


def current_role():
    u = session.get("user")
    return u.get("role") if u else None


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return wrapper


# -------------- app factory --------------
def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-key")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "SQLALCHEMY_DATABASE_URI", "sqlite:///mealmind.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    with app.app_context():
        db.create_all()
        # seed 1 manager if empty
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
            print("Seeded user: manager / 1234")

    # ---------- context ----------
    @app.context_processor
    def inject_user():
        return {"current_user": session.get("user")}

    # ---------- routes ----------

    @app.route("/")
    def home():
        if "user" in session:
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    # ---------- auth ----------
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

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ---------- dashboard ----------
    @app.route("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html")

    # ---------- residents ----------
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
        rows = query.order_by(Resident.last_name.asc(), Resident.first_name.asc()).all()
        return render_template("residents_list.html", residents=rows, q=q)

    @app.route("/residents/new", methods=["GET", "POST"])
    @login_required
    def residents_new():
        if request.method == "POST":
            r = Resident(
                first_name=request.form.get("first_name") or "",
                last_name=request.form.get("last_name") or "",
                birthday=_parse_date(request.form.get("birthday")),
                diet=request.form.get("diet") or "",
                allergies=request.form.get("allergies") or "",
                illnesses=request.form.get("illnesses") or "",
                medications=request.form.get("medications") or "",
                fluids=request.form.get("fluids") or "",
                notes=request.form.get("notes") or "",
            )
            db.session.add(r)
            db.session.commit()
            return redirect(url_for("residents_list"))
        return render_template("residents_form.html", resident=None)

    @app.route("/residents/<int:rid>/edit", methods=["GET", "POST"])
    @login_required
    def residents_edit(rid):
        r = Resident.query.get_or_404(rid)
        if request.method == "POST":
            r.first_name = request.form.get("first_name") or ""
            r.last_name = request.form.get("last_name") or ""
            r.birthday = _parse_date(request.form.get("birthday"))
            r.diet = request.form.get("diet") or ""
            r.allergies = request.form.get("allergies") or ""
            r.illnesses = request.form.get("illnesses") or ""
            r.medications = request.form.get("medications") or ""
            r.fluids = request.form.get("fluids") or ""
            r.notes = request.form.get("notes") or ""
            db.session.commit()
            return redirect(url_for("residents_list"))
        return render_template("residents_form.html", resident=r)

    @app.route("/resident/<int:rid>/print")
    @login_required
    def resident_print(rid):
        r = Resident.query.get_or_404(rid)
        return render_template("resident_print.html", r=r)

    # ---------- staff ----------
    @app.route("/staff")
    @login_required
    def staff_list():
        users = User.query.order_by(User.username.asc()).all()
        return render_template("staff_list.html", users=users)

    @app.route("/staff/new", methods=["GET", "POST"])
    @login_required
    def staff_new():
        if request.method == "POST":
            u = User(
                first_name=request.form.get("first_name") or "",
                last_name=request.form.get("last_name") or "",
                username=(request.form.get("username") or "").strip().lower(),
                employee_id=request.form.get("employee_id") or "",
                email=request.form.get("email") or "",
                role=request.form.get("role") or "Dietary Aide",
            )
            pw = request.form.get("password") or "1234"
            u.set_password(pw)
            db.session.add(u)
            db.session.commit()
            flash("Staff created.", "success")
            return redirect(url_for("staff_list"))
        return render_template("staff_form.html", user=None)

    @app.route("/staff/<int:uid>/edit", methods=["GET", "POST"])
    @login_required
    def staff_edit(uid):
        u = User.query.get_or_404(uid)
        if request.method == "POST":
            u.first_name = request.form.get("first_name") or ""
            u.last_name = request.form.get("last_name") or ""
            u.username = (request.form.get("username") or u.username).strip().lower()
            u.employee_id = request.form.get("employee_id") or ""
            u.email = request.form.get("email") or ""
            u.role = request.form.get("role") or u.role
            db.session.commit()
            flash("Staff updated.", "success")
            return redirect(url_for("staff_list"))
        return render_template("staff_form.html", user=u)

    @app.route("/staff/<int:uid>/reset", methods=["GET", "POST"])
    @login_required
    def staff_reset(uid):
        u = User.query.get_or_404(uid)
        if request.method == "POST":
            newpw = request.form.get("password") or "1234"
            u.set_password(newpw)
            db.session.commit()
            flash("Password reset.", "success")
            return redirect(url_for("staff_list"))
        return render_template("reset.html", user=u)

    # ---------- inventory ----------
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
        return render_template("inventory_form.html", item=None)

    @app.route("/inventory/<int:iid>/edit", methods=["GET", "POST"])
    @login_required
    def inventory_edit(iid):
        it = InventoryItem.query.get_or_404(iid)
        if request.method == "POST":
            it.name = request.form.get("name") or it.name
            it.unit = request.form.get("unit") or it.unit
            it.quantity = _to_float(request.form.get("quantity"), it.quantity or 0.0)
            it.low_stock_threshold = _to_float(
                request.form.get("low_stock_threshold"), it.low_stock_threshold or 0.0
            )
            db.session.commit()
            return redirect(url_for("inventory_list"))
        return render_template("inventory_form.html", item=it)

    @app.route("/inventory/<int:iid>/bump", methods=["POST"])
    @login_required
    def inventory_bump(iid):
        delta = _to_float(request.form.get("delta"), 0.0)
        it = InventoryItem.query.get_or_404(iid)
        it.quantity = (it.quantity or 0.0) + delta
        db.session.commit()
        q = request.args.get("q") or ""
        show = request.args.get("show") or "all"
        return redirect(url_for("inventory_list", q=q, show=show))

    # this was missing -> caused 500
    @app.route("/inventory/export")
    @login_required
    def inventory_export():
        q = (request.args.get("q") or "").strip()
        status = (request.args.get("status") or "all").strip()

        query = InventoryItem.query
        if q:
            query = query.filter(InventoryItem.name.ilike(f"%{q}%"))
        rows = query.order_by(InventoryItem.name.asc()).all()

        filtered = []
        for it in rows:
            qty = it.quantity or 0.0
            thr = it.low_stock_threshold or 0.0
            is_low = (qty <= thr) if it.low_stock_threshold is not None else False
            if status == "low" and not is_low:
                continue
            filtered.append(it)

        out = StringIO()
        w = csv.writer(out)
        w.writerow(["Name", "Quantity", "Unit", "Low stock threshold"])
        for it in filtered:
            w.writerow(
                [
                    it.name,
                    it.quantity or 0,
                    it.unit or "",
                    it.low_stock_threshold or "",
                ]
            )
        return Response(
            out.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=inventory.csv"},
        )

    # ---------- menu hub ----------
    @app.route("/menu")
    @login_required
    def menu_hub():
        return render_template("menu_hub.html")

    # ---------- menu scheduler (was missing context) ----------
    @app.route("/menu/scheduler", methods=["GET", "POST"])
    @login_required
    def menu_scheduler():
        # load menus and group by meal so template can loop
        all_menus = Menu.query.order_by(Menu.meal_type.asc(), Menu.title.asc()).all()
        menus_by_meal = {"Breakfast": [], "Lunch": [], "Dinner": []}
        for m in all_menus:
            menus_by_meal.setdefault(m.meal_type, []).append(m)

        # build current week dates
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        days = []
        for i in range(7):
            d = monday + timedelta(days=i)
            days.append({"date": d, "label": d.strftime("%a %m/%d")})

        # fetch existing schedules in this week
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

        # for the “deduct” modal the template had, send inventory
        inventory_items = InventoryItem.query.order_by(InventoryItem.name.asc()).all()

        return render_template(
            "menu_scheduler.html",
            menus_by_meal=menus_by_meal,
            days=days,
            grouped=grouped,
            inventory_items=inventory_items,
        )

    # ---------- planned menus ----------
    @app.route("/menu/planned")
    @login_required
    def planned_menus():
        # show current week by default
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        return redirect(url_for("planned_menu_week", base=monday.isoformat()))

    @app.route("/menu/planned/week")
    @login_required
    def planned_menu_week():
        # ?base=YYYY-MM-DD
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

        days = []
        for i in range(7):
            d = week_start + timedelta(days=i)
            days.append({"date": d, "label": d.strftime("%a %m/%d")})

        # prev / next links
        prev_base = (week_start - timedelta(days=7)).isoformat()
        next_base = (week_start + timedelta(days=7)).isoformat()

        return render_template(
            "planned_menu_week.html",
            week_start=week_start,
            week_end=week_end,
            days=days,
            grouped=grouped,
            prev_url=url_for("planned_menu_week", base=prev_base),
            next_url=url_for("planned_menu_week", base=next_base),
        )

    @app.route("/menu/planned/<string:day_str>")
    @login_required
    def planned_menu_view(day_str):
        d = _parse_date(day_str)
        if not d:
            flash("Invalid date.", "error")
            return redirect(url_for("planned_menus"))

        schedules = (
            MenuSchedule.query.filter_by(date=d)
            .order_by(MenuSchedule.meal_type.asc())
            .all()
        )
        blocks = []
        for s in schedules:
            title = ""
            if s.menu_id:
                mm = Menu.query.get(s.menu_id)
                if mm:
                    title = mm.title
            items = (
                MenuScheduleItem.query.filter_by(schedule_id=s.id)
                .order_by(MenuScheduleItem.id.asc())
                .all()
            )
            used = []
            for it in items:
                inv = InventoryItem.query.get(it.inventory_id)
                used.append(
                    {
                        "name": inv.name if inv else "(removed)",
                        "qty": it.quantity_used or 0,
                        "unit": inv.unit if inv else "",
                    }
                )
            blocks.append(
                {
                    "meal": s.meal_type,
                    "menu_title": title or "(untitled)",
                    "notes": s.notes or "",
                    "items": used,
                }
            )

        return render_template(
            "planned_menu_view.html", day_value=d, blocks=blocks
        )

    # health
    @app.route("/healthz")
    def healthz():
        return "ok", 200

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
