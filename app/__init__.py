from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os
import os


def get_environment_setting(name):
	value = os.environ.get(name)
	if value or os.name != "nt":
		return value or ""
	import winreg

	try:
		with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
			return winreg.QueryValueEx(key, name)[0]
	except FileNotFoundError:
		return ""

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'gemgrove-development-key')

# Config for SQLite
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, '../gemapp.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'uploads')
# Keep the delivery integration off while it is paused. Its stored data and
# implementation remain intact so it can be restored later.
app.config['WHATSAPP_REMINDERS_ENABLED'] = False
app.config['VAPID_PUBLIC_KEY'] = os.environ.get('VAPID_PUBLIC_KEY', '')
app.config['VAPID_PUBLIC_KEY'] = get_environment_setting('VAPID_PUBLIC_KEY')
app.config['VAPID_PRIVATE_KEY'] = get_environment_setting('VAPID_PRIVATE_KEY')
app.config['VAPID_SUBJECT'] = get_environment_setting('VAPID_SUBJECT')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
from app import routes
from app import models  

with app.app_context():
	db.create_all()
	# Lightweight migration for databases created before purchase/sale entries.
	columns = {column["name"] for column in db.inspect(db.engine).get_columns("ledger_entry")}
	migrations = {
		"transaction_type": "ALTER TABLE ledger_entry ADD COLUMN transaction_type VARCHAR(20) NOT NULL DEFAULT 'Sale'",
		"whatsapp_reminder_sent_at": "ALTER TABLE ledger_entry ADD COLUMN whatsapp_reminder_sent_at DATETIME",
		"whatsapp_overdue_reminder_sent_at": "ALTER TABLE ledger_entry ADD COLUMN whatsapp_overdue_reminder_sent_at DATETIME",
		"image_filename": "ALTER TABLE ledger_entry ADD COLUMN image_filename VARCHAR(255)",
		"currency": "ALTER TABLE ledger_entry ADD COLUMN currency VARCHAR(3) NOT NULL DEFAULT 'INR'",
	}
	for column, statement in migrations.items():
		if column not in columns:
			db.session.execute(db.text(statement))
	db.session.commit()

