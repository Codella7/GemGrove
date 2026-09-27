from datetime import date, datetime, timedelta
import json
from functools import wraps
import re
import os
import click
from uuid import uuid4

from flask import flash, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app import app, db
from app.models import Customer, LedgerEntry, PushSubscription, User
from app.whatsapp import send_reminder

GEMSTONE_PRODUCTS = ("Blue Sapphire", "Yellow Sapphire", "Ruby", "Emerald", "Diamond", "Mix")
CURRENCIES = {
    "INR": "Indian rupees (INR)",
    "LKR": "Sri Lankan rupees (LKR)",
    "THB": "Thai baht (THB)",
    "USD": "US dollars (USD)",
    "HKD": "Hong Kong dollars (HKD)",
}
PLACE_CURRENCIES = {
    "Bangkok": ("THB", "USD"),
    "Hongkok": ("HKD",),
    "Sri Lanka": ("LKR",),
    "India": ("INR",),
}


def format_currency(amount, currency="INR"):
    """Show a monetary value with an unambiguous currency label."""
    return f"{currency if currency in CURRENCIES else 'INR'} {amount:,.2f}"


def totals_by_currency(entries, condition=lambda entry: True):
    totals = {}
    for entry in entries:
        if condition(entry):
            currency = entry.currency if entry.currency in CURRENCIES else "INR"
            totals[currency] = totals.get(currency, 0) + entry.total_price
    return totals


def normalise_whatsapp_number(value):
    number = re.sub(r"[\s()-]", "", value.strip())
    if number.startswith("00"):
        number = "+" + number[2:]
    if not re.fullmatch(r"\+[1-9]\d{7,14}", number):
        raise ValueError("Use the full WhatsApp number with country code, for example +919876543210.")
    return number


def hajiyar_name_key(name):
    """Return the case-insensitive key used to group Hajiyar names."""
    return name.casefold()


def customer_for_name(user_id, name):
    """Find a registered customer without treating capitalization as distinct."""
    key = hajiyar_name_key(name)
    return next(
        (
            customer
            for customer in Customer.query.filter_by(user_id=user_id).order_by(Customer.id).all()
            if hajiyar_name_key(customer.name) == key
        ),
        None,
    )


def save_gem_image(upload):
    """Validate and save a small raster image with a generated filename."""
    if not upload or not upload.filename:
        return None
    signature = upload.stream.read(16)
    upload.stream.seek(0)
    if signature.startswith(b"\xff\xd8\xff"):
        extension = "jpg"
    elif signature.startswith(b"\x89PNG\r\n\x1a\n"):
        extension = "png"
    elif signature.startswith(b"RIFF") and signature[8:12] == b"WEBP":
        extension = "webp"
    else:
        raise ValueError("Upload a JPEG, PNG, or WebP image of the gemstone.")
    filename = f"{uuid4().hex}.{extension}"
    upload.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    return filename


def delete_gem_image(filename):
    if not filename:
        return
    image_path = os.path.join(app.config["UPLOAD_FOLDER"], os.path.basename(filename))
    if os.path.isfile(image_path):
        os.remove(image_path)


def current_user():
    return db.session.get(User, session["user_id"]) if session.get("user_id") else None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Please log in to access GemGrove.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_current_user():
    user = current_user()
    reminder_counts = {"due": 0, "overdue": 0}
    if user:
        today = date.today()
        base_query = LedgerEntry.query.filter(
            LedgerEntry.user_id == user.id,
            LedgerEntry.status != "Paid",
            LedgerEntry.due_date.isnot(None),
        )
        reminder_counts["due"] = base_query.filter(LedgerEntry.due_date >= today).count()
        reminder_counts["overdue"] = base_query.filter(LedgerEntry.due_date < today).count()
    return {
        "current_user": user,
        "money": format_currency,
        "currency_names": CURRENCIES,
        "place_currencies": PLACE_CURRENCIES,
        "reminder_counts": reminder_counts,
    }


@app.route("/")
def home():
    return redirect(url_for("dashboard" if current_user() else "login"))


@app.get("/service-worker.js")
def service_worker():
    response = send_from_directory(app.static_folder, "service-worker.js", mimetype="application/javascript")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/push/vapid-public-key")
@login_required
def push_vapid_public_key():
    if not all(app.config[key] for key in ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT")):
        return jsonify(error="Push notifications are not configured on this server."), 503
    return jsonify(publicKey=app.config["VAPID_PUBLIC_KEY"])


@app.post("/push/subscriptions")
@login_required
def save_push_subscription():
    payload = request.get_json(silent=True) or {}
    keys = payload.get("keys") or {}
    endpoint = payload.get("endpoint", "")
    p256dh, auth = keys.get("p256dh", ""), keys.get("auth", "")
    if not endpoint.startswith("https://") or not p256dh or not auth:
        return jsonify(error="The browser supplied an invalid push subscription."), 400

    subscription = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if subscription is None:
        subscription = PushSubscription(endpoint=endpoint)
    subscription.user_id = current_user().id
    subscription.p256dh, subscription.auth = p256dh, auth
    subscription.due_reminder_sent_on = None
    db.session.add(subscription)
    db.session.commit()
    return jsonify(ok=True)


@app.delete("/push/subscriptions")
@login_required
def delete_push_subscription():
    endpoint = (request.get_json(silent=True) or {}).get("endpoint", "")
    if endpoint:
        PushSubscription.query.filter_by(endpoint=endpoint, user_id=current_user().id).delete()
        db.session.commit()
    return jsonify(ok=True)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        number = ""
        if len(username) < 3:
            flash("Username must have at least 3 characters.", "error")
        elif "@" not in email:
            flash("Enter a valid email address.", "error")
        elif len(password) < 8:
            flash("Password must have at least 8 characters.", "error")
        elif password != request.form.get("confirm_password", ""):
            flash("Passwords do not match.", "error")
        elif User.query.filter(db.or_(User.username == username, User.email == email)).first():
            flash("That username or email is already registered.", "error")
        else:
            user = User(username=username, email=email, whatsapp_number=number, password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            session.clear()
            session["user_id"] = user.id
            flash("Your account has been created.", "success")
            return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip().lower()
        user = User.query.filter(db.or_(User.email == identifier, User.username == identifier)).first()
        if not user or not check_password_hash(user.password_hash, request.form.get("password", "")):
            flash("Incorrect username/email or password.", "error")
        else:
            session.clear()
            session["user_id"] = user.id
            return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    today = date.today()
    greeting = "Good morning" if datetime.now().hour < 12 else "Good afternoon" if datetime.now().hour < 18 else "Good evening"
    entries = LedgerEntry.query.filter_by(user_id=user.id).order_by(LedgerEntry.purchase_date.desc()).all()
    reminders = LedgerEntry.query.filter(LedgerEntry.user_id == user.id, LedgerEntry.status != "Paid", LedgerEntry.due_date.isnot(None), LedgerEntry.due_date <= today + timedelta(days=7)).order_by(LedgerEntry.due_date.asc()).all()
    return render_template("dashboard.html", entries=entries[:5], reminders=reminders, greeting=greeting,
                           total_entries=len(entries), total_carats=sum(x.carat for x in entries),
                           sales_totals=totals_by_currency(entries, lambda x: x.transaction_type == "Sale"),
                           purchases_totals=totals_by_currency(entries, lambda x: x.transaction_type == "Purchase"))


@app.route("/inventory")
@login_required
def inventory():
    return redirect(url_for("transactions"))


@app.route("/transactions")
@login_required
def transactions():
    query = LedgerEntry.query.filter_by(user_id=current_user().id)
    search, place, status = (request.args.get(key, "").strip() for key in ("search", "place", "status"))
    transaction_type = request.args.get("transaction_type", "").strip()
    date_from, date_to = request.args.get("date_from", "").strip(), request.args.get("date_to", "").strip()
    if search:
        query = query.filter(db.or_(LedgerEntry.customer_name.ilike(f"%{search}%"), LedgerEntry.product_name.ilike(f"%{search}%")))
    if place:
        query = query.filter(LedgerEntry.place.ilike(f"%{place}%"))
    if status in {"Due", "Paid"}:
        query = query.filter_by(status=status)
    if transaction_type in {"Purchase", "Sale"}:
        query = query.filter_by(transaction_type=transaction_type)
    if date_from:
        query = query.filter(LedgerEntry.purchase_date >= date_from)
    if date_to:
        query = query.filter(LedgerEntry.purchase_date <= date_to)
    return render_template("transactions.html", entries=query.order_by(LedgerEntry.purchase_date.desc()).all(), filters={"search": search, "place": place, "status": status, "transaction_type": transaction_type, "date_from": date_from, "date_to": date_to})


@app.route("/customers")
@login_required
def customers():
    user = current_user()
    cards_by_name = {}
    for customer in Customer.query.filter_by(user_id=user.id).order_by(Customer.id).all():
        key = hajiyar_name_key(customer.name)
        cards_by_name.setdefault(
            key,
            {"name": customer.name, "entries": 0, "carats": 0, "outstanding": {}, "whatsapp_number": customer.whatsapp_number},
        )
    for entry in LedgerEntry.query.filter_by(user_id=user.id).all():
        key = hajiyar_name_key(entry.customer_name)
        card = cards_by_name.setdefault(
            key,
            {"name": entry.customer_name, "entries": 0, "carats": 0, "outstanding": {}, "whatsapp_number": None},
        )
        card["entries"] += 1
        card["carats"] += entry.carat
        if entry.status != "Paid":
            currency = entry.currency if entry.currency in CURRENCIES else "INR"
            card["outstanding"][currency] = card["outstanding"].get(currency, 0) + entry.total_price
    cards = sorted(cards_by_name.values(), key=lambda card: card["name"].casefold())
    return render_template("customers.html", customers=cards)


@app.route("/customers/new", methods=["GET", "POST"])
@login_required
def new_customer():
    user = current_user()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        number = ""
        if not name:
            flash("Enter the customer's name.", "error")
            return render_template("customer_form.html")
        customer = customer_for_name(user.id, name)
        if customer:
            flash("Customer already registered.", "success")
        else:
            db.session.add(Customer(user_id=user.id, name=name, whatsapp_number=number))
            flash("Customer registered.", "success")
        db.session.commit()
        return redirect(url_for("customers"))
    return render_template("customer_form.html")


@app.route("/customers/<path:customer_name>")
@login_required
def customer_history(customer_name):
    user = current_user()
    name_key = hajiyar_name_key(customer_name)
    entries = [
        entry
        for entry in LedgerEntry.query.filter_by(user_id=user.id).all()
        if hajiyar_name_key(entry.customer_name) == name_key
    ]
    entries.sort(key=lambda entry: entry.purchase_date, reverse=True)
    customer = customer_for_name(user.id, customer_name)
    display_name = customer.name if customer else (entries[0].customer_name if entries else customer_name)
    return render_template("customer_history.html", customer_name=display_name, entries=entries, total_carats=sum(x.carat for x in entries), total_values=totals_by_currency(entries), outstanding_totals=totals_by_currency(entries, lambda x: x.status != "Paid"), customer=customer)


@app.route("/transactions/new", methods=["GET", "POST"])
@login_required
def new_transaction():
    user = current_user()
    if request.method == "POST":
        try:
            carat, price = float(request.form["carat"]), float(request.form["price_per_carat"])
            total_price = float(request.form["total_price"])
            pieces = int(request.form["pieces"])
            purchase_date = date.fromisoformat(request.form["purchase_date"])
            due_value = request.form.get("due_date", "")
            due_date = date.fromisoformat(due_value) if due_value else None
        except (KeyError, TypeError, ValueError):
            flash("Enter valid numbers and dates before saving.", "error")
            return render_template("transaction_form.html", entry=None, today=date.today(), products=GEMSTONE_PRODUCTS)
        product, party, place = request.form["product_name"].strip(), request.form["customer_name"].strip(), request.form.get("place", "").strip()
        transaction_type = request.form.get("transaction_type", "")
        if product not in GEMSTONE_PRODUCTS or not party or transaction_type not in {"Purchase", "Sale"} or place not in PLACE_CURRENCIES:
            flash("Enter a customer and choose a gemstone, transaction type, and place.", "error")
            return render_template("transaction_form.html", entry=None, today=date.today(), products=GEMSTONE_PRODUCTS)
        currency = request.form.get("currency", "").strip()
        if currency not in PLACE_CURRENCIES[place]:
            flash("Choose a currency available for the selected place.", "error")
            return render_template("transaction_form.html", entry=None, today=date.today(), products=GEMSTONE_PRODUCTS)
        try:
            image_filename = save_gem_image(request.files.get("gem_image"))
        except ValueError as error:
            flash(str(error), "error")
            return render_template("transaction_form.html", entry=None, today=date.today(), products=GEMSTONE_PRODUCTS)
        db.session.add(LedgerEntry(user_id=user.id, customer_name=party, transaction_type=transaction_type, product_name=product, image_filename=image_filename, place=place, pieces=pieces, carat=carat, price_per_carat=price, total_price=total_price, currency=currency, purchase_date=purchase_date, due_date=due_date, status="Due", notes=request.form.get("notes", "").strip()))
        db.session.commit()
        flash("Entry saved.", "success")
        return redirect(url_for("transactions"))
    return render_template("transaction_form.html", entry=None, today=date.today(), products=GEMSTONE_PRODUCTS)


@app.route("/transactions/<int:entry_id>/edit", methods=["GET", "POST"])
@login_required
def edit_transaction(entry_id):
    entry = owned_entry_or_404(entry_id)
    if request.method == "POST":
        try:
            carat, price = float(request.form["carat"]), float(request.form["price_per_carat"])
            total_price = float(request.form["total_price"])
            pieces = int(request.form["pieces"])
            transaction_date = date.fromisoformat(request.form["purchase_date"])
            due_value = request.form.get("due_date", "")
            due_date = date.fromisoformat(due_value) if due_value else None
        except (KeyError, TypeError, ValueError):
            flash("Enter valid numbers and dates before saving.", "error")
            return render_template("transaction_form.html", entry=entry, today=date.today(), products=GEMSTONE_PRODUCTS)
        product, party, place = request.form["product_name"].strip(), request.form["customer_name"].strip(), request.form.get("place", "").strip()
        transaction_type = request.form.get("transaction_type", "")
        if product not in GEMSTONE_PRODUCTS or not party or transaction_type not in {"Purchase", "Sale"} or place not in PLACE_CURRENCIES:
            flash("Enter a contact and choose a transaction type, gemstone, and place.", "error")
            return render_template("transaction_form.html", entry=entry, today=date.today(), products=GEMSTONE_PRODUCTS)
        currency = request.form.get("currency", "").strip()
        if currency not in PLACE_CURRENCIES[place]:
            flash("Choose a currency available for the selected place.", "error")
            return render_template("transaction_form.html", entry=entry, today=date.today(), products=GEMSTONE_PRODUCTS)
        old_image = entry.image_filename
        try:
            uploaded_image = save_gem_image(request.files.get("gem_image"))
        except ValueError as error:
            flash(str(error), "error")
            return render_template("transaction_form.html", entry=entry, today=date.today(), products=GEMSTONE_PRODUCTS)
        if uploaded_image:
            entry.image_filename = uploaded_image
        elif request.form.get("remove_image"):
            entry.image_filename = None
        entry.customer_name, entry.transaction_type, entry.product_name, entry.currency = party, transaction_type, product, currency
        entry.place, entry.pieces, entry.carat = place, pieces, carat
        entry.price_per_carat, entry.total_price = price, total_price
        entry.purchase_date, entry.due_date, entry.notes = transaction_date, due_date, request.form.get("notes", "").strip()
        db.session.commit()
        if old_image != entry.image_filename:
            delete_gem_image(old_image)
        flash("Ledger entry updated.", "success")
        return redirect(url_for("transactions"))
    return render_template("transaction_form.html", entry=entry, today=date.today(), products=GEMSTONE_PRODUCTS)


def owned_entry_or_404(entry_id):
    return LedgerEntry.query.filter_by(id=entry_id, user_id=current_user().id).first_or_404()


def dispatch_due_purchase_reminders(report_failure=None):
    """Remind each buyer before an unpaid purchase is due and after it is overdue.

    If the scheduled task did not run the day before, an unpaid purchase is
    still sent on its due date. A separate overdue reminder is sent once after
    the due date if the purchase remains unpaid.
    """
    if not app.config["WHATSAPP_REMINDERS_ENABLED"]:
        return 0

    today = date.today()
    due_entries = LedgerEntry.query.filter(
        LedgerEntry.transaction_type == "Purchase",
        LedgerEntry.status != "Paid",
        LedgerEntry.due_date.isnot(None),
        LedgerEntry.due_date >= today,
        LedgerEntry.due_date <= today + timedelta(days=1),
        LedgerEntry.whatsapp_reminder_sent_at.is_(None),
    ).all()
    overdue_entries = LedgerEntry.query.filter(
        LedgerEntry.transaction_type == "Purchase",
        LedgerEntry.status != "Paid",
        LedgerEntry.due_date.isnot(None),
        LedgerEntry.due_date < today,
        LedgerEntry.whatsapp_overdue_reminder_sent_at.is_(None),
    ).all()
    sent = 0
    for entry in due_entries:
        user = db.session.get(User, entry.user_id)
        try:
            send_reminder(entry, user.whatsapp_number)
        except Exception as error:
            # Leave the entry unsent so the next scheduled run can retry it.
            if report_failure:
                report_failure(entry, error)
            continue
        entry.whatsapp_reminder_sent_at = datetime.utcnow()
        sent += 1
    for entry in overdue_entries:
        user = db.session.get(User, entry.user_id)
        try:
            send_reminder(entry, user.whatsapp_number, overdue=True)
        except Exception as error:
            if report_failure:
                report_failure(entry, error)
            continue
        entry.whatsapp_overdue_reminder_sent_at = datetime.utcnow()
        sent += 1
    if sent:
        db.session.commit()
    return sent


def dispatch_due_payment_pushes(today=None, report_failure=None):
    """Send each subscribed device one summary for due and overdue payments."""
    today = today or date.today()
    if not all(app.config[key] for key in ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT")):
        return 0

    due_entries = LedgerEntry.query.filter(
        LedgerEntry.status != "Paid",
        LedgerEntry.due_date.isnot(None),
        LedgerEntry.due_date <= today,
    ).all()
    due_counts = {}
    overdue_counts = {}
    for entry in due_entries:
        if entry.due_date < today:
            overdue_counts[entry.user_id] = overdue_counts.get(entry.user_id, 0) + 1
        else:
            due_counts[entry.user_id] = due_counts.get(entry.user_id, 0) + 1

    from pywebpush import WebPushException, webpush

    sent = 0
    for user_id in set(due_counts) | set(overdue_counts):
        due_count = due_counts.get(user_id, 0)
        overdue_count = overdue_counts.get(user_id, 0)
        subscriptions = PushSubscription.query.filter_by(user_id=user_id).all()
        for subscription in subscriptions:
            if subscription.due_reminder_sent_on == today:
                continue
            try:
                webpush(
                    subscription_info={
                        "endpoint": subscription.endpoint,
                        "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                    },
                    data=json.dumps({
                        "title": "Payment reminder",
                        "body": "; ".join(filter(None, [
                            f"You have {due_count} unpaid payment{'s' if due_count != 1 else ''} due today." if due_count else "",
                            f"You have {overdue_count} overdue unpaid payment{'s' if overdue_count != 1 else ''}." if overdue_count else "",
                        ])),
                        "url": "/reminders",
                    }),
                    vapid_private_key=app.config["VAPID_PRIVATE_KEY"],
                    vapid_claims={"sub": app.config["VAPID_SUBJECT"]},
                )
            except WebPushException as error:
                response = getattr(error, "response", None)
                if getattr(response, "status_code", None) in {404, 410}:
                    db.session.delete(subscription)
                    db.session.commit()
                elif "invalid p256dh key" in str(error).lower():
                    db.session.delete(subscription)
                    db.session.commit()
                if report_failure:
                    report_failure(subscription, error)
                continue
            except Exception as error:
                if report_failure:
                    report_failure(subscription, error)
                continue

            subscription.due_reminder_sent_on = today
            db.session.commit()
            sent += 1
    return sent


@app.cli.command("send-purchase-reminders")
def send_purchase_reminders_command():
    """Send upcoming purchase reminders to registered account WhatsApp numbers."""
    if not app.config["WHATSAPP_REMINDERS_ENABLED"]:
        click.echo("WhatsApp reminders are paused.")
        return
    failures = []
    sent = dispatch_due_purchase_reminders(
        lambda entry, error: failures.append(f"Entry {entry.id} ({entry.customer_name}): {error}")
    )
    click.echo(f"Sent {sent} upcoming purchase reminder(s).")
    for failure in failures:
        click.echo(f"Failed — {failure}", err=True)
    if failures:
        raise click.ClickException(f"{len(failures)} reminder(s) failed; see the error above.")


@app.cli.command("send-due-payment-pushes")
def send_due_payment_pushes_command():
    """Send daily push summaries to devices with unpaid payments due today."""
    if not all(app.config[key] for key in ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT")):
        click.echo("Push reminders are not configured; set the VAPID environment variables.")
        return
    failures = []
    sent = dispatch_due_payment_pushes(
        report_failure=lambda subscription, error: failures.append(f"Subscription {subscription.id}: {error}")
    )
    click.echo(f"Sent {sent} due-payment push notification(s).")
    for failure in failures:
        click.echo(f"Failed — {failure}", err=True)
    if failures:
        raise click.ClickException(f"{len(failures)} push notification(s) failed; see the error above.")


@app.post("/transactions/<int:entry_id>/paid")
@login_required
def mark_paid(entry_id):
    entry = owned_entry_or_404(entry_id)
    entry.status, entry.payment_date = "Paid", date.today()
    db.session.commit()
    flash(f"Payment recorded for {entry.customer_name}.", "success")
    return redirect(request.referrer or url_for("dashboard"))


@app.post("/transactions/<int:entry_id>/delete")
@login_required
def delete_transaction(entry_id):
    entry = owned_entry_or_404(entry_id)
    image_filename = entry.image_filename
    db.session.delete(entry)
    db.session.commit()
    delete_gem_image(image_filename)
    flash("Entry deleted.", "success")
    return redirect(request.referrer or url_for("transactions"))


@app.route("/reports")
@login_required
def reports():
    entries = LedgerEntry.query.filter_by(user_id=current_user().id).order_by(LedgerEntry.purchase_date.desc()).all()
    return render_template("reports.html", entries=entries, total_values=totals_by_currency(entries))


@app.route("/reminders")
@login_required
def reminders():
    entries = LedgerEntry.query.filter(LedgerEntry.user_id == current_user().id, LedgerEntry.status != "Paid", LedgerEntry.due_date.isnot(None)).order_by(LedgerEntry.due_date.asc()).all()
    return render_template("reminder.html", entries=entries, today=date.today())
