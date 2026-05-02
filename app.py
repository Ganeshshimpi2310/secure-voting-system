from flask import Flask, render_template, request, redirect, session, Response, flash, url_for
import sqlite3
import hashlib
from cryptography.fernet import Fernet
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
try:
    import openai
except ImportError:
    openai = None
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import csv
from io import StringIO
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField
from wtforms.validators import DataRequired, Length, EqualTo
import secrets
import logging
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

def hash_password(password):
    return generate_password_hash(password)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['UPLOAD_FOLDER'] = 'static/images/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///voting.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['WTF_CSRF_ENABLED'] = True

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
limiter = Limiter(get_remote_address, app=app)

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'candidates'), exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'candidates'), exist_ok=True)

# Email configuration (update these with real values or set environment variables)
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USERNAME = os.environ.get('SMTP_USERNAME', 'your-email@gmail.com')  # Replace with your email
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', 'your-app-password')     # Replace with app password
FROM_EMAIL = os.environ.get('FROM_EMAIL', SMTP_USERNAME)
CONTACT_EMAIL = os.environ.get('CONTACT_EMAIL', 'ganeshshimpi9970@gmail.com')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')

# Context processor for logo
@app.context_processor
def inject_logo():
    logo_files = ['logo.png', 'logo.jpg', 'logo.jpeg', 'logo.svg']
    for file in logo_files:
        if os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], file)):
            return {'logo_url': url_for('static', filename=f'images/uploads/{file}')}
    return {'logo_url': url_for('static', filename='images/logo.svg')}

# Encryption key
key = Fernet.generate_key()
cipher = Fernet(key)


def ask_ai(question):
    if not openai or not OPENAI_API_KEY:
        return None
    try:
        openai.api_key = OPENAI_API_KEY
        response = openai.ChatCompletion.create(
            model='gpt-3.5-turbo',
            messages=[
                {'role': 'system', 'content': 'You are a helpful support assistant for a voting application.'},
                {'role': 'user', 'content': question}
            ],
            max_tokens=500,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error('AI assistant failed: %s', e)
        return None

# List of candidates shown in the UI
# Political Parties and their candidates for the Secure Vote System
CANDIDATES = [
    "Progressive Alliance - Sarah Johnson",
    "Progressive Alliance - Michael Chen",
    "National Unity Party - David Rodriguez",
    "National Unity Party - Emma Thompson",
    "Green Future Coalition - James Wilson",
    "Green Future Coalition - Lisa Park",
    "Liberty First Movement - Robert Davis",
    "Liberty First Movement - Maria Gonzalez",
    "People's Democratic Party - Ahmed Hassan",
    "People's Democratic Party - Jennifer Liu"
]

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    has_voted = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    votes = db.relationship('Vote', backref='user', lazy=True)

class Candidate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    votes = db.relationship('Vote', backref='candidate', lazy=True)

class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey('candidate.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Forms
class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=150)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class VoteForm(FlaskForm):
    candidate = SelectField('Candidate', validators=[DataRequired()])
    submit = SubmitField('Vote')

class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Current Password', validators=[DataRequired()])
    new_password = PasswordField('New Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired(), EqualTo('new_password')])
    submit = SubmitField('Change Password')

# ---------------- ROUTES ----------------
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/register', methods=['GET','POST'])
@limiter.limit("5 per minute")
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        username = form.username.data
        password = hash_password(form.password.data)

        if User.query.filter_by(username=username).first():
            flash('That username is already taken.', 'error')
        else:
            is_admin = 1 if username.strip().lower() == "admin" else 0
            user = User(username=username, password=password, is_admin=is_admin)
            db.session.add(user)
            db.session.commit()
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))

    return render_template('register.html', form=form)


@app.route('/login', methods=['GET','POST'])
@limiter.limit("10 per minute")
def login():
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, form.password.data):
            login_user(user)
            return redirect(url_for('vote'))
        else:
            flash('Invalid username or password.', 'error')

    return render_template('login.html', form=form)


@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/assistant', methods=['GET','POST'])
def assistant():
    response = None
    query = None
    if request.method == 'POST':
        query = request.form.get('query', '').strip()
        if query:
            response = ask_ai(query)
            if not response:
                response = (
                    'AI assistant is not configured yet. ' 
                    'Set OPENAI_API_KEY in the environment to enable instant AI answers. ' 
                    'You can also use the "Search online" button to look up your issue from your device.'
                )
    return render_template('assistant.html', response=response, query=query)


@app.route('/contact', methods=['GET','POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        msg = request.form.get('message')

        if name and email and msg:
            try:
                # Send email directly to the configured contact address
                msg_obj = MIMEMultipart()
                msg_obj['From'] = FROM_EMAIL
                msg_obj['To'] = CONTACT_EMAIL
                msg_obj['Reply-To'] = email
                msg_obj['Subject'] = f"Contact Form: {name}"

                body = f"Name: {name}\nEmail: {email}\n\nMessage:\n{msg}"
                msg_obj.attach(MIMEText(body, 'plain'))

                server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
                server.starttls()
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                text = msg_obj.as_string()
                server.sendmail(FROM_EMAIL, CONTACT_EMAIL, text)
                server.quit()

                flash("Thanks! Your message has been sent directly.", 'success')
            except Exception as e: # skipcq: PYL-W0703
                logger.error('Contact form failed: %s', e)
                flash("Sorry, there was an error sending your message. Please try again.", 'error')
        else:
            flash("Please fill in all fields.", 'error')

    return render_template('contact.html')


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not check_password_hash(current_user.password, form.current_password.data):
            flash('Current password is incorrect.', 'error')
        else:
            current_user.password = hash_password(form.new_password.data)
            db.session.commit()
            flash('Password updated successfully!', 'success')

    return render_template('profile.html', form=form, username=current_user.username)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


@app.route('/vote', methods=['GET','POST'])
@login_required
@limiter.limit("60 per minute")
def vote():
    form = VoteForm()
    candidates = [c.name for c in Candidate.query.all()]
    form.candidate.choices = [(c, c) for c in candidates]

    voted = current_user.has_voted
    last_vote = None

    if voted:
        vote_record = Vote.query.filter_by(user_id=current_user.id).first()
        if vote_record:
            last_vote = vote_record.candidate.name

    if form.validate_on_submit() and not voted:
        candidate = Candidate.query.filter_by(name=form.candidate.data).first()
        if candidate:
            vote = Vote(user_id=current_user.id, candidate_id=candidate.id)
            current_user.has_voted = True
            db.session.add(vote)
            db.session.commit()
            voted = True
            last_vote = candidate.name
            flash('Vote submitted successfully!', 'success')
        else:
            flash('Invalid candidate.', 'error')

    # Map each candidate to a candidate image path
    def _slugify(name):
        return ''.join(c for c in name.lower() if c.isalnum() or c == ' ').replace(' ', '-')

    candidate_images = {}
    for candidate in Candidate.query.all():
        # Check for uploaded photo first
        photo_files = ['.png', '.jpg', '.jpeg', '.svg']
        photo_path = None
        for ext in photo_files:
            filename = f"{candidate.name.replace(' ', '_')}{ext}"
            if os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], 'candidates', filename)):
                photo_path = f"images/uploads/candidates/{filename}"
                break
        if not photo_path:
            photo_path = f"images/candidates/{_slugify(candidate.name)}.svg"
        candidate_images[candidate.name] = photo_path

    return render_template(
        'vote.html',
        form=form,
        candidates=candidates,
        candidate_images=candidate_images,
        voted=voted,
        last_vote=last_vote,
    )


@app.route('/results')
def results():
    # Count votes for each candidate
    votes_query = db.session.query(
        Candidate.name,
        db.func.count(Vote.id).label('votes')
    ).outerjoin(Vote).group_by(Candidate.id).order_by(db.desc('votes'), Candidate.name).all()

    # Ensure the results are shown only for the current candidate list (preserves order)
    result = {candidate.name: 0 for candidate in Candidate.query.all()}
    for name, votes in votes_query:
        if name in result:
            result[name] = votes

    # Recent vote history (for dashboard-style display)
    recent = db.session.query(
        User.username,
        Candidate.name,
        Vote.created_at
    ).outerjoin(User, Vote.user_id == User.id).join(Candidate).order_by(Vote.created_at.desc()).limit(12).all()

    total = sum(result.values())
    percents = {
        candidate: int(round((count / total) * 100)) if total > 0 else 0
        for candidate, count in result.items()
    }

    from datetime import datetime

    return render_template(
        'results.html',
        result=result,
        total=total,
        percents=percents,
        recent=recent,
        now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    )


@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        return redirect(url_for('home'))

    # per-user voting records
    user_votes = db.session.query(
        User.username,
        Candidate.name,
        Vote.created_at
    ).join(Vote, Vote.user_id == User.id).join(Candidate).order_by(User.username.asc()).all()

    # Current vote totals
    totals = dict(db.session.query(
        Candidate.name,
        db.func.count(Vote.id)
    ).outerjoin(Vote).group_by(Candidate.id).order_by(db.desc(db.func.count(Vote.id)), Candidate.name).all())

    return render_template('admin.html', user_votes=user_votes, totals=totals)


@app.route('/admin/candidates', methods=['GET', 'POST'])
@login_required
def manage_candidates():
    if not current_user.is_admin:
        return redirect(url_for('home'))

    if request.method == 'POST':
        action = request.form.get('action')
        candidate_name = request.form.get('candidate_name', '').strip()

        if action == 'add' and candidate_name:
            if not Candidate.query.filter_by(name=candidate_name).first():
                candidate = Candidate(name=candidate_name)
                db.session.add(candidate)
                db.session.commit()
                flash('Candidate added.', 'success')
        elif action == 'remove' and candidate_name:
            candidate = Candidate.query.filter_by(name=candidate_name).first()
            if candidate:
                db.session.delete(candidate)
                db.session.commit()
                flash('Candidate removed.', 'success')

    candidates = [c.name for c in Candidate.query.order_by(Candidate.name).all()]

    return render_template('manage_candidates.html', candidates=candidates)


@app.route('/admin/upload-logo', methods=['GET', 'POST'])
@login_required
def upload_logo():
    if not current_user.is_admin:
        return redirect(url_for('home'))

    if request.method == 'POST':
        if 'logo' not in request.files:
            flash('No file selected', 'error')
            return redirect(request.url)
        file = request.files['logo']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)
        if file and allowed_file(file.filename, {'png', 'jpg', 'jpeg', 'svg'}):
            filename = secure_filename('logo.' + file.filename.rsplit('.', 1)[1].lower())
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            flash('Logo uploaded successfully', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid file type. Please upload PNG, JPG, or SVG.', 'error')
            return redirect(request.url)

    return render_template('upload_logo.html')


@app.route('/admin/upload-candidate-photo', methods=['GET', 'POST'])
@login_required
def upload_candidate_photo():
    if not current_user.is_admin:
        return redirect(url_for('home'))

    candidates = [c.name for c in Candidate.query.order_by(Candidate.name).all()]

    if request.method == 'POST':
        candidate_name = request.form.get('candidate')
        if 'photo' not in request.files:
            flash('No file selected', 'error')
            return redirect(request.url)
        file = request.files['photo']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)
        if file and allowed_file(file.filename, {'png', 'jpg', 'jpeg', 'svg'}):
            filename = secure_filename(f"{candidate_name.replace(' ', '_')}.{file.filename.rsplit('.', 1)[1].lower()}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], 'candidates', filename))
            flash('Candidate photo uploaded successfully', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid file type. Please upload PNG, JPG, or SVG.', 'error')
            return redirect(request.url)

    return render_template('upload_candidate_photo.html', candidates=candidates)


@app.route('/export')
@login_required
def export_csv():
    if not current_user.is_admin:
        return redirect(url_for('home'))

    # Get all vote data
    votes = db.session.query(
        User.username,
        Candidate.name,
        Vote.created_at
    ).outerjoin(User, Vote.user_id == User.id).join(Candidate).order_by(Vote.created_at.desc()).all()

    # Get vote totals
    totals = dict(db.session.query(
        Candidate.name,
        db.func.count(Vote.id)
    ).outerjoin(Vote).group_by(Candidate.id).order_by(db.desc(db.func.count(Vote.id)), Candidate.name).all())

    # Create CSV in memory
    output = StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow(['Username', 'Candidate', 'Timestamp'])

    # Write vote data
    for username, candidate, timestamp in votes:
        writer.writerow([username or 'Anonymous', candidate or 'Unknown', timestamp])

    # Add summary
    writer.writerow([])
    writer.writerow(['Summary'])
    writer.writerow(['Candidate', 'Votes'])
    for candidate, count in totals.items():
        writer.writerow([candidate, count])

    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=voting_results.csv'}
    )


def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


@app.route('/api/results')
def api_results():
    # Count votes for each candidate
    votes_query = db.session.query(
        Candidate.name,
        db.func.count(Vote.id).label('votes')
    ).outerjoin(Vote).group_by(Candidate.id).order_by(db.desc('votes'), Candidate.name).all()

    # Ensure the results are shown only for the current candidate list (preserves order)
    result = {candidate.name: 0 for candidate in Candidate.query.all()}
    for name, votes in votes_query:
        if name in result:
            result[name] = votes

    labels = [name.split(' - ')[1] for name in result.keys()]
    data = list(result.values())
    total = sum(data)

    return {'labels': labels, 'data': data, 'total': total}

@app.errorhandler(404)
def page_not_found(error):
    return render_template(
        'error.html',
        code=404,
        title='Page not found',
        message='The page you are looking for does not exist.',
        suggestion='Please check the URL or return to the homepage.'
    ), 404

@app.errorhandler(500)
def internal_server_error(error):
    return render_template(
        'error.html',
        code=500,
        title='Server error',
        message='Something went wrong on our end.',
        suggestion='Try again later or contact support if the issue continues.'
    ), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Ensure candidates table matches the UI list
        for candidate in CANDIDATES:
            if not Candidate.query.filter_by(name=candidate).first():
                db.session.add(Candidate(name=candidate))
        db.session.commit()
    app.run(debug=True)