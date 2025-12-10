import os
import requests
import json
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import or_, and_, func
from datetime import datetime
from authlib.integrations.flask_client import OAuth
import base64
from io import BytesIO
from PIL import Image

# --- CONFIGURACIÓN ---
app = Flask(__name__)

basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'basket.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'clave_secreta_super_segura'
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024 

# --- GOOGLE KEYS ---
app.config['GOOGLE_CLIENT_ID'] = '706704268052-lhvlruk0fjs8hhma8bk76bv711a4k7ct.apps.googleusercontent.com'
app.config['GOOGLE_CLIENT_SECRET'] = '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'

# --- SETUP ---
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=app.config['GOOGLE_CLIENT_ID'],
    client_secret=app.config['GOOGLE_CLIENT_SECRET'],
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- MODELOS ---
favorites = db.Table('favorites',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('drill_id', db.Integer, db.ForeignKey('drill.id'), primary_key=True)
)

next_practice = db.Table('next_practice',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('drill_id', db.Integer, db.ForeignKey('drill.id'), primary_key=True)
)

drill_primary_tags = db.Table('drill_primary_tags',
    db.Column('drill_id', db.Integer, db.ForeignKey('drill.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)
drill_secondary_tags = db.Table('drill_secondary_tags',
    db.Column('drill_id', db.Integer, db.ForeignKey('drill.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)

class DrillView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    drill_id = db.Column(db.Integer, db.ForeignKey('drill.id'), nullable=False)
    ip_address = db.Column(db.String(50), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=True)
    password_hash = db.Column(db.String(128), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    
    # Preferencia de bloques del usuario
    last_blocks_config = db.Column(db.String(500), nullable=True, default="Calentamiento,Técnica Individual,Tiro,Táctica,Físico,Vuelta a la Calma")

    favoritos = db.relationship('Drill', secondary=favorites, backref=db.backref('favorited_by', lazy='dynamic'))
    mochila = db.relationship('Drill', secondary=next_practice, backref=db.backref('in_practice_plan', lazy='dynamic'))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash: return False
        return check_password_hash(self.password_hash, password)

class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)

class Drill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)
    media_file = db.Column(db.String(120), nullable=True)
    external_link = db.Column(db.String(500), nullable=True)
    is_public = db.Column(db.Boolean, default=True)
    views = db.Column(db.Integer, default=0)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    author = db.relationship('User', backref=db.backref('drills', lazy=True))
    primary_tags = db.relationship('Tag', secondary=drill_primary_tags, backref='primary_drills')
    secondary_tags = db.relationship('Tag', secondary=drill_secondary_tags, backref='secondary_drills')

# --- MODELOS FASE 2 (ENTRENAMIENTOS PRO) ---

class TrainingTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    blocks_structure = db.Column(db.String(500), nullable=False)

class TrainingPlan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False) 
    date = db.Column(db.DateTime, default=datetime.utcnow)
    team_name = db.Column(db.String(100), nullable=True) 
    notes = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Estructura de bloques
    structure = db.Column(db.String(500), nullable=True) 
    
    # NUEVO: Para compartir (WhatsApp/Mail)
    is_public = db.Column(db.Boolean, default=False)

    items = db.relationship('TrainingItem', backref='plan', lazy=True, cascade="all, delete-orphan")

class TrainingItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    training_plan_id = db.Column(db.Integer, db.ForeignKey('training_plan.id'), nullable=False)
    drill_id = db.Column(db.Integer, db.ForeignKey('drill.id'), nullable=False)
    
    block_name = db.Column(db.String(50), nullable=False)
    order = db.Column(db.Integer, default=0)
    notes = db.Column(db.String(200), nullable=True)

    drill = db.relationship('Drill')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- FILTROS ---
@app.template_filter('youtube_thumb')
def youtube_thumb(url):
    if not url: return None
    vid_id = None
    if 'youtu.be' in url: vid_id = url.split('/')[-1]
    elif 'v=' in url: vid_id = url.split('v=')[1].split('&')[0]
    if vid_id: return f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg"
    return None

@app.template_filter('is_video')
def is_video(filename):
    if not filename: return False
    ext = filename.split('.')[-1].lower()
    return ext in ['mp4', 'mov', 'avi']

@app.template_filter('get_youtube_id')
def get_youtube_id(url):
    if not url: return None
    if 'youtu.be' in url: return url.split('/')[-1]
    if 'youtube.com' in url and 'v=' in url: return url.split('v=')[1].split('&')[0]
    return None

# --- RUTAS ---
@app.route('/')
def home():
    query = request.args.get('q', '').strip()
    primary_id = request.args.get('primary', '')
    filter_type = request.args.getlist('filter_type')
    sort_by = request.args.get('sort_by', 'favs_desc') 
    
    if current_user.is_authenticated:
        base_condition = or_(Drill.is_public == True, Drill.user_id == current_user.id)
    else:
        base_condition = (Drill.is_public == True)

    drills_query = Drill.query.filter(base_condition)
    
    if filter_type:
        conditions = []
        if current_user.is_authenticated:
            if 'my_private' in filter_type: conditions.append(and_(Drill.user_id == current_user.id, Drill.is_public == False))
            if 'my_public' in filter_type: conditions.append(and_(Drill.user_id == current_user.id, Drill.is_public == True))
            if 'others' in filter_type: conditions.append(and_(Drill.user_id != current_user.id, Drill.is_public == True))
            if 'favorites' in filter_type:
                fav_ids = [d.id for d in current_user.favoritos]
                conditions.append(Drill.id.in_(fav_ids) if fav_ids else Drill.id == -1)
            if 'next_practice' in filter_type:
                practice_ids = [d.id for d in current_user.mochila]
                conditions.append(Drill.id.in_(practice_ids) if practice_ids else Drill.id == -1)
        if conditions: drills_query = drills_query.filter(or_(*conditions))

    if query: drills_query = drills_query.filter(or_(Drill.title.ilike(f'%{query}%'), Drill.description.ilike(f'%{query}%')))
    if primary_id and primary_id.isdigit(): drills_query = drills_query.filter(Drill.primary_tags.any(id=int(primary_id)))

    if sort_by == 'views_desc': drills_query = drills_query.order_by(Drill.views.desc())
    elif sort_by == 'favs_desc': drills_query = drills_query.outerjoin(favorites).group_by(Drill.id).order_by(func.count(favorites.c.user_id).desc())
    elif sort_by == 'name_asc': drills_query = drills_query.order_by(Drill.title.asc())
    elif sort_by == 'date_asc': drills_query = drills_query.order_by(Drill.date_posted.asc())
    else: drills_query = drills_query.order_by(Drill.date_posted.desc())

    drills = drills_query.all()
    tags = Tag.query.order_by(Tag.name).all()
    return render_template('index.html', drills=drills, tags=tags)

@app.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    tags = Tag.query.order_by(Tag.name).all()
    if request.method == 'POST':
        title = request.form['titulo']
        desc = request.form['descripcion']
        is_public = 'is_public' in request.form
        external_link = request.form.get('external_link', '').strip()
        nuevo = Drill(title=title, description=desc, is_public=is_public, user_id=current_user.id, external_link=external_link)

        file = request.files.get('archivo')
        pasted_image = request.form.get('pasted_image')
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            nuevo.media_file = filename
        elif pasted_image:
            header, encoded = pasted_image.split(",", 1)
            data = base64.b64decode(encoded)
            filename = f"pasted_{int(datetime.now().timestamp())}.png"
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            with open(path, "wb") as f: f.write(data)
            nuevo.media_file = filename

        ids_p = request.form.getlist('primary_tags')
        for t_id in ids_p:
            tag = Tag.query.get(int(t_id))
            if tag: nuevo.primary_tags.append(tag)
        db.session.add(nuevo)
        db.session.commit()
        return redirect('/')
    return render_template('create.html', etiquetas=tags)

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_drill(id):
    drill = Drill.query.get_or_404(id)
    if drill.user_id != current_user.id and not current_user.is_admin:
        flash('No tienes permiso para editar este ejercicio.')
        return redirect('/')

    tags = Tag.query.order_by(Tag.name).all()

    if request.method == 'POST':
        drill.title = request.form['titulo']
        drill.description = request.form['descripcion']
        drill.is_public = 'is_public' in request.form
        drill.external_link = request.form.get('external_link', '').strip()

        drill.primary_tags = [] 
        ids_p = request.form.getlist('primary_tags')
        for t_id in ids_p:
            tag = Tag.query.get(int(t_id))
            if tag: drill.primary_tags.append(tag)
            
        file = request.files.get('archivo')
        pasted_image = request.form.get('pasted_image')
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            drill.media_file = filename
        elif pasted_image:
            header, encoded = pasted_image.split(",", 1)
            data = base64.b64decode(encoded)
            filename = f"pasted_{int(datetime.now().timestamp())}.png"
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            with open(path, "wb") as f: f.write(data)
            drill.media_file = filename

        db.session.commit()
        return redirect('/')

    return render_template('edit_drill.html', drill=drill, etiquetas=tags)

# --- NUEVA RUTA FASE 2: CONFIGURADOR DE ENTRENO ---
@app.route('/create_plan', methods=['GET', 'POST'])
@login_required
def create_plan():
    STANDARD_BLOCKS = "Calentamiento,Técnica Individual,Tiro,Táctica,Físico,Vuelta a la Calma"

    if request.method == 'POST':
        name = request.form.get('name')
        team = request.form.get('team')
        date_str = request.form.get('date')
        notes = request.form.get('notes')
        blocks_csv = request.form.get('blocks_csv')

        current_user.last_blocks_config = blocks_csv
        
        plan_date = datetime.strptime(date_str, '%Y-%m-%d') if date_str else datetime.utcnow()
        new_plan = TrainingPlan(
            name=name,
            team_name=team,
            date=plan_date,
            notes=notes,
            structure=blocks_csv, 
            user_id=current_user.id,
            is_public=False # Por defecto privado
        )
        db.session.add(new_plan)
        db.session.commit()
        
        return redirect('/')

    user_blocks = current_user.last_blocks_config if current_user.last_blocks_config else STANDARD_BLOCKS
    blocks_list = user_blocks.split(',')
    
    return render_template('create_plan.html', blocks=blocks_list, standard_blocks=STANDARD_BLOCKS)

@app.route('/drill/<int:id>')
def view_drill(id):
    drill = Drill.query.get_or_404(id)
    if not drill.is_public:
        if not current_user.is_authenticated or drill.user_id != current_user.id:
            return redirect('/')

    user_ip = request.remote_addr
    existing_view = DrillView.query.filter_by(drill_id=id, ip_address=user_ip).first()
    if not existing_view:
        drill.views += 1
        new_view = DrillView(drill_id=id, ip_address=user_ip)
        db.session.add(new_view)
        db.session.commit()

    media_type = 'none'
    if drill.media_file:
        ext = drill.media_file.split('.')[-1].lower()
        if ext in ['mp4', 'mov', 'avi']: media_type = 'video_file'
        else: media_type = 'image_file'
    elif drill.external_link:
        if 'youtu' in drill.external_link: media_type = 'youtube'
        else: media_type = 'link'
    return render_template('view_drill_modal.html', drill=drill, media_type=media_type)

@app.route('/toggle_fav/<int:id>')
@login_required
def toggle_fav(id):
    drill = Drill.query.get(id)
    if drill:
        if drill in current_user.favoritos: current_user.favoritos.remove(drill)
        else: current_user.favoritos.append(drill)
        db.session.commit()
    return redirect(request.referrer)

@app.route('/toggle_practice/<int:id>')
@login_required
def toggle_practice(id):
    drill = Drill.query.get(id)
    if drill:
        if drill in current_user.mochila: current_user.mochila.remove(drill)
        else: current_user.mochila.append(drill)
        db.session.commit()
    return redirect(request.referrer)

@app.route('/clear_practice')
@login_required
def clear_practice():
    current_user.mochila = []
    db.session.commit()
    return redirect('/')

@app.route('/delete/<int:id>')
@login_required
def delete_drill(id):
    drill = Drill.query.get(id)
    if drill and (drill.user_id == current_user.id or current_user.is_admin):
        db.session.delete(drill)
        db.session.commit()
    return redirect('/')

# --- AUTH ROUTES ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect('/')
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        name = request.form['name']
        
        if User.query.filter_by(email=email).first():
            flash('Ese email ya existe')
            return redirect('/register')
            
        new_user = User(email=email, name=name)
        new_user.set_password(password)
        if email.lower() == 'jcaplliure@gmail.com': new_user.is_admin = True
        
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        return redirect('/')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect('/')
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect('/')
        else:
            flash('Email o contraseña incorrectos')
    return render_template('login.html')

@app.route('/login/google')
def google_login():
    redirect_uri = url_for('google_auth', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/callback')
def google_auth():
    token = google.authorize_access_token()
    user_info = token['userinfo']
    email = user_info['email']
    name = user_info.get('name', email.split('@')[0])
    user = User.query.filter_by(email=email).first()
    if not user:
        is_admin = (email.lower() == 'jcaplliure@gmail.com')
        user = User(email=email, name=name, is_admin=is_admin)
        db.session.add(user)
        db.session.commit()
    login_user(user)
    return redirect('/')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')

# --- ZONA DE ADMINISTRACIÓN ---
@app.route('/admin', methods=['GET'])
@login_required
def admin_panel():
    if not current_user.is_admin:
        return redirect('/')
    return redirect('/admin/tags')

@app.route('/admin/tags', methods=['GET', 'POST'])
@login_required
def manage_tags():
    if not current_user.is_admin: return redirect('/')
    
    if request.method == 'POST':
        tag_name = request.form.get('tag_name').strip()
        if tag_name:
            existing = Tag.query.filter_by(name=tag_name).first()
            if not existing:
                db.session.add(Tag(name=tag_name))
                db.session.commit()
            else:
                flash('Esa etiqueta ya existe.')
    
    tags = Tag.query.order_by(Tag.name).all()
    return render_template('admin_tags.html', tags=tags)

@app.route('/admin/delete_tag/<int:id>')
@login_required
def delete_tag(id):
    if not current_user.is_admin: return redirect('/')
    tag = Tag.query.get(id)
    if tag:
        db.session.delete(tag)
        db.session.commit()
    return redirect('/admin/tags')

@app.route('/admin/config', methods=['GET', 'POST'])
@login_required
def admin_config():
    if not current_user.is_admin: return redirect('/')
    
    if request.method == 'POST':
        file = request.files.get('default_image')
        if file:
            filename = 'default_link_image.jpg'
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(path)
            return redirect(url_for('admin_config', updated=datetime.now().timestamp()))

    return render_template('admin_config.html')

def crear_datos_prueba():
    if Tag.query.count() == 0:
        lista = ["Tiro", "Entrada", "Pase", "Bote", "Defensa", "Rebote", "Físico", "Táctica"]
        for n in lista: db.session.add(Tag(name=n))
        db.session.commit()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        crear_datos_prueba()
    app.run(debug=True)