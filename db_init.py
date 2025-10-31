from app import create_app
from models import db, User

app = create_app()
with app.app_context():
    db.create_all()

    mgr = User.query.filter_by(username="manager").first()
    if not mgr:
        mgr = User(
            username="manager",
            role="Manager",
            must_change_password=False,  # manager won’t be prompted
        )
        mgr.set_password("1234")
        db.session.add(mgr)
        db.session.commit()
        print("Created default manager (manager/1234).")
    else:
        print("Manager account already present.")
