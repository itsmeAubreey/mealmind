import os
from datetime import datetime, date, timedelta

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
)
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    current_user,
    login_required,
)
from werkzeug.security import generate_password_hash

# pull models from your models.py
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

# ---------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------


def _to_float(val, default=0.0):
    try:
        return float(val)
    except Exception:
        return default


def _parse_date(s: str):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def current_role() -> str:
    if not current_user or current_user.is_anonymous:
        return ""
    return current_user.role or ""


# ---------------------------------------------------------------------
# app factory
# ---------------------------------------------------------------------


def create_app():
    app = Flask(__name__, template_folder="templates")

    # secret + db
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "SQLALCHEMY_DATABASE_URI", "sqlite:///mealmind.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    # login
    login_manager = LoginManager(app)
    login_manager.login_view = "login"

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # --------------------------------------------------------------
    # auth
    # --------------------------------------------------------------
    @app.route("/", methods=["GET"])
    def home():
        # just send them to login — your login page is the entry point
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = (request.form.get("username") or "").strip().lower()
            password = (request.form.get("password") or "").strip()

            user = (
                User.query.filter(
                    (User.username.ilike(username)) | (User.employee_id.ilike(username))
                )
                .order_by(User.id.asc())
                .first()
            )

            if user and user.check_password(password):
                login_user(user)
                return redirect(url_for("dashboard"))

            flash("Invalid credentials.", "error")

        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    # --------------------------------------------------------------
    # dashboard
    # --------------------------------------------------------------
    @app.route("/dashboard")
    @login_required
    def dashboard():
        # your dashboard.html already knows how to show the 4 tiles
        return render_template("dashboard.html")

    # --------------------------------------------------------------
    # change password (your template name is change_password.html)
    # --------------------------------------------------------------
    @app.route("/change-password", methods=["GET", "POST"])
    @login_required
    def change_password():
        if request.method == "POST":
            cur = request.form.get("current_password") or ""
            new = request.form.get("new_password") or ""
            if not current_user.check_password(cur):
                flash("Current password is incorrect.", "error")
            elif not new:
                flash("New password is required.", "error")
            else:
                current_user.set_password(new)
                current_user.must_change_password = False
                db.session.commit()
                flash("Password updated.", "success")
                return redirect(url_for("dashboard"))
        return render_template("change_password.html")

    # --------------------------------------------------------------
    # residents
    # --------------------------------------------------------------
    @app.route("/residents")
    @login_required
    def residents():
        data = Resident.query.order_by(Resident.last_name.asc()).all()
        return render_template("residents_list.html", residents=data)

    @app.route("/residents/new", methods=["GET", "POST"])
    @login_required
    def resident_new():
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
            flash("Resident added.", "success")
            return redirect(url_for("residents"))
        return render_template("residents_form.html", resident=None)

    @app.route("/residents/<int:rid>/edit", methods=["GET", "POST"])
    @login_required
    def resident_edit(rid):
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
            flash("Resident updated.", "success")
            return redirect(url_for("residents"))
        return render_template("residents_form.html", resident=r)

    @app.route("/residents/<int:rid>/print")
    @login_required
    def resident_print(rid):
        r = Resident.query.get_or_404(rid)
        return render_template("resident_print.html", resident=r)

    @app.route("/residents/<int:rid>/delete")
    @login_required
    def resident_delete(rid):
        r = Resident.query.get_or_404(rid)
        db.session.delete(r)
        db.session.commit()
        flash("Resident deleted.", "success")
        return redirect(url_for("residents"))

    # --------------------------------------------------------------
    # inventory
    # --------------------------------------------------------------
    @app.route("/inventory")
    @login_required
    def inventory():
        items = InventoryItem.query.order_by(InventoryItem.name.asc()).all()
        # your template was inventory_list.html
        return render_template("inventory_list.html", items=items)

    @app.route("/inventory/new", methods=["GET", "POST"])
    @login_required
    def inventory_new():
        if request.method == "POST":
            item = InventoryItem(
                name=request.form.get("name") or "",
                unit=request.form.get("unit") or "pcs",
                quantity=_to_float(request.form.get("quantity"), 0.0),
                low_stock_threshold=_to_float(
                    request.form.get("low_stock_threshold"), 0.0
                ),
            )
            db.session.add(item)
            db.session.commit()
            flash("Inventory item added.", "success")
            return redirect(url_for("inventory"))
        return render_template("inventory_form.html", item=None)

    @app.route("/inventory/<int:item_id>/edit", methods=["GET", "POST"])
    @login_required
    def inventory_edit(item_id):
        item = InventoryItem.query.get_or_404(item_id)
        if request.method == "POST":
            item.name = request.form.get("name") or item.name
            item.unit = request.form.get("unit") or item.unit
            item.quantity = _to_float(request.form.get("quantity"), item.quantity)
            item.low_stock_threshold = _to_float(
                request.form.get("low_stock_threshold"), item.low_stock_threshold
            )
            db.session.commit()
            flash("Inventory updated.", "success")
            return redirect(url_for("inventory"))
        return render_template("inventory_form.html", item=item)

    @app.route("/inventory/<int:item_id>/delete")
    @login_required
    def inventory_delete(item_id):
        item = InventoryItem.query.get_or_404(item_id)
        db.session.delete(item)
        db.session.commit()
        flash("Inventory item deleted.", "success")
        return redirect(url_for("inventory"))

    # some of your HTMLs link to /inventory/export — make it exist
    @app.route("/inventory/export")
    @login_required
    def inventory_export():
        from flask import Response

        items = InventoryItem.query.order_by(InventoryItem.name.asc()).all()
        lines = ["name,unit,quantity,low_stock_threshold"]
        for it in items:
            lines.append(
                f"{it.name},{it.unit},{it.quantity or 0},{it.low_stock_threshold or 0}"
            )
        csv_data = "\n".join(lines)
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=inventory.csv"},
        )

    # --------------------------------------------------------------
    # staff
    # --------------------------------------------------------------
    @app.route("/staff")
    @login_required
    def staff():
        users = User.query.order_by(User.username.asc()).all()
        return render_template("staff_list.html", users=users)

    @app.route("/staff/new", methods=["GET", "POST"])
    @login_required
    def staff_new():
        if request.method == "POST":
            u = User(
                first_name=request.form.get("first_name") or "",
                last_name=request.form.get("last_name") or "",
                username=(request.form.get("username") or "").lower(),
                employee_id=request.form.get("employee_id") or "",
                email=request.form.get("email") or "",
                role=request.form.get("role") or "Dietary Aide",
            )
            pw = request.form.get("password") or "1234"
            u.set_password(pw)
            db.session.add(u)
            db.session.commit()
            flash("Staff added.", "success")
            return redirect(url_for("staff"))
        return render_template("staff_form.html", user=None)

    @app.route("/staff/<int:uid>/edit", methods=["GET", "POST"])
    @login_required
    def staff_edit(uid):
        u = User.query.get_or_404(uid)
        if request.method == "POST":
            u.first_name = request.form.get("first_name") or ""
            u.last_name = request.form.get("last_name") or ""
            u.username = (request.form.get("username") or u.username).lower()
            u.employee_id = request.form.get("employee_id") or ""
            u.email = request.form.get("email") or ""
            u.role = request.form.get("role") or u.role
            db.session.commit()
            flash("Staff updated.", "success")
            return redirect(url_for("staff"))
        return render_template("staff_form.html", user=u)

    @app.route("/staff/<int:uid>/reset", methods=["GET", "POST"])
    @login_required
    def staff_reset(uid):
        u = User.query.get_or_404(uid)
        if request.method == "POST":
            new_pw = request.form.get("password") or "1234"
            u.set_password(new_pw)
            u.must_change_password = True
            db.session.commit()
            flash("Password reset.", "success")
            return redirect(url_for("staff"))
        return render_template("reset.html", user=u)

    # --------------------------------------------------------------
    # MENU AREA (hub, builder, scheduler, planned)
    # --------------------------------------------------------------
    @app.route("/menu")
    @login_required
    def menu_hub():
        return render_template("menu_hub.html")

    @app.route("/menu/builder", methods=["GET", "POST"])
    @login_required
    def menu_builder():
        if current_role() not in ("Manager", "Dietitian", "Cook"):
            flash("You do not have access to that page.", "error")
            return redirect(url_for("menu_hub"))

        inventory_items = InventoryItem.query.order_by(InventoryItem.name.asc()).all()
        errors = []
        values = {}

        if request.method == "POST":
            meal_type = (request.form.get("meal_type") or "").strip()
            title = (request.form.get("title") or "").strip()
            description = (request.form.get("description") or "").strip()
            ids = request.form.getlist("ingredient_id")
            qtys = request.form.getlist("quantity")

            if meal_type not in ("Breakfast", "Lunch", "Dinner"):
                errors.append("Select a valid meal type.")
            if not title:
                errors.append("Menu title is required.")
            if not ids:
                errors.append("Add at least one ingredient.")

            if errors:
                menus = Menu.query.order_by(Menu.meal_type.asc(), Menu.title.asc()).all()
                values = {
                    "meal_type": meal_type,
                    "title": title,
                    "description": description,
                }
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
                m.ingredients.append(
                    MenuIngredient(
                        inventory_id=inv.id,
                        quantity=_to_float(qty, 0.0),
                        unit=inv.unit,
                    )
                )

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
    def menu_builder_edit(menu_id):
        if current_role() not in ("Manager", "Dietitian", "Cook"):
            flash("You do not have access to that page.", "error")
            return redirect(url_for("menu_hub"))

        inventory_items = InventoryItem.query.order_by(InventoryItem.name.asc()).all()
        current_menu = Menu.query.get_or_404(menu_id)
        errors = []
        values = {}

        if request.method == "POST":
            meal_type = (request.form.get("meal_type") or "").strip()
            title = (request.form.get("title") or "").strip()
            description = (request.form.get("description") or "").strip()
            ids = request.form.getlist("ingredient_id")
            qtys = request.form.getlist("quantity")

            if meal_type not in ("Breakfast", "Lunch", "Dinner"):
                errors.append("Select a valid meal type.")
            if not title:
                errors.append("Menu title is required.")
            if not ids:
                errors.append("Add at least one ingredient.")

            if errors:
                menus = Menu.query.order_by(Menu.meal_type.asc(), Menu.title.asc()).all()
                values = {
                    "meal_type": meal_type,
                    "title": title,
                    "description": description,
                }
                return render_template(
                    "menu_builder.html",
                    inventory_items=inventory_items,
                    menus=menus,
                    errors=errors,
                    values=values,
                    editing=True,
                    current_menu=current_menu,
                )

            current_menu.meal_type = meal_type
            current_menu.title = title
            current_menu.description = description
            current_menu.ingredients.clear()

            for inv_id, qty in zip(ids, qtys):
                if not inv_id or not qty:
                    continue
                inv = InventoryItem.query.get(int(inv_id))
                if not inv:
                    continue
                current_menu.ingredients.append(
                    MenuIngredient(
                        inventory_id=inv.id,
                        quantity=_to_float(qty, 0.0),
                        unit=inv.unit,
                    )
                )

            db.session.commit()
            flash("Menu updated.", "success")
            return redirect(url_for("menu_builder"))

        menus = Menu.query.order_by(Menu.meal_type.asc(), Menu.title.asc()).all()
        return render_template(
            "menu_builder.html",
            inventory_items=inventory_items,
            menus=menus,
            errors=errors,
            values=values,
            editing=True,
            current_menu=current_menu,
        )

    @app.route("/menu/builder/<int:menu_id>/delete", methods=["POST"])
    @login_required
    def menu_builder_delete(menu_id):
        m = Menu.query.get_or_404(menu_id)
        db.session.delete(m)
        db.session.commit()
        flash("Menu deleted.", "success")
        return redirect(url_for("menu_builder"))

    # ---------------- scheduler (this was 500 in your log) -------------
    @app.route("/menu/scheduler", methods=["GET", "POST"])
    @login_required
    def menu_scheduler():
        if current_role() not in ("Manager", "Dietitian", "Cook"):
            flash("You do not have access to that page.", "error")
            return redirect(url_for("menu_hub"))

        # list of reusable menus grouped by meal (what template expects)
        all_menus = Menu.query.order_by(Menu.meal_type.asc(), Menu.title.asc()).all()
        menus_by_meal = {"Breakfast": [], "Lunch": [], "Dinner": []}
        for m in all_menus:
            menus_by_meal.setdefault(m.meal_type, []).append(m)

        inventory_items = InventoryItem.query.order_by(InventoryItem.name.asc()).all()

        if request.method == "POST":
            # simple version: schedule exactly one meal for one day
            date_val = _parse_date(request.form.get("date"))
            meal_type = request.form.get("meal_type")
            chosen_menu_id = request.form.get("menu_id")
            notes = request.form.get("notes") or ""

            if not date_val or meal_type not in ("Breakfast", "Lunch", "Dinner"):
                flash("Invalid data.", "error")
            else:
                sched = MenuSchedule(
                    date=date_val,
                    meal_type=meal_type,
                    menu_id=int(chosen_menu_id) if chosen_menu_id else None,
                    notes=notes,
                )
                db.session.add(sched)
                db.session.flush()

                # if a menu selected, record/deduct its ingredients
                if chosen_menu_id:
                    chosen_menu = Menu.query.get(int(chosen_menu_id))
                    if chosen_menu:
                        for ing in chosen_menu.ingredients:
                            # record row
                            db.session.add(
                                MenuScheduleItem(
                                    schedule_id=sched.id,
                                    inventory_id=ing.inventory_id,
                                    quantity_used=ing.quantity,
                                )
                            )
                            # deduct from inventory
                            inv = InventoryItem.query.get(ing.inventory_id)
                            if inv:
                                inv.quantity = (inv.quantity or 0) - (ing.quantity or 0)

                db.session.commit()
                flash("Menu scheduled and inventory updated.", "success")
                return redirect(url_for("menu_scheduler"))

        # build current week grid so template can show something
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
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
            days.append({"date": d, "dow": d.strftime("%a %m/%d")})

        return render_template(
            "menu_scheduler.html",
            menus_by_meal=menus_by_meal,
            days=days,
            grouped=grouped,
            inventory_items=inventory_items,
        )

    # ---------------- planned menus list -------------------------------
    @app.route("/menu/planned")
    @login_required
    def planned_menus():
        rows = MenuSchedule.query.order_by(MenuSchedule.date.asc()).all()
        grouped = {}
        for r in rows:
            grouped.setdefault(r.date, []).append(r)
        return render_template("planned_menus.html", grouped=grouped)

    # ---------------- weekly grid (with prev/next) ----------------------
    @app.route("/menu/planned/week")
    @login_required
    def planned_menu_week():
        # optional ?offset=0 (0 = this week, 1 = next week, -1 = last week)
        offset = int(request.args.get("offset", 0))
        today = date.today()
        base = today - timedelta(days=today.weekday())  # monday
        week_start = base + timedelta(days=7 * offset)
        week_end = week_start + timedelta(days=6)

        # fetch schedules for the week
        schedules = (
            MenuSchedule.query.filter(
                MenuSchedule.date >= week_start, MenuSchedule.date <= week_end
            )
            .order_by(MenuSchedule.date.asc(), MenuSchedule.meal_type.asc())
            .all()
        )

        grouped = {}
        for s in schedules:
            day = grouped.setdefault(s.date, {})
            # figure out title
            menu_title = ""
            if s.menu_id:
                mm = Menu.query.get(s.menu_id)
                if mm:
                    menu_title = mm.title
            day.setdefault(s.meal_type, []).append(
                {
                    "menu_title": menu_title or "(untitled)",
                    "notes": s.notes or "",
                }
            )

        days = []
        for i in range(7):
            d = week_start + timedelta(days=i)
            days.append({"date": d, "dow": d.strftime("%a %m/%d")})

        prev_url = url_for("planned_menu_week", offset=offset - 1)
        next_url = url_for("planned_menu_week", offset=offset + 1)

        return render_template(
            "planned_menu_week.html",
            grouped=grouped,
            week_start=week_start,
            week_end=week_end,
            days=days,
            prev_url=prev_url,
            next_url=next_url,
            offset=offset,
        )

    # ---------------- one-day detail view -------------------------------
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

        order = {"Breakfast": 0, "Lunch": 1, "Dinner": 2}
        schedules = sorted(schedules, key=lambda s: order.get(s.meal_type, 99))

        detail = []
        for s in schedules:
            # load used items
            rows = (
                MenuScheduleItem.query.filter_by(schedule_id=s.id)
                .order_by(MenuScheduleItem.id.asc())
                .all()
            )
            items = []
            for r in rows:
                inv = InventoryItem.query.get(r.inventory_id)
                items.append(
                    {
                        "name": inv.name if inv else "(deleted item)",
                        "unit": inv.unit if inv else "",
                        "qty": r.quantity_used or 0.0,
                    }
                )

            title = "(untitled)"
            if s.menu_id:
                mm = Menu.query.get(s.menu_id)
                if mm:
                    title = mm.title

            detail.append(
                {
                    "meal": s.meal_type,
                    "notes": s.notes,
                    "menu_title": title,
                    "items": items,
                }
            )

        return render_template("planned_menu_view.html", day_value=d, blocks=detail)

    # --------------------------------------------------------------
    # health
    # --------------------------------------------------------------
    @app.route("/healthz")
    def healthz():
        return "ok", 200

    return app


# --------------------------------------------------------------
# module-level for gunicorn / azure
# --------------------------------------------------------------
app = create_app()
with app.app_context():
    db.create_all()
    # seed a manager if db empty
    if not User.query.first():
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
        print("Seeded default user: manager / 1234")

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )
