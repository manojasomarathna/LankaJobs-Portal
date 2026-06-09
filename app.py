import os
import requests as http_requests
from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from models import db, User, Job, Application

JOOBLE_API_KEY  = '04fdd77e-720e-4ad3-a47a-ae9e69184dc0'
JOOBLE_API_URL  = f'https://jooble.org/api/{JOOBLE_API_KEY}'
REMOTEOK_API_URL = 'https://remoteok.com/api'

app = Flask(__name__)
app.config['SECRET_KEY'] = 'lankajobs-secret-key-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///lankajobs.db'
app.config['UPLOAD_FOLDER'] = 'uploads/cvs'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ─── Home ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    jobs = Job.query.order_by(Job.created_at.desc()).limit(6).all()
    return render_template('index.html', jobs=jobs)

# ─── Auth ────────────────────────────────────────────────────────────────────

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

# ─── Dashboard (role-based) ──────────────────────────────────────────────────

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

# ─── Jobs ────────────────────────────────────────────────────────────────────

@app.route('/jobs')
def jobs():
    query = request.args.get('q', '')
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

# ─── Apply ───────────────────────────────────────────────────────────────────

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

# ─── Applicants (employer) ───────────────────────────────────────────────────

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

# ─── Profile ─────────────────────────────────────────────────────────────────

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.name = request.form['name']
        if request.form['password']:
            current_user.password = generate_password_hash(request.form['password'])
        db.session.commit()
        flash('Profile updated.', 'success')
    return render_template('profile.html')

# ─── Admin: delete user ───────────────────────────────────────────────────────

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

# ─── External Jobs ───────────────────────────────────────────────────────────

def fetch_remoteok_jobs(keyword='', page=1):
    try:
        resp = http_requests.get(
            REMOTEOK_API_URL,
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=10
        )
        data = resp.json()
        jobs = [j for j in data if isinstance(j, dict) and 'position' in j]

        if keyword:
            kw = keyword.lower()
            jobs = [j for j in jobs
                    if kw in j.get('position', '').lower()
                    or kw in j.get('company', '').lower()
                    or any(kw in t.lower() for t in j.get('tags', []))]

        per_page = 20
        total    = len(jobs)
        start    = (page - 1) * per_page
        jobs     = jobs[start:start + per_page]

        normalized = []
        for j in jobs:
            normalized.append({
                'title':   j.get('position', ''),
                'company': j.get('company', ''),
                'location': j.get('location', 'Worldwide 🌍'),
                'salary':  j.get('salary', ''),
                'snippet': j.get('description', '')[:200] if j.get('description') else '',
                'link':    j.get('url', f"https://remoteok.com/remote-jobs/{j.get('id', '')}"),
                'tags':    j.get('tags', [])[:4],
                'date':    j.get('date', '')[:10] if j.get('date') else '',
                'source':  'RemoteOK'
            })
        return normalized, total
    except Exception:
        return [], 0


def fetch_jooble_jobs(keyword='developer', location='', page=1):
    try:
        resp = http_requests.post(
            JOOBLE_API_URL,
            json={'keywords': keyword, 'location': location, 'page': page},
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        data = resp.json()
        jobs = []
        for j in data.get('jobs', []):
            jobs.append({
                'title':   j.get('title', ''),
                'company': j.get('company', ''),
                'location': j.get('location', ''),
                'salary':  j.get('salary', ''),
                'snippet': j.get('snippet', '')[:200],
                'link':    j.get('link', ''),
                'tags':    [],
                'date':    j.get('updated', '')[:10] if j.get('updated') else '',
                'source':  'Jooble'
            })
        return jobs, data.get('totalCount', 0)
    except Exception:
        return [], 0


@app.route('/external-jobs')
def external_jobs():
    keyword  = request.args.get('q', '')
    location = request.args.get('location', '')
    source   = request.args.get('source', 'remoteok')
    page     = int(request.args.get('page', 1))
    ext_jobs = []
    total    = 0
    error    = None

    if source == 'jooble':
        ext_jobs, total = fetch_jooble_jobs(keyword or 'developer', location, page)
    else:
        ext_jobs, total = fetch_remoteok_jobs(keyword, page)

    if not ext_jobs and not error:
        error = 'No jobs found. Try different keywords.' if keyword else None

    return render_template('external_jobs.html',
                           ext_jobs=ext_jobs,
                           keyword=keyword,
                           location=location,
                           source=source,
                           page=page,
                           total=total,
                           error=error)

# ─── Init & Run ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Create default admin
        if not User.query.filter_by(role='admin').first():
            admin = User(name='Admin', email='admin@lankajobs.lk',
                         password=generate_password_hash('admin123'), role='admin')
            db.session.add(admin)
            db.session.commit()
    app.run(debug=True)
