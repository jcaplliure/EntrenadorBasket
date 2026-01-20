Comenzamos la **Fase 5**. Esta es la actualización más grande que hemos hecho hasta ahora porque cambiamos los cimientos del edificio (la Base de Datos) para permitir todo lo que has pedido: varios entrenadores, sesiones reales, gamificación y rankings.

⚠️ **AVISO IMPORTANTE ANTES DE EMPEZAR:**
Como vamos a cambiar la estructura de la base de datos (añadir tablas de Staff, Sesiones, Puntuaciones, etc.), cuando subas este archivo **tendrás que borrar la base de datos antigua (`rm basket.db`)** y crearla de nuevo, tal como hicimos la última vez. Si no lo haces, dará error porque no encontrará los sitios nuevos donde guardar los datos.

Aquí tienes el **Archivo 1 de 5: `app.py` Completo**.

### 1. Archivo Completo: `app.py`

Incluye:

* **Base de Datos Nueva:** Tablas `TeamStaff`, `TrainingSession`, `SessionAttendance`, `SessionScore`.
* **Lógica Multi-Entrenador:** Rutas para invitar, aceptar y gestionar permisos.
* **Gestión de Equipos:** Ahora puedes editar nombre, logo y configuración de ranking.
* **Gamificación:** Toda la lógica para calcular puntos (15, 14, 13...) y gestionar sesiones.
* **Portal Público:** Ruta para que los jugadores vean el ranking sin login.

```python
import os
import requests
import json
import csv
import io
import uuid
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import or_, and_, func, desc
from datetime import datetime
from authlib.integrations.flask_client import OAuth
from io import BytesIO
from PIL import Image, ImageDraw

app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'basket.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'clave_secreta_super_segura'
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

app.config['GOOGLE_CLIENT_ID'] = '706704268052-lhvlruk0fjs8hhma8bk76bv711a4k7ct.apps.googleusercontent.com'
app.config['GOOGLE_CLIENT_SECRET'] = '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'

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

# --- TABLAS DE RELACIÓN ---
favorites = db.Table('favorites',
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
ranking_ingredients = db.Table('ranking_ingredients',
    db.Column('ranking_id', db.Integer, db.ForeignKey('ranking_definition.id'), primary_key=True),
    db.Column('action_id', db.Integer, db.ForeignKey('action_definition.id'), primary_key=True)
)
match_roster = db.Table('match_roster',
    db.Column('match_id', db.Integer, db.ForeignKey('match.id'), primary_key=True),
    db.Column('player_id', db.Integer, db.ForeignKey('player.id'), primary_key=True)
)

# --- MODELOS ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=True)
    password_hash = db.Column(db.String(128), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    last_blocks_config = db.Column(db.String(500), nullable=True, default="Calentamiento,Técnica Individual,Tiro,Táctica,Físico,Vuelta a la Calma")
    favoritos = db.relationship('Drill', secondary=favorites, backref=db.backref('favorited_by', lazy='dynamic'))
    # Teams owned
    owned_teams = db.relationship('Team', backref='owner', lazy=True)
    # Teams where staff
    staff_memberships = db.relationship('TeamStaff', backref='user', lazy=True)
    
    actions_config = db.relationship('ActionDefinition', backref='owner', lazy=True)
    rankings_config = db.relationship('RankingDefinition', backref='owner', lazy=True)
    matches = db.relationship('Match', backref='coach', lazy=True)

    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password):
        if not self.password_hash: return False
        return check_password_hash(self.password_hash, password)

class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=True)
    logo_file = db.Column(db.String(120), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # Creator/Owner
    
    # Configuración de Ranking Público
    visibility_top_x = db.Column(db.Integer, default=3) # Top 3
    visibility_top_pct = db.Column(db.Integer, default=25) # Top 25%
    visibility_mode = db.Column(db.String(20), default='fixed') # 'fixed' or 'percent'

    players = db.relationship('Player', backref='team', lazy=True, cascade="all, delete-orphan")
    staff = db.relationship('TeamStaff', backref='team', lazy=True, cascade="all, delete-orphan")
    sessions = db.relationship('TrainingSession', backref='team', lazy=True, cascade="all, delete-orphan")

class TeamStaff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # Null if pending
    email = db.Column(db.String(120), nullable=False) # To invite by email
    role = db.Column(db.String(20), default='assistant') # assistant, etc.
    status = db.Column(db.String(20), default='pending') # pending, accepted

class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    dorsal = db.Column(db.Integer, nullable=False)
    photo_file = db.Column(db.String(120), nullable=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)

# --- NUEVOS MODELOS PARA SESIONES Y GAMIFICACIÓN ---
class TrainingSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('training_plan.id'), nullable=True) # Optional link to a plan
    date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='active') # active, finished
    attendance = db.relationship('SessionAttendance', backref='session', lazy=True, cascade="all, delete-orphan")
    scores = db.relationship('SessionScore', backref='session', lazy=True, cascade="all, delete-orphan")

class SessionAttendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('training_session.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    is_present = db.Column(db.Boolean, default=False)

class SessionScore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('training_session.id'), nullable=False)
    drill_id = db.Column(db.Integer, db.ForeignKey('drill.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    raw_score = db.Column(db.Float, default=0.0) # El valor real (ej: 8 canastas)
    points = db.Column(db.Integer, default=0) # Los puntos gamificados (ej: 15 pts)

class ActionDefinition(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    value = db.Column(db.Float, nullable=False) 
    is_positive = db.Column(db.Boolean, default=True) 
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class RankingDefinition(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    icon = db.Column(db.String(50), default="trophy") 
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ingredients = db.relationship('ActionDefinition', secondary=ranking_ingredients, backref='used_in_rankings')

class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    opponent = db.Column(db.String(100), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    is_home = db.Column(db.Boolean, default=True)
    result_us = db.Column(db.Integer, default=0)
    result_them = db.Column(db.Integer, default=0)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False) 
    roster = db.relationship('Player', secondary=match_roster, backref='matches_played')
    events = db.relationship('MatchEvent', backref='match', lazy=True, cascade="all, delete-orphan")

class MatchEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    action_id = db.Column(db.Integer, db.ForeignKey('action_definition.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    game_minute = db.Column(db.Integer, default=0) 

class SiteConfig(db.Model):
    key = db.Column(db.String(50), primary_key=True) 
    value = db.Column(db.String(255), nullable=False) 

class DrillView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    drill_id = db.Column(db.Integer, db.ForeignKey('drill.id'), nullable=False)
    ip_address = db.Column(db.String(50), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)

class Drill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)
    media_type = db.Column(db.String(20), default='link') 
    media_file = db.Column(db.String(120), nullable=True) 
    external_link = db.Column(db.String(500), nullable=True) 
    cover_image = db.Column(db.String(120), nullable=True) 
    is_public = db.Column(db.Boolean, default=True)
    views = db.Column(db.Integer, default=0)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    author = db.relationship('User', backref=db.backref('drills', lazy=True))
    primary_tags = db.relationship('Tag', secondary=drill_primary_tags, backref='primary_drills')
    secondary_tags = db.relationship('Tag', secondary=drill_secondary_tags, backref='secondary_drills')

class TrainingPlan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False) 
    date = db.Column(db.DateTime, default=datetime.utcnow)
    team_name = db.Column(db.String(100), nullable=True) 
    notes = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    structure = db.Column(db.String(500), nullable=True) 
    is_public = db.Column(db.Boolean, default=False)
    items = db.relationship('TrainingItem', backref='plan', lazy=True, cascade="all, delete-orphan")

class TrainingItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    training_plan_id = db.Column(db.Integer, db.ForeignKey('training_plan.id'), nullable=False)
    drill_id = db.Column(db.Integer, db.ForeignKey('drill.id'), nullable=False)
    block_name = db.Column(db.String(50), nullable=False)
    order = db.Column(db.Integer, default=0)
    duration = db.Column(db.Integer, default=10) 
    drill = db.relationship('Drill')

@login_manager.user_loader
def load_user(user_id): return User.query.get(int(user_id))

@app.context_processor
def inject_config():
    configs = SiteConfig.query.all()
    site_config = {c.key: c.value for c in configs}
    def get_config_url(key):
        val = site_config.get(key, '')
        if val.startswith('http'): return val
        if val: return url_for('static', filename='uploads/' + val)
        return ''
    return dict(site_config=site_config, get_config_url=get_config_url)

def compress_image(file):
    img = Image.open(file)
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    output = BytesIO()
    img.save(output, format='JPEG', quality=75, optimize=True)
    output.seek(0)
    return output

def extract_youtube_id(url):
    if not url: return None
    if '/shorts/' in url: return url.split('/shorts/')[-1].split('?')[0]
    if 'youtu.be/' in url: return url.split('youtu.be/')[-1].split('?')[0]
    if 'v=' in url: return url.split('v=')[1].split('&')[0]
    return None

@app.template_filter('youtube_thumb')
def youtube_thumb(url):
    vid_id = extract_youtube_id(url)
    if vid_id: return f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg"
    return None

@app.template_filter('get_youtube_id')
def get_youtube_id(url):
    return extract_youtube_id(url)

def create_default_game_config(user_id):
    defaults = [
        ("Rebote Ataque", 1.0, True), ("Rebote Defensa", 1.0, True),
        ("Asistencia", 1.0, True), ("Tapón", 1.0, True),
        ("Robo", 1.0, True), ("Provocar Pérdida", 1.0, True),
        ("Gritar Presión", 1.0, True), ("Canasta Fallada", -0.25, False),
        ("Balón Perdido", -0.5, False), ("Recibo Tapón/Robo", -0.5, False)
    ]
    created_actions = {}
    for name, val, is_pos in defaults:
        act = ActionDefinition(name=name, value=val, is_positive=is_pos, user_id=user_id)
        db.session.add(act)
        created_actions[name] = act
    db.session.commit() 
    all_actions = list(created_actions.values())
    r_mvp = RankingDefinition(name="MVP (Valoración)", icon="star", user_id=user_id)
    r_mvp.ingredients.extend(all_actions)
    r_pulpo = RankingDefinition(name="El Pulpo", icon="octopus", user_id=user_id)
    for k in ["Rebote Ataque", "Rebote Defensa"]:
        if k in created_actions: r_pulpo.ingredients.append(created_actions[k])
    r_muro = RankingDefinition(name="El Muro", icon="shield", user_id=user_id)
    for k in ["Tapón", "Robo", "Provocar Pérdida", "Gritar Presión"]:
        if k in created_actions: r_muro.ingredients.append(created_actions[k])
    r_mago = RankingDefinition(name="El Mago", icon="magic", user_id=user_id)
    if "Asistencia" in created_actions: r_mago.ingredients.append(created_actions["Asistencia"])
    db.session.add_all([r_mvp, r_pulpo, r_muro, r_mago])
    db.session.commit()

# --- RUTAS ---
@app.route('/')
def home():
    query = request.args.get('q', '').strip()
    primary_ids_raw = request.args.getlist('primary')
    filter_type = request.args.getlist('filter_type')
    sort_by = request.args.get('sort_by', 'favs_desc') 
    if current_user.is_authenticated: base_condition = or_(Drill.is_public == True, Drill.user_id == current_user.id)
    else: base_condition = (Drill.is_public == True)
    drills_query = Drill.query.filter(base_condition)
    if filter_type and current_user.is_authenticated:
        conditions = []
        if 'my_private' in filter_type: conditions.append(and_(Drill.user_id == current_user.id, Drill.is_public == False))
        if 'my_public' in filter_type: conditions.append(and_(Drill.user_id == current_user.id, Drill.is_public == True))
        if 'others' in filter_type: conditions.append(and_(Drill.user_id != current_user.id, Drill.is_public == True))
        if 'favorites' in filter_type:
            fav_ids = [d.id for d in current_user.favoritos]
            conditions.append(Drill.id.in_(fav_ids) if fav_ids else Drill.id == -1)
        if conditions: drills_query = drills_query.filter(or_(*conditions))
    if query:
        search_term = f"%{query}%"
        drills_query = drills_query.filter(or_(Drill.title.ilike(search_term), Drill.description.ilike(search_term)))
    if primary_ids_raw:
        try:
            primary_ids = [int(x) for x in primary_ids_raw]
            drills_query = drills_query.filter(Drill.primary_tags.any(Tag.id.in_(primary_ids)))
        except ValueError: pass
    if sort_by == 'views_desc': drills_query = drills_query.order_by(Drill.views.desc())
    elif sort_by == 'favs_desc': drills_query = drills_query.outerjoin(favorites).group_by(Drill.id).order_by(func.count(favorites.c.user_id).desc())
    elif sort_by == 'name_asc': drills_query = drills_query.order_by(Drill.title.asc())
    elif sort_by == 'date_asc': drills_query = drills_query.order_by(Drill.date_posted.asc())
    else: drills_query = drills_query.order_by(Drill.date_posted.desc())
    drills = drills_query.all()
    tags = Tag.query.order_by(Tag.name).all()
    
    # Notificaciones para staff pendiente
    pending_invites = []
    if current_user.is_authenticated:
        pending_invites = TeamStaff.query.filter_by(email=current_user.email, status='pending').all()

    return render_template('index.html', drills=drills, tags=tags, pending_invites=pending_invites)

@app.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    tags = Tag.query.order_by(Tag.name).all()
    if request.method == 'POST':
        title = request.form['titulo']
        desc = request.form['descripcion']
        is_public = 'is_public' in request.form
        content_type = request.form.get('content_type') 
        external_link = request.form.get('external_link', '').strip()
        nuevo = Drill(title=title, description=desc, is_public=is_public, user_id=current_user.id, media_type=content_type)
        if content_type == 'link': nuevo.external_link = external_link
        elif content_type in ['image', 'pdf', 'video_file']:
            file = request.files.get('archivo')
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                if content_type == 'image':
                    ext = filename.split('.')[-1].lower()
                    if ext in ['jpg', 'jpeg', 'png', 'webp']:
                        filename = f"{int(datetime.now().timestamp())}_{filename.rsplit('.', 1)[0]}.jpg"
                        compressed_file = compress_image(file)
                        with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), 'wb') as f: f.write(compressed_file.getbuffer())
                        nuevo.media_file = filename
                    else: return redirect(request.url)
                elif content_type == 'pdf':
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    nuevo.media_file = filename
                elif content_type == 'video_file' and current_user.is_admin:
                     file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                     nuevo.media_file = filename
        cover_option = request.form.get('cover_option')
        if cover_option == 'custom':
            cover_file = request.files.get('custom_cover_file')
            if cover_file and cover_file.filename != '':
                c_filename = f"cover_{int(datetime.now().timestamp())}.jpg"
                c_comp = compress_image(cover_file)
                with open(os.path.join(app.config['UPLOAD_FOLDER'], c_filename), 'wb') as f: f.write(c_comp.getbuffer())
                nuevo.cover_image = c_filename
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
    if drill.user_id != current_user.id and not current_user.is_admin: return redirect('/')
    tags = Tag.query.order_by(Tag.name).all()
    if request.method == 'POST':
        drill.title = request.form['titulo']
        drill.description = request.form['descripcion']
        drill.is_public = 'is_public' in request.form
        drill.primary_tags = [] 
        ids_p = request.form.getlist('primary_tags')
        for t_id in ids_p:
            tag = Tag.query.get(int(t_id))
            if tag: drill.primary_tags.append(tag)
        db.session.commit()
        return redirect('/')
    return render_template('edit_drill.html', drill=drill, etiquetas=tags)

@app.route('/check_link', methods=['POST'])
def check_link():
    url = request.json.get('url')
    if not url: return {'status': 'error'}
    try:
        headers = {'User-Agent': 'Mozilla/5.0'} 
        requests.head(url, headers=headers, timeout=5)
        return {'status': 'ok'}
    except: return {'status': 'error'}

@app.route('/delete/<int:id>')
@login_required
def delete_drill(id):
    drill = Drill.query.get(id)
    if drill and (drill.user_id == current_user.id or current_user.is_admin):
        db.session.delete(drill)
        db.session.commit()
    return redirect(request.referrer or '/')

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
        new_plan = TrainingPlan(name=name, team_name=team, date=plan_date, notes=notes, structure=blocks_csv, user_id=current_user.id, is_public=False)
        db.session.add(new_plan)
        db.session.commit()
        return redirect(url_for('view_plan', id=new_plan.id))
    user_blocks = current_user.last_blocks_config if current_user.last_blocks_config else STANDARD_BLOCKS
    blocks_list = user_blocks.split(',')
    return render_template('create_plan.html', blocks=blocks_list, standard_blocks=STANDARD_BLOCKS)

@app.route('/my_plans')
@login_required
def my_plans():
    plans = TrainingPlan.query.filter_by(user_id=current_user.id).order_by(TrainingPlan.date.desc()).all()
    return render_template('my_plans.html', plans=plans)

@app.route('/plan/<int:id>')
@login_required
def view_plan(id):
    plan = TrainingPlan.query.get_or_404(id)
    if plan.user_id != current_user.id and not plan.is_public: return redirect('/')
    base_condition = or_(Drill.is_public == True, Drill.user_id == current_user.id)
    all_drills = Drill.query.filter(base_condition).order_by(Drill.date_posted.desc()).all()
    tags = Tag.query.order_by(Tag.name).all()
    total_minutes = sum(item.duration for item in plan.items)
    # Get user teams for session start
    owned = Team.query.filter_by(user_id=current_user.id).all()
    staff_teams = [s.team for s in TeamStaff.query.filter_by(user_id=current_user.id, status='accepted').all()]
    my_teams = list(set(owned + staff_teams))
    
    return render_template('view_plan.html', plan=plan, all_drills=all_drills, tags=tags, total_minutes=total_minutes, teams=my_teams)

@app.route('/add_item_to_plan', methods=['POST'])
@login_required
def add_item_to_plan():
    plan_id = request.form.get('plan_id')
    drill_id = request.form.get('drill_id')
    block_name = request.form.get('block_name')
    plan = TrainingPlan.query.get(plan_id)
    if not plan or plan.user_id != current_user.id: return "Error", 403
    item = TrainingItem(training_plan_id=plan.id, drill_id=drill_id, block_name=block_name, duration=10)
    db.session.add(item)
    db.session.commit()
    return redirect(url_for('view_plan', id=plan.id))

@app.route('/update_item_duration', methods=['POST'])
@login_required
def update_item_duration():
    item_id = request.json.get('item_id')
    duration = request.json.get('duration')
    item = TrainingItem.query.get(item_id)
    if item and item.plan.user_id == current_user.id:
        item.duration = int(duration)
        db.session.commit()
        return jsonify({'status': 'ok'})
    return jsonify({'status': 'error'})

@app.route('/delete_plan_item/<int:id>')
@login_required
def delete_plan_item(id):
    item = TrainingItem.query.get_or_404(id)
    if item.plan.user_id == current_user.id:
        plan_id = item.plan.id
        db.session.delete(item)
        db.session.commit()
        return redirect(url_for('view_plan', id=plan_id))
    return redirect('/')

@app.route('/duplicate_drill/<int:id>')
@login_required
def duplicate_drill(id):
    original = Drill.query.get_or_404(id)
    if original.user_id != current_user.id and not current_user.is_admin: return redirect('/')
    clon = Drill(title=f"{original.title} (Copia)", description=original.description, media_type=original.media_type, media_file=original.media_file, external_link=original.external_link, cover_image=original.cover_image, user_id=current_user.id, is_public=False)
    for tag in original.primary_tags: clon.primary_tags.append(tag)
    db.session.add(clon)
    db.session.commit()
    flash('Ejercicio duplicado')
    return redirect('/')

@app.route('/duplicate_plan/<int:id>')
@login_required
def duplicate_plan(id):
    original = TrainingPlan.query.get_or_404(id)
    if original.user_id != current_user.id: return redirect('/')
    clon = TrainingPlan(name=f"{original.name} (Copia)", team_name=original.team_name, notes=original.notes, structure=original.structure, user_id=current_user.id, date=datetime.utcnow())
    db.session.add(clon)
    for item in original.items:
        new_item = TrainingItem(drill_id=item.drill_id, block_name=item.block_name, order=item.order, duration=item.duration)
        clon.items.append(new_item)
    db.session.add(clon)
    db.session.commit()
    flash('Plan duplicado')
    return redirect('/my_plans')

@app.route('/delete_plan/<int:id>')
@login_required
def delete_plan(id):
    plan = TrainingPlan.query.get_or_404(id)
    if plan.user_id == current_user.id:
        db.session.delete(plan)
        db.session.commit()
        flash('Plan eliminado correctamente')
    return redirect('/my_plans')

@app.route('/edit_plan/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_plan(id):
    plan = TrainingPlan.query.get_or_404(id)
    if plan.user_id != current_user.id: return redirect('/my_plans')
    if request.method == 'POST':
        plan.name = request.form.get('name')
        plan.team_name = request.form.get('team')
        date_str = request.form.get('date')
        if date_str: plan.date = datetime.strptime(date_str, '%Y-%m-%d')
        plan.notes = request.form.get('notes')
        plan.structure = request.form.get('blocks_csv')
        current_user.last_blocks_config = plan.structure
        db.session.commit()
        flash('Plan actualizado correctamente')
        return redirect(url_for('view_plan', id=plan.id))
    return render_template('edit_plan.html', plan=plan)

@app.route('/drill/<int:id>')
def view_drill(id):
    drill = Drill.query.get_or_404(id)
    if not drill.is_public:
        if not current_user.is_authenticated or drill.user_id != current_user.id: return redirect('/')
    return render_template('view_drill_modal.html', drill=drill)

@app.route('/toggle_fav/<int:id>')
@login_required
def toggle_fav(id):
    drill = Drill.query.get(id)
    if drill:
        if drill in current_user.favoritos: current_user.favoritos.remove(drill)
        else: current_user.favoritos.append(drill)
        db.session.commit()
    return redirect(request.referrer)

# --- AUTH ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect('/')
    if request.method == 'POST':
        email = request.form['email']
        if User.query.filter_by(email=email).first(): return redirect('/register')
        new_user = User(email=email, name=request.form['name'])
        new_user.set_password(request.form['password'])
        if email.lower() == 'jcaplliure@gmail.com': new_user.is_admin = True
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        create_default_game_config(new_user.id)
        return redirect('/')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect('/')
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            if not user.actions_config: create_default_game_config(user.id)
            return redirect('/')
        else: flash('Error login')
    return render_template('login.html')

@app.route('/login/google')
def google_login():
    redirect_uri = url_for('google_auth', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/callback')
def google_auth():
    token = google.authorize_access_token()
    email = token['userinfo']['email']
    user = User.query.filter_by(email=email).first()
    if not user:
        is_admin = (email.lower() == 'jcaplliure@gmail.com')
        user = User(email=email, name=token['userinfo'].get('name', email.split('@')[0]), is_admin=is_admin)
        db.session.add(user)
        db.session.commit()
        create_default_game_config(user.id)
    login_user(user)
    if not user.actions_config: create_default_game_config(user.id)
    return redirect('/')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')

@app.route('/admin/tags', methods=['GET', 'POST'])
@login_required
def manage_tags():
    if not current_user.is_admin: return redirect('/')
    if request.method == 'POST':
        tag_name = request.form.get('tag_name').strip()
        if tag_name and not Tag.query.filter_by(name=tag_name).first():
            db.session.add(Tag(name=tag_name))
            db.session.commit()
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
        key = request.form.get('key')
        file = request.files.get('file')
        if key and file:
            filename = f"config_{key}_{int(datetime.now().timestamp())}.png"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            conf = SiteConfig.query.get(key)
            if not conf: db.session.add(SiteConfig(key=key, value=filename))
            else: conf.value = filename
            db.session.commit()
            flash('Configuración actualizada')
    configs = SiteConfig.query.all()
    config_dict = {c.key: c.value for c in configs}
    keys_needed = [
        ('tiktok_bg', 'Fondo TikTok'), ('instagram_bg', 'Fondo Instagram'),
        ('facebook_bg', 'Fondo Facebook'), ('pdf_bg', 'Fondo PDF'),
        ('generic_bg', 'Fondo Link Web'), ('youtube_overlay', 'Icono Hover YouTube'),
        ('image_overlay', 'Icono Hover Imagen'), ('pdf_overlay', 'Icono Hover PDF'),
        ('tiktok_overlay', 'Icono Hover TikTok'), ('instagram_overlay', 'Icono Hover Instagram'),
        ('facebook_overlay', 'Icono Hover Facebook'), ('generic_overlay', 'Icono Hover Link Web')
    ]
    return render_template('admin_config.html', config_dict=config_dict, keys_needed=keys_needed)

@app.route('/admin/import_drills', methods=['POST'])
@login_required
def import_drills():
    if not current_user.is_admin: return redirect('/')
    file = request.files['file']
    if not file or file.filename == '':
        flash('No has seleccionado ningún archivo')
        return redirect('/admin/config')
    try:
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.reader(stream)
        count_success = 0
        count_updated = 0
        for row in csv_input:
            if len(row) < 3: continue 
            link = row[0].strip()
            title = row[1].strip()
            tags_string = row[2].strip()
            tags_list_raw = tags_string.split(',') 
            existing_drill = Drill.query.filter_by(external_link=link).first()
            target_drill = None
            if existing_drill:
                target_drill = existing_drill
                count_updated += 1
            else:
                target_drill = Drill(title=title, description="Importado automáticamente", external_link=link, media_type='link', user_id=current_user.id, is_public=True)
                db.session.add(target_drill)
                count_success += 1
            for t_raw in tags_list_raw:
                t_clean = t_raw.strip().capitalize()
                if not t_clean: continue
                tag = Tag.query.filter_by(name=t_clean).first()
                if not tag:
                    tag = Tag(name=t_clean)
                    db.session.add(tag)
                    db.session.commit()
                if tag not in target_drill.primary_tags: target_drill.primary_tags.append(tag)
        db.session.commit()
        flash(f'✅ Importación: {count_success} nuevos, {count_updated} actualizados.')
    except Exception as e: flash(f'❌ Error al importar: {str(e)}')
    return redirect('/admin/config')

# --- LOGICA MULTI-ENTRENADOR Y SESIONES ---

@app.route('/my_teams', methods=['GET', 'POST'])
@login_required
def my_teams():
    if request.method == 'POST':
        name = request.form.get('name')
        category = request.form.get('category')
        logo_filename = None
        file = request.files.get('logo')
        if file and file.filename != '':
            logo_filename = f"team_{int(datetime.now().timestamp())}.jpg"
            comp = compress_image(file)
            with open(os.path.join(app.config['UPLOAD_FOLDER'], logo_filename), 'wb') as f: f.write(comp.getbuffer())
        new_team = Team(name=name, category=category, logo_file=logo_filename, user_id=current_user.id)
        db.session.add(new_team)
        db.session.commit()
        return redirect('/my_teams')
    
    # Obtener equipos propios y equipos donde soy staff aceptado
    owned = Team.query.filter_by(user_id=current_user.id).all()
    staff_memberships = TeamStaff.query.filter_by(email=current_user.email, status='accepted').all()
    staff_teams = [s.team for s in staff_memberships]
    
    all_teams = list(set(owned + staff_teams))
    return render_template('my_teams.html', teams=all_teams)

@app.route('/team/<int:id>', methods=['GET', 'POST'])
@login_required
def view_team(id):
    team = Team.query.get_or_404(id)
    # Check permission (owner or staff)
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    
    if not is_owner and not is_staff: return redirect('/')
    
    if request.method == 'POST':
        # Add player
        name = request.form.get('name')
        dorsal = request.form.get('dorsal')
        photo_filename = None
        file = request.files.get('photo')
        if file and file.filename != '':
            photo_filename = f"player_{int(datetime.now().timestamp())}.jpg"
            comp = compress_image(file)
            with open(os.path.join(app.config['UPLOAD_FOLDER'], photo_filename), 'wb') as f: f.write(comp.getbuffer())
        new_player = Player(name=name, dorsal=int(dorsal), photo_file=photo_filename, team_id=team.id)
        db.session.add(new_player)
        db.session.commit()
        return redirect(url_for('view_team', id=team.id))
        
    return render_template('view_team.html', team=team, is_owner=is_owner)

@app.route('/edit_team_settings/<int:id>', methods=['POST'])
@login_required
def edit_team_settings(id):
    team = Team.query.get_or_404(id)
    # Solo owner o staff puede editar
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return redirect('/')

    team.name = request.form.get('name')
    # Logo
    file = request.files.get('logo')
    if file and file.filename != '':
        logo_filename = f"team_{int(datetime.now().timestamp())}.jpg"
        comp = compress_image(file)
        with open(os.path.join(app.config['UPLOAD_FOLDER'], logo_filename), 'wb') as f: f.write(comp.getbuffer())
        team.logo_file = logo_filename
    
    # Visibilidad
    team.visibility_mode = request.form.get('visibility_mode', 'fixed')
    team.visibility_top_x = int(request.form.get('visibility_top_x', 3))
    team.visibility_top_pct = int(request.form.get('visibility_top_pct', 25))

    db.session.commit()
    flash('Equipo actualizado')
    return redirect(url_for('view_team', id=team.id))

@app.route('/manage_staff/<int:id>', methods=['POST'])
@login_required
def manage_staff(id):
    team = Team.query.get_or_404(id)
    if team.user_id != current_user.id: return "Solo el propietario puede gestionar staff", 403
    
    action = request.form.get('action')
    if action == 'invite':
        email = request.form.get('email').strip()
        if email and email != current_user.email:
            # Check if user exists
            existing_user = User.query.filter_by(email=email).first()
            uid = existing_user.id if existing_user else None
            
            # Check if invite exists
            exists = TeamStaff.query.filter_by(team_id=team.id, email=email).first()
            if not exists:
                new_staff = TeamStaff(team_id=team.id, user_id=uid, email=email, status='pending')
                db.session.add(new_staff)
                db.session.commit()
                flash(f'Invitación enviada a {email}')
            else:
                flash('Usuario ya invitado')
    elif action == 'remove':
        staff_id = request.form.get('staff_id')
        staff = TeamStaff.query.get(staff_id)
        if staff and staff.team_id == team.id:
            db.session.delete(staff)
            db.session.commit()
            flash('Miembro eliminado')
            
    return redirect(url_for('view_team', id=team.id))

@app.route('/accept_invite/<int:id>')
@login_required
def accept_invite(id):
    invite = TeamStaff.query.get_or_404(id)
    if invite.email == current_user.email:
        invite.status = 'accepted'
        invite.user_id = current_user.id
        db.session.commit()
        flash('Has aceptado la invitación')
    return redirect('/')

@app.route('/reject_invite/<int:id>')
@login_required
def reject_invite(id):
    invite = TeamStaff.query.get_or_404(id)
    if invite.email == current_user.email:
        db.session.delete(invite)
        db.session.commit()
    return redirect('/')

# --- SESIONES Y GAMIFICACIÓN ---

@app.route('/start_session', methods=['POST'])
@login_required
def start_session():
    plan_id = request.form.get('plan_id')
    team_id = request.form.get('team_id')
    
    # Check permissions
    team = Team.query.get(team_id)
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return "No autorizado", 403
    
    # Create Session
    new_session = TrainingSession(team_id=team_id, plan_id=plan_id, status='active')
    db.session.add(new_session)
    db.session.commit()
    
    # Initialize Attendance (Default: Everyone present)
    for p in team.players:
        att = SessionAttendance(session_id=new_session.id, player_id=p.id, is_present=True)
        db.session.add(att)
    db.session.commit()
    
    return redirect(url_for('session_tracker', id=new_session.id))

@app.route('/session/<int:id>')
@login_required
def session_tracker(id):
    session = TrainingSession.query.get_or_404(id)
    # Permisos
    team = session.team
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return redirect('/')
    
    plan = TrainingPlan.query.get(session.plan_id) if session.plan_id else None
    
    # Organizar attendance
    attendance_map = {att.player_id: att.is_present for att in session.attendance}
    
    return render_template('session_tracker.html', session=session, plan=plan, attendance_map=attendance_map)

@app.route('/api/save_attendance', methods=['POST'])
@login_required
def api_save_attendance():
    data = request.json
    session_id = data.get('session_id')
    player_id = data.get('player_id')
    is_present = data.get('is_present')
    
    att = SessionAttendance.query.filter_by(session_id=session_id, player_id=player_id).first()
    if att:
        att.is_present = is_present
        db.session.commit()
        return jsonify({'status': 'ok'})
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/save_gamification', methods=['POST'])
@login_required
def api_save_gamification():
    data = request.json
    session_id = data.get('session_id')
    drill_id = data.get('drill_id')
    results = data.get('results') # List of {player_id, raw_score}
    criteria = data.get('criteria') # 'high' or 'low' wins
    
    # 1. Sort results
    # Si 'high' wins (canastas): Mayor a menor
    # Si 'low' wins (tiempo): Menor a mayor
    reverse_sort = (criteria == 'high')
    sorted_results = sorted(results, key=lambda x: float(x['raw_score']), reverse=reverse_sort)
    
    # 2. Assign points (15, 14, 13...)
    points_map = {}
    current_points = 15
    for res in sorted_results:
        points_map[res['player_id']] = max(1, current_points) # Minimo 1 punto
        current_points -= 1
        
    # 3. Save to DB
    # First clear previous scores for this drill/session
    SessionScore.query.filter_by(session_id=session_id, drill_id=drill_id).delete()
    
    for res in results:
        pid = res['player_id']
        raw = res['raw_score']
        pts = points_map.get(pid, 0)
        new_score = SessionScore(session_id=session_id, drill_id=drill_id, player_id=pid, raw_score=raw, points=pts)
        db.session.add(new_score)
    
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/add_late_player', methods=['POST'])
@login_required
def api_add_late_player():
    data = request.json
    session_id = data.get('session_id')
    name = data.get('name')
    dorsal = data.get('dorsal')
    
    session = TrainingSession.query.get(session_id)
    if not session: return jsonify({'error': 'No session'}), 404
    
    # Create player in team
    new_player = Player(name=name, dorsal=int(dorsal), team_id=session.team_id)
    db.session.add(new_player)
    db.session.commit()
    
    # Add to attendance
    att = SessionAttendance(session_id=session.id, player_id=new_player.id, is_present=True)
    db.session.add(att)
    db.session.commit()
    
    return jsonify({'status': 'ok'})

@app.route('/finish_session/<int:id>')
@login_required
def finish_session(id):
    session = TrainingSession.query.get_or_404(id)
    session.status = 'finished'
    db.session.commit()
    return redirect('/my_teams')

# --- PORTAL PÚBLICO JUGADOR ---
@app.route('/team/<int:id>/public')
def public_team_ranking(id):
    team = Team.query.get_or_404(id)
    
    # Calcular puntos totales de gamificación
    # Join SessionScore -> Session -> Team
    scores = db.session.query(
        SessionScore.player_id, 
        func.sum(SessionScore.points).label('total')
    ).join(TrainingSession).filter(TrainingSession.team_id == team.id).group_by(SessionScore.player_id).all()
    
    ranking_data = []
    for pid, total in scores:
        player = Player.query.get(pid)
        if player:
            ranking_data.append({'name': player.name, 'points': total, 'photo': player.photo_file, 'dorsal': player.dorsal})
            
    # Ordenar
    ranking_data.sort(key=lambda x: x['points'], reverse=True)
    
    # Aplicar Filtro "Muro de la Fama"
    limit = len(ranking_data)
    if team.visibility_mode == 'fixed':
        limit = team.visibility_top_x
    else:
        limit = int(len(team.players) * (team.visibility_top_pct / 100.0))
        limit = max(1, limit) # Al menos 1
        
    visible_ranking = ranking_data[:limit]
    
    return render_template('public_ranking.html', team=team, ranking=visible_ranking)

@app.route('/delete_player/<int:id>')
@login_required
def delete_player(id):
    player = Player.query.get_or_404(id)
    # Check permissions logic
    is_owner = (player.team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=player.team.id, email=current_user.email, status='accepted').first()
    if is_owner or is_staff:
        team_id = player.team.id
        db.session.delete(player)
        db.session.commit()
        return redirect(url_for('view_team', id=team_id))
    return redirect('/')

@app.route('/edit_player/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_player(id):
    player = Player.query.get_or_404(id)
    # Check permissions logic
    is_owner = (player.team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=player.team.id, email=current_user.email, status='accepted').first()
    
    if not is_owner and not is_staff: return redirect('/')
    
    if request.method == 'POST':
        player.name = request.form.get('name')
        player.dorsal = int(request.form.get('dorsal'))
        file = request.files.get('photo')
        if file and file.filename != '':
            photo_filename = f"player_{int(datetime.now().timestamp())}.jpg"
            comp = compress_image(file)
            with open(os.path.join(app.config['UPLOAD_FOLDER'], photo_filename), 'wb') as f: 
                f.write(comp.getbuffer())
            player.photo_file = photo_filename
        db.session.commit()
        return redirect(url_for('view_team', id=player.team.id))
        
    return render_template('edit_player.html', player=player)

@app.route('/delete_team/<int:id>')
@login_required
def delete_team(id):
    team = Team.query.get_or_404(id)
    if team.user_id == current_user.id:
        db.session.delete(team)
        db.session.commit()
    return redirect('/my_teams')

@app.route('/game_config', methods=['GET', 'POST'])
@login_required
def game_config():
    if request.method == 'POST':
        actions = ActionDefinition.query.filter_by(user_id=current_user.id).all()
        for action in actions:
            val_str = request.form.get(f'val_{action.id}')
            if val_str:
                action.value = float(val_str)
        db.session.commit()
        flash('Valores actualizados')
        return redirect('/game_config')
    actions = ActionDefinition.query.filter_by(user_id=current_user.id).order_by(ActionDefinition.is_positive.desc()).all()
    return render_template('game_config.html', actions=actions)

@app.route('/new_match', methods=['GET', 'POST'])
@login_required
def new_match():
    if request.method == 'POST':
        team_id = request.form.get('team_id')
        opponent = request.form.get('opponent')
        player_ids = request.form.getlist('roster') 
        
        team = Team.query.get(team_id)
        match = Match(opponent=opponent, team_id=team_id, user_id=current_user.id) # Keep owner as match creator for simplicity
        db.session.add(match)
        db.session.commit()
        for pid in player_ids:
            player = Player.query.get(int(pid))
            if player: match.roster.append(player)
        db.session.commit()
        return redirect(url_for('match_tracker', id=match.id))
        
    # Get all available teams
    owned = Team.query.filter_by(user_id=current_user.id).all()
    staff_teams = [s.team for s in TeamStaff.query.filter_by(user_id=current_user.id, status='accepted').all()]
    all_teams = list(set(owned + staff_teams))
    
    if not all_teams: return redirect('/my_teams')
    return render_template('new_match.html', teams=all_teams)

@app.route('/match/<int:id>')
@login_required
def match_tracker(id):
    match = Match.query.get_or_404(id)
    # Check simple permission (is it one of my teams?)
    if match.user_id != current_user.id:
        # Check staff
        is_staff = TeamStaff.query.filter_by(team_id=match.team_id, email=current_user.email, status='accepted').first()
        if not is_staff: return redirect('/')
        
    actions = ActionDefinition.query.filter_by(user_id=current_user.id).order_by(ActionDefinition.is_positive.desc()).all()
    # Fallback to owner actions if staff doesn't have config (simplified)
    if not actions:
        actions = ActionDefinition.query.filter_by(user_id=match.user_id).order_by(ActionDefinition.is_positive.desc()).all()
        
    return render_template('tracker.html', match=match, actions=actions)

@app.route('/api/add_event', methods=['POST'])
@login_required
def api_add_event():
    data = request.json
    match_id = data.get('match_id')
    player_id = data.get('player_id')
    action_id = data.get('action_id')
    game_minute = data.get('game_minute', 0)
    match = Match.query.get(match_id)
    if not match: return jsonify({'error': 'No match'}), 404
    
    event = MatchEvent(match_id=match_id, player_id=player_id, action_id=action_id, game_minute=game_minute)
    db.session.add(event)
    db.session.commit()
    return jsonify({'status': 'ok', 'event_id': event.id})

@app.route('/api/undo_event', methods=['POST'])
@login_required
def api_undo_event():
    data = request.json
    event_id = data.get('event_id')
    event = MatchEvent.query.get(event_id)
    if event:
        db.session.delete(event)
        db.session.commit()
        return jsonify({'status': 'ok'})
    return jsonify({'error': 'Error'}), 400

@app.route('/match_stats/<int:id>')
@login_required
def match_stats(id):
    match = Match.query.get_or_404(id)
    # Permissions check omitted for brevity, assumes logged in valid
    stats = {}
    for player in match.roster:
        stats[player.id] = { 'name': player.name, 'dorsal': player.dorsal, 'photo': player.photo_file, 'total_val': 0.0, 'actions': {} }
    for event in match.events:
        pid = event.player_id
        aid = event.action_id
        action_def = ActionDefinition.query.get(aid)
        if pid in stats and action_def:
            current_count = stats[pid]['actions'].get(action_def.name, 0)
            stats[pid]['actions'][action_def.name] = current_count + 1
            stats[pid]['total_val'] += action_def.value
    action_names = [a.name for a in ActionDefinition.query.filter_by(user_id=current_user.id).order_by(ActionDefinition.is_positive.desc()).all()]
    if not action_names:
         action_names = [a.name for a in ActionDefinition.query.filter_by(user_id=match.user_id).order_by(ActionDefinition.is_positive.desc()).all()]

    return render_template('match_stats.html', match=match, stats=stats, action_names=action_names)

@app.route('/matches')
@login_required
def matches_list():
    matches = Match.query.filter_by(user_id=current_user.id).order_by(Match.date.desc()).all()
    return render_template('matches_list.html', matches=matches)

@app.route('/court_mode/<int:id>')
@login_required
def court_mode(id):
    # This route is legacy/redirect to session logic if needed, but keeping for compatibility if direct link used
    plan = TrainingPlan.query.get_or_404(id)
    return render_template('court_mode.html', plan=plan)

# --- INICIO ---
def generar_icono_banana(nombre, simbolo):
    path = os.path.join(app.config['UPLOAD_FOLDER'], nombre)
    if os.path.exists(path): return 
    img = Image.new('RGBA', (200, 200), (0, 0, 0, 0)) 
    draw = ImageDraw.Draw(img)
    if simbolo == 'play':
        draw.polygon([(70, 50), (70, 150), (150, 100)], fill=(255, 255, 255, 230))
        draw.ellipse((10, 10, 190, 190), outline=(255, 255, 255, 200), width=8)
    elif simbolo == 'search':
        draw.ellipse((50, 50, 130, 130), outline=(255, 255, 255, 230), width=10)
        draw.line((110, 110, 160, 160), fill=(255, 255, 255, 230), width=12)
    elif simbolo == 'doc':
        draw.rectangle((60, 40, 140, 160), outline=(255, 255, 255, 230), width=8)
        draw.line((80, 70, 120, 70), fill=(255, 255, 255, 180), width=4)
        draw.line((80, 100, 120, 100), fill=(255, 255, 255, 180), width=4)
        draw.line((80, 130, 120, 130), fill=(255, 255, 255, 180), width=4)
    elif simbolo == 'social':
        draw.ellipse((50, 50, 150, 150), outline=(255, 255, 255, 230), width=8)
        draw.text((85, 80), "App", fill=(255, 255, 255, 255))
    img.save(path, 'PNG')

def crear_datos_prueba():
    if Tag.query.count() == 0:
        lista = ["Tiro", "Entrada", "Pase", "Bote", "Defensa", "Rebote", "Físico", "Táctica"]
        for n in lista: db.session.add(Tag(name=n))
        db.session.commit()
    play_icon = "banana_play.png"
    lupa_icon = "banana_search.png"
    doc_icon = "banana_doc.png"
    social_icon = "banana_social.png"
    generar_icono_banana(play_icon, 'play')
    generar_icono_banana(lupa_icon, 'search')
    generar_icono_banana(doc_icon, 'doc')
    generar_icono_banana(social_icon, 'social')
    defaults = {
        'tiktok_bg': 'https://placehold.co/600x400/000000/FFF?text=TikTok',
        'instagram_bg': 'https://placehold.co/600x400/E1306C/FFF?text=Instagram',
        'facebook_bg': 'https://placehold.co/600x400/1877F2/FFF?text=Facebook',
        'pdf_bg': 'https://placehold.co/600x400/dc3545/FFF?text=PDF',
        'generic_bg': 'https://placehold.co/600x400/6c757d/FFF?text=Web',
        'youtube_overlay': play_icon,
        'image_overlay': lupa_icon,
        'pdf_overlay': doc_icon,
        'tiktok_overlay': social_icon, 
        'instagram_overlay': social_icon,
        'facebook_overlay': social_icon,
        'generic_overlay': lupa_icon
    }
    for k, v in defaults.items():
        if not SiteConfig.query.get(k): db.session.add(SiteConfig(key=k, value=v))
    db.session.commit()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        crear_datos_prueba()
    app.run(debug=True)

```