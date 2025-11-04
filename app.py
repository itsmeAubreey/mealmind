import os
from flask import Flask, render_template_string, request, redirect, url_for, session

def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-key")

    @app.route("/healthz")
    def healthz():
        return "ok", 200

    @app.route("/")
    def home():
        # if already "logged in" go to dashboard
        if "user" in session:
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            # accept any username/password for now
            username = (request.form.get("username") or "user").strip()
            session["user"] = {"username": username}
            return redirect(url_for("dashboard"))

        # tiny inline page so we don't depend on templates yet
        return render_template_string("""
        <!doctype html>
        <html>
        <head><title>MealMind – Login</title></head>
        <body style="font-family:Arial, sans-serif; max-width:480px; margin:40px auto;">
          <h1>MealMind login (test)</h1>
          <form method="post" style="display:flex; flex-direction:column; gap:8px;">
            <input name="username" placeholder="username" style="padding:6px;">
            <input name="password" type="password" placeholder="password" style="padding:6px;">
            <button style="padding:6px 10px;">Login</button>
          </form>
        </body>
        </html>
        """)

    @app.route("/dashboard")
    def dashboard():
        if "user" not in session:
            return redirect(url_for("login"))
        user = session["user"]["username"]
        return render_template_string(f"""
        <!doctype html>
        <html>
        <head><title>MealMind – Dashboard</title></head>
        <body style="font-family:Arial, sans-serif; max-width:720px; margin:40px auto;">
          <h1>Dashboard OK</h1>
          <p>Hi, {user}! If you can see this, Azure is now running the UPDATED app.py.</p>
          <p><a href="{url_for('logout')}">Logout</a></p>
        </body>
        </html>
        """)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    return app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
