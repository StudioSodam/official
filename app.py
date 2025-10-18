import os
from datetime import datetime

from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

PROJECT_STATUSES = {
    "planning": "기획 중",
    "in_progress": "진행 중",
    "completed": "완료",
}

INVOICE_STATUSES = {
    "pending": "요청",
    "sent": "송신",
    "paid": "입금 완료",
}


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///studio_sodam.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "studio-sodam-secret")

    db.init_app(app)

    with app.app_context():
        db.create_all()
        ensure_default_admin()

    register_routes(app)
    return app


db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), default="manager")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(150), nullable=False)
    contact_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(40))
    industry = db.Column(db.String(100))
    notes = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    projects = db.relationship("Project", backref="client", lazy=True, cascade="all, delete-orphan")
    messages = db.relationship("Message", backref="client", lazy=True, cascade="all, delete-orphan")
    invoices = db.relationship("Invoice", backref="client", lazy=True, cascade="all, delete-orphan")


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    status = db.Column(db.String(50), default="planning")
    kickoff_date = db.Column(db.Date)
    delivery_date = db.Column(db.Date)
    budget = db.Column(db.Float)
    description = db.Column(db.Text)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    author = db.Column(db.String(120), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(50), default="pending")
    due_date = db.Column(db.Date)
    issued_at = db.Column(db.DateTime, default=datetime.utcnow)


def ensure_default_admin() -> None:
    if not User.query.first():
        admin = User(email="admin@studiosodam.com", name="관리자")
        admin.set_password("sodam1234")
        admin.role = "administrator"
        db.session.add(admin)
        db.session.commit()


def login_required(view_func):
    from functools import wraps

    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("로그인이 필요합니다.", "warning")
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped_view


def register_routes(app: Flask) -> None:
    @app.context_processor
    def inject_globals():
        return {
            "now": datetime.utcnow(),
            "PROJECT_STATUSES": PROJECT_STATUSES,
            "INVOICE_STATUSES": INVOICE_STATUSES,
        }

    @app.route("/")
    @login_required
    def dashboard():
        client_count = Client.query.count()
        active_projects = Project.query.filter(Project.status != "completed").count()
        outstanding_invoices = Invoice.query.filter(Invoice.status != "paid").count()

        upcoming_projects = (
            Project.query.filter(
                Project.kickoff_date != None, Project.status != "completed"
            )
            .order_by(Project.kickoff_date.asc())
            .limit(5)
            .all()
        )

        recent_messages = (
            Message.query.order_by(Message.created_at.desc()).limit(5).all()
        )

        return render_template(
            "dashboard.html",
            client_count=client_count,
            active_projects=active_projects,
            outstanding_invoices=outstanding_invoices,
            upcoming_projects=upcoming_projects,
            recent_messages=recent_messages,
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form["email"].strip().lower()
            password = request.form["password"]
            user = User.query.filter(func.lower(User.email) == email).first()
            if user and user.check_password(password):
                session["user_id"] = user.id
                session["user_name"] = user.name
                flash(f"{user.name}님 환영합니다!", "success")
                return redirect(url_for("dashboard"))
            flash("로그인 정보가 정확하지 않습니다.", "danger")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        flash("로그아웃 되었습니다.", "info")
        return redirect(url_for("login"))

    @app.route("/clients")
    @login_required
    def clients():
        status = request.args.get("status", "all")
        query = Client.query
        if status == "active":
            query = query.filter_by(active=True)
        elif status == "inactive":
            query = query.filter_by(active=False)
        clients = query.order_by(Client.company_name.asc()).all()
        return render_template("clients.html", clients=clients, status=status)

    @app.route("/clients/new", methods=["GET", "POST"])
    @login_required
    def new_client():
        if request.method == "POST":
            client = Client(
                company_name=request.form["company_name"].strip(),
                contact_name=request.form["contact_name"].strip(),
                email=request.form["email"].strip(),
                phone=request.form.get("phone", "").strip() or None,
                industry=request.form.get("industry", "").strip() or None,
                notes=request.form.get("notes", "").strip() or None,
                active="active" in request.form,
            )
            db.session.add(client)
            db.session.commit()
            flash("새 클라이언트가 등록되었습니다.", "success")
            return redirect(url_for("clients"))
        return render_template("client_form.html")

    @app.route("/clients/<int:client_id>", methods=["GET", "POST"])
    @login_required
    def client_detail(client_id: int):
        client = Client.query.get_or_404(client_id)
        if request.method == "POST":
            message = Message(
                client=client,
                author=session.get("user_name", "스태프"),
                content=request.form["content"].strip(),
            )
            if not message.content:
                flash("메시지 내용을 입력해주세요.", "warning")
            else:
                db.session.add(message)
                db.session.commit()
                flash("메시지가 전송되었습니다.", "success")
            return redirect(url_for("client_detail", client_id=client.id))

        return render_template("client_detail.html", client=client)

    @app.route("/clients/<int:client_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_client(client_id: int):
        client = Client.query.get_or_404(client_id)
        if request.method == "POST":
            client.company_name = request.form["company_name"].strip()
            client.contact_name = request.form["contact_name"].strip()
            client.email = request.form["email"].strip()
            client.phone = request.form.get("phone", "").strip() or None
            client.industry = request.form.get("industry", "").strip() or None
            client.notes = request.form.get("notes", "").strip() or None
            client.active = "active" in request.form
            db.session.commit()
            flash("클라이언트 정보가 업데이트되었습니다.", "success")
            return redirect(url_for("client_detail", client_id=client.id))
        return render_template("client_form.html", client=client)

    @app.route("/clients/<int:client_id>/projects/new", methods=["POST"])
    @login_required
    def add_project(client_id: int):
        client = Client.query.get_or_404(client_id)
        status = request.form.get("status", "planning")
        if status not in PROJECT_STATUSES:
            status = "planning"
        budget_raw = (request.form.get("budget") or "").replace(",", "")
        project = Project(
            client=client,
            name=request.form["name"].strip(),
            status=status,
            budget=budget_raw or None,
            description=request.form.get("description", "").strip() or None,
        )
        kickoff_date = request.form.get("kickoff_date")
        delivery_date = request.form.get("delivery_date")
        if kickoff_date:
            project.kickoff_date = datetime.strptime(kickoff_date, "%Y-%m-%d").date()
        if delivery_date:
            project.delivery_date = datetime.strptime(delivery_date, "%Y-%m-%d").date()
        if project.budget:
            try:
                project.budget = float(project.budget)
            except ValueError:
                project.budget = None
                flash("예산 값이 올바르지 않아 저장되지 않았습니다.", "warning")
        db.session.add(project)
        db.session.commit()
        flash("프로젝트가 추가되었습니다.", "success")
        return redirect(url_for("client_detail", client_id=client.id))

    @app.route("/clients/<int:client_id>/invoices/new", methods=["POST"])
    @login_required
    def add_invoice(client_id: int):
        client = Client.query.get_or_404(client_id)
        amount_raw = (request.form.get("amount") or "0").replace(",", "")
        status = request.form.get("status", "pending")
        if status not in INVOICE_STATUSES:
            status = "pending"
        try:
            amount = float(amount_raw)
        except ValueError:
            flash("금액 형식이 올바르지 않습니다.", "danger")
            return redirect(url_for("client_detail", client_id=client.id))
        invoice = Invoice(
            client=client,
            title=request.form["title"].strip(),
            amount=amount,
            status=status,
        )
        due_date = request.form.get("due_date")
        if due_date:
            invoice.due_date = datetime.strptime(due_date, "%Y-%m-%d").date()
        db.session.add(invoice)
        db.session.commit()
        flash("결제 정보가 추가되었습니다.", "success")
        return redirect(url_for("client_detail", client_id=client.id))

    @app.route("/clients/<int:client_id>/invoices/<int:invoice_id>/status", methods=["POST"])
    @login_required
    def update_invoice_status(client_id: int, invoice_id: int):
        invoice = Invoice.query.filter_by(id=invoice_id, client_id=client_id).first_or_404()
        status = request.form.get("status", invoice.status)
        if status not in INVOICE_STATUSES:
            flash("허용되지 않은 결제 상태입니다.", "danger")
        else:
            invoice.status = status
            db.session.commit()
            flash("결제 상태가 변경되었습니다.", "success")
        return redirect(url_for("client_detail", client_id=client_id))

    @app.route("/settings/profile", methods=["GET", "POST"])
    @login_required
    def profile():
        user = User.query.get_or_404(session["user_id"])
        if request.method == "POST":
            user.name = request.form["name"].strip()
            password = request.form.get("password", "").strip()
            if password:
                user.set_password(password)
            db.session.commit()
            session["user_name"] = user.name
            flash("프로필이 업데이트되었습니다.", "success")
            return redirect(url_for("profile"))
        return render_template("profile.html", user=user)


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
