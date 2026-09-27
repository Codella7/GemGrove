from app import db
from datetime import date, datetime


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    whatsapp_number = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False, unique=True)
    whatsapp_number = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Gem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    quantity = db.Column(db.Float)
    weight = db.Column(db.Float)
    cost_per_unit = db.Column(db.Float)
    purchase_date = db.Column(db.DateTime, default=datetime.utcnow)

    transactions = db.relationship('Transaction', backref='gem', lazy=True)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    gem_id = db.Column(db.Integer, db.ForeignKey('gem.id'), nullable=False)
    type = db.Column(db.String(10))  # "buy" or "sell"
    quantity = db.Column(db.Float)
    price_per_unit = db.Column(db.Float)
    total_amount = db.Column(db.Float)
    date = db.Column(db.DateTime, default=datetime.utcnow)

class Reminder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    gem_name = db.Column(db.String(100))
    due_date = db.Column(db.DateTime)
    note = db.Column(db.String(255))
    is_sent = db.Column(db.Boolean, default=False)


class LedgerEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    customer_name = db.Column(db.String(120), nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False, default="Sale")
    product_name = db.Column(db.String(120), nullable=False)
    image_filename = db.Column(db.String(255))
    place = db.Column(db.String(120))
    pieces = db.Column(db.Integer, nullable=False, default=1)
    carat = db.Column(db.Float, nullable=False, default=0)
    price_per_carat = db.Column(db.Float, nullable=False, default=0)
    total_price = db.Column(db.Float, nullable=False, default=0)
    currency = db.Column(db.String(3), nullable=False, default="INR")
    purchase_date = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date)
    payment_date = db.Column(db.Date)
    whatsapp_reminder_sent_at = db.Column(db.DateTime)
    status = db.Column(db.String(20), nullable=False, default="Due")
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    whatsapp_overdue_reminder_sent_at = db.Column(db.DateTime)


class PushSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    endpoint = db.Column(db.Text, nullable=False, unique=True)
    p256dh = db.Column(db.String(255), nullable=False)
    auth = db.Column(db.String(255), nullable=False)
    due_reminder_sent_on = db.Column(db.Date)
