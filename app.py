import os
import requests as http_requests
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from models import db, User, Job, Application
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
JOOBLE_API_KEY     = os.getenv('JOOBLE_API_KEY')
JOOBLE_API_URL     = f'https://jooble.org/api/{JOOBLE_API_KEY}'
REMOTEOK_API_URL   = 'https://remoteok.com/api'

app = Flask(__name__)
app.config['SECRET_KEY']              = os.getenv('SECRET_KEY', 'lankajobs-secret-key-2024')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///lankajobs.db'
app.config['UPLOAD_FOLDER']           = 'uploads/cvs'
app.config['MAX_CONTENT_LENGTH']      = 5 * 1024 * 1024

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ─── Home ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    jobs = Job.query.order_by(Job.created_at.desc()).limit(6).all()
    return render_template('index.html', jobs=jobs)

# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name     = request.form['name']
        email    = request.form['email']
        password = request.form['password']
        role     = request.form['role']
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return redirect(url_for('register'))
        user = User(name=name, email=email,
                    password=generate_password_hash(password), role=role)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid credentials.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# ─── Dashboard ────────────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        users = User.query.all()
        jobs  = Job.query.all()
        apps  = Application.query.all()
        return render_template('dashboard.html', users=users, jobs=jobs, apps=apps)
    elif current_user.role == 'employer':
        jobs = Job.query.filter_by(posted_by=current_user.id).all()
        return render_template('dashboard.html', jobs=jobs)
    else:
        apps = Application.query.filter_by(user_id=current_user.id).all()
        return render_template('dashboard.html', apps=apps)

# ─── Jobs ─────────────────────────────────────────────────────────────────────

@app.route('/jobs')
def jobs():
    query    = request.args.get('q', '')
    location = request.args.get('location', '')
    job_list = Job.query
    if query:
        job_list = job_list.filter(Job.title.ilike(f'%{query}%'))
    if location:
        job_list = job_list.filter(Job.location.ilike(f'%{location}%'))
    job_list = job_list.order_by(Job.created_at.desc()).all()
    return render_template('jobs.html', jobs=job_list, query=query, location=location)


@app.route('/jobs/post', methods=['GET', 'POST'])
@login_required
def post_job():
    if current_user.role != 'employer':
        flash('Only employers can post jobs.', 'danger')
        return redirect(url_for('jobs'))
    if request.method == 'POST':
        job = Job(
            title=request.form['title'],
            company=request.form['company'],
            location=request.form['location'],
            salary=request.form['salary'],
            description=request.form['description'],
            posted_by=current_user.id
        )
        db.session.add(job)
        db.session.commit()
        flash('Job posted successfully!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('post_job.html')


@app.route('/jobs/edit/<int:job_id>', methods=['GET', 'POST'])
@login_required
def edit_job(job_id):
    job = Job.query.get_or_404(job_id)
    if job.posted_by != current_user.id and current_user.role != 'admin':
        flash('Unauthorized.', 'danger')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        job.title       = request.form['title']
        job.company     = request.form['company']
        job.location    = request.form['location']
        job.salary      = request.form['salary']
        job.description = request.form['description']
        db.session.commit()
        flash('Job updated.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('post_job.html', job=job)


@app.route('/jobs/delete/<int:job_id>')
@login_required
def delete_job(job_id):
    job = Job.query.get_or_404(job_id)
    if job.posted_by != current_user.id and current_user.role != 'admin':
        flash('Unauthorized.', 'danger')
        return redirect(url_for('dashboard'))
    db.session.delete(job)
    db.session.commit()
    flash('Job deleted.', 'success')
    return redirect(url_for('dashboard'))

# ─── Apply ────────────────────────────────────────────────────────────────────

@app.route('/jobs/apply/<int:job_id>', methods=['GET', 'POST'])
@login_required
def apply_job(job_id):
    if current_user.role != 'jobseeker':
        flash('Only job seekers can apply.', 'danger')
        return redirect(url_for('jobs'))
    job = Job.query.get_or_404(job_id)
    if Application.query.filter_by(job_id=job_id, user_id=current_user.id).first():
        flash('You already applied for this job.', 'warning')
        return redirect(url_for('jobs'))
    if request.method == 'POST':
        cv_path = None
        if 'cv' in request.files:
            file = request.files['cv']
            if file and allowed_file(file.filename):
                filename = secure_filename(f"{current_user.id}_{job_id}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                cv_path = filename
        app_entry = Application(job_id=job_id, user_id=current_user.id, cv_path=cv_path)
        db.session.add(app_entry)
        db.session.commit()
        flash('Application submitted!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('apply.html', job=job)

# ─── Applicants ───────────────────────────────────────────────────────────────

@app.route('/jobs/<int:job_id>/applicants')
@login_required
def view_applicants(job_id):
    job = Job.query.get_or_404(job_id)
    if job.posted_by != current_user.id and current_user.role != 'admin':
        flash('Unauthorized.', 'danger')
        return redirect(url_for('dashboard'))
    applicants = Application.query.filter_by(job_id=job_id).all()
    return render_template('applicants.html', job=job, applicants=applicants)


@app.route('/applications/status/<int:app_id>/<string:status>')
@login_required
def update_status(app_id, status):
    application = Application.query.get_or_404(app_id)
    job = Job.query.get(application.job_id)
    if job.posted_by != current_user.id and current_user.role != 'admin':
        flash('Unauthorized.', 'danger')
        return redirect(url_for('dashboard'))
    application.status = status
    db.session.commit()
    flash(f'Application {status}.', 'success')
    return redirect(url_for('view_applicants', job_id=job.id))

# ─── Profile ──────────────────────────────────────────────────────────────────

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.name = request.form['name']
        if request.form['password']:
            current_user.password = generate_password_hash(request.form['password'])
        if 'cv' in request.files:
            file = request.files['cv']
            if file and allowed_file(file.filename):
                filename = secure_filename(f"profile_{current_user.id}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                current_user.cv_path = filename
        db.session.commit()
        flash('Profile updated.', 'success')
    return render_template('profile.html')


@app.route('/cv-job-match')
@login_required
def cv_job_match():
    if current_user.role != 'jobseeker':
        flash('Only job seekers can use this feature.', 'danger')
        return redirect(url_for('dashboard'))

    if not current_user.cv_path:
        flash('Please upload your CV in your profile first.', 'warning')
        return redirect(url_for('profile'))

    # Read CV text
    cv_full_path = os.path.join(app.config['UPLOAD_FOLDER'], current_user.cv_path)
    cv_text = ''
    try:
        if current_user.cv_path.endswith('.pdf'):
            import pdfplumber
            with pdfplumber.open(cv_full_path) as pdf:
                cv_text = ' '.join([p.extract_text() or '' for p in pdf.pages])
        else:
            with open(cv_full_path, 'rb') as f:
                cv_text = f.read().decode('utf-8', errors='ignore')[:3000]
    except Exception:
        cv_text = ''

    # Get all jobs from DB
    all_jobs = Job.query.order_by(Job.created_at.desc()).all()
    jobs_list = '\n'.join(
        [f"ID:{j.id} | {j.title} at {j.company}, {j.location} | {j.description[:150]}" for j in all_jobs]
    ) or 'No jobs available.'

    matched_jobs = []
    ai_summary   = ''
    error        = None

    try:
        prompt = f"""Analyze this CV and match it with the available jobs below.
Return a JSON array of matched job IDs with a short reason why each matches.
Format: [{"id": 1, "reason": "..."}]
Only return the JSON, nothing else.

CV Content:
{cv_text[:2000] if cv_text else 'CV text could not be extracted.'}

Available Jobs:
{jobs_list}"""

        resp = http_requests.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers={'Authorization': f'Bearer {OPENROUTER_API_KEY}',
                     'Content-Type': 'application/json'},
            json={'model': 'google/gemma-4-31b-it:free',
                  'messages': [{'role': 'user', 'content': prompt}]},
            timeout=30
        )
        import json, re
        ai_text = resp.json()['choices'][0]['message']['content']
        # Extract JSON from response
        json_match = re.search(r'\[.*?\]', ai_text, re.DOTALL)
        if json_match:
            matches = json.loads(json_match.group())
            for m in matches:
                job = Job.query.get(m.get('id'))
                if job:
                    matched_jobs.append({'job': job, 'reason': m.get('reason', '')})
        ai_summary = ai_text
    except Exception as e:
        error = 'AI matching failed. Showing all jobs instead.'
        matched_jobs = [{'job': j, 'reason': ''} for j in all_jobs]

    return render_template('cv_match.html',
                           matched_jobs=matched_jobs,
                           cv_filename=current_user.cv_path,
                           error=error)

# ─── Admin ────────────────────────────────────────────────────────────────────

@app.route('/admin/delete_user/<int:user_id>')
@login_required
def delete_user(user_id):
    if current_user.role != 'admin':
        flash('Unauthorized.', 'danger')
        return redirect(url_for('dashboard'))
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash('User deleted.', 'success')
    return redirect(url_for('dashboard'))

# ─── External Jobs ────────────────────────────────────────────────────────────

def fetch_remoteok_jobs(keyword='', page=1):
    try:
        resp = http_requests.get(REMOTEOK_API_URL,
                                 headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        data = resp.json()
        jobs = [j for j in data if isinstance(j, dict) and 'position' in j]
        if keyword:
            kw   = keyword.lower()
            jobs = [j for j in jobs
                    if kw in j.get('position', '').lower()
                    or kw in j.get('company', '').lower()
                    or any(kw in t.lower() for t in j.get('tags', []))]
        per_page = 20
        total    = len(jobs)
        jobs     = jobs[(page-1)*per_page : page*per_page]
        return [{
            'title':    j.get('position', ''),
            'company':  j.get('company', ''),
            'location': j.get('location', 'Worldwide 🌍'),
            'salary':   j.get('salary', ''),
            'snippet':  (j.get('description') or '')[:200],
            'link':     j.get('url', f"https://remoteok.com/remote-jobs/{j.get('id','')}"),
            'tags':     j.get('tags', [])[:4],
            'date':     (j.get('date') or '')[:10],
            'source':   'RemoteOK'
        } for j in jobs], total
    except Exception:
        return [], 0


def fetch_jooble_jobs(keyword='developer', location='', page=1):
    try:
        resp = http_requests.post(JOOBLE_API_URL,
                                  json={'keywords': keyword, 'location': location, 'page': page},
                                  headers={'Content-Type': 'application/json'}, timeout=10)
        data = resp.json()
        return [{
            'title':    j.get('title', ''),
            'company':  j.get('company', ''),
            'location': j.get('location', ''),
            'salary':   j.get('salary', ''),
            'snippet':  j.get('snippet', '')[:200],
            'link':     j.get('link', ''),
            'tags':     [],
            'date':     (j.get('updated') or '')[:10],
            'source':   'Jooble'
        } for j in data.get('jobs', [])], data.get('totalCount', 0)
    except Exception:
        return [], 0


@app.route('/external-jobs')
def external_jobs():
    keyword  = request.args.get('q', '')
    location = request.args.get('location', '')
    source   = request.args.get('source', 'remoteok')
    page     = int(request.args.get('page', 1))
    error    = None

    if source == 'jooble':
        ext_jobs, total = fetch_jooble_jobs(keyword or 'developer', location, page)
    else:
        ext_jobs, total = fetch_remoteok_jobs(keyword, page)

    if not ext_jobs:
        error = 'No jobs found. Try different keywords.' if keyword else None

    return render_template('external_jobs.html',
                           ext_jobs=ext_jobs, keyword=keyword, location=location,
                           source=source, page=page, total=total, error=error)

# ─── AI Chatbot ───────────────────────────────────────────────────────────────

@app.route('/chatbot')
def chatbot():
    return render_template('chatbot.html')


@app.route('/chatbot/ask', methods=['POST'])
def chatbot_ask():
    user_msg = request.json.get('message', '').strip()
    if not user_msg:
        return {'reply': 'Please type a message.'}

    jobs = Job.query.order_by(Job.created_at.desc()).limit(10).all()
    jobs_context = '\n'.join(
        [f"- {j.title} at {j.company}, {j.location}, Salary: {j.salary or 'N/A'}" for j in jobs]
    ) or 'No jobs currently posted.'

    system_prompt = f"""You are LankaJobs AI Assistant - a helpful job portal bot for Sri Lanka.
Help users find jobs, write CVs, prepare for interviews, and use the portal.
Be friendly, concise, and helpful. Reply in the same language the user uses (Sinhala or English).

Available jobs on LankaJobs:
{jobs_context}

Portal features: Browse Jobs, Apply Jobs, Post Jobs (employers), Admin Dashboard."""

    try:
        resp = http_requests.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers={'Authorization': f'Bearer {OPENROUTER_API_KEY}',
                     'Content-Type': 'application/json'},
            json={'model': 'google/gemma-4-31b-it:free',
                  'messages': [{'role': 'system', 'content': system_prompt},
                                {'role': 'user',   'content': user_msg}]},
            timeout=20
        )
        reply = resp.json()['choices'][0]['message']['content']
    except Exception:
        reply = 'Sorry, I could not process your request. Please try again.'

    return {'reply': reply}

# ─── Init & Run ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(role='admin').first():
            admin = User(name='Admin', email='admin@lankajobs.lk',
                         password=generate_password_hash('admin123'), role='admin')
            db.session.add(admin)
            db.session.commit()
    app.run(debug=True)
