import os
import requests
import json
import csv
import io
import uuid
import random
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import or_, and_, func, desc, case, text
from datetime import datetime
from authlib.integrations.flask_client import OAuth
from io import BytesIO
from PIL import Image, ImageDraw
from dotenv import load_dotenv

# Cargar variables de entorno desde archivo .env
load_dotenv()

app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))

# Configuración de base de datos
database_uri = os.getenv('DATABASE_URL') or f'sqlite:///{os.path.join(basedir, "basket.db")}'
app.config['SQLALCHEMY_DATABASE_URI'] = database_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Clave secreta (obligatoria en producción)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'clave_secreta_super_segura_dev_only')

# Configuración de sesiones
app.config['SESSION_COOKIE_SAMESITE'] = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')
# SESSION_COOKIE_SECURE: True en producción (HTTPS), False en desarrollo (HTTP)
app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', 'False').lower() == 'true'

# Configuración de archivos
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_CONTENT_LENGTH', 50 * 1024 * 1024))

# Configuración de Google OAuth
app.config['GOOGLE_CLIENT_ID'] = os.getenv('GOOGLE_CLIENT_ID', '')
app.config['GOOGLE_CLIENT_SECRET'] = os.getenv('GOOGLE_CLIENT_SECRET', '')
google_redirect_uri = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:5000/auth/callback')

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Configurar OAuth solo si hay credenciales de Google
oauth = OAuth(app)
if app.config['GOOGLE_CLIENT_ID'] and app.config['GOOGLE_CLIENT_SECRET']:
    google = oauth.register(
        name='google',
        client_id=app.config['GOOGLE_CLIENT_ID'],
        client_secret=app.config['GOOGLE_CLIENT_SECRET'],
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
        redirect_uri=google_redirect_uri
    )
else:
    google = None

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
team_gallery_drills = db.Table('team_gallery_drills',
    db.Column('team_id', db.Integer, db.ForeignKey('team.id'), primary_key=True),
    db.Column('drill_id', db.Integer, db.ForeignKey('drill.id'), primary_key=True)
)
action_categories = db.Table('action_categories',
    db.Column('action_id', db.Integer, db.ForeignKey('action_definition.id'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('action_category.id'), primary_key=True)
)

# --- MODELOS ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=True)
    password_hash = db.Column(db.String(128), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    theme_color = db.Column(db.String(7), nullable=True)
    last_blocks_config = db.Column(db.String(500), nullable=True, default="Calentamiento,Técnica Individual,Tiro,Táctica,Físico,Vuelta a la Calma")
    favoritos = db.relationship('Drill', secondary=favorites, backref=db.backref('favorited_by', lazy='dynamic'))
    owned_teams = db.relationship('Team', backref='owner', lazy=True)
    staff_memberships = db.relationship('TeamStaff', backref='user', lazy=True)
    actions_config = db.relationship('ActionDefinition', backref='owner', lazy=True)
    rankings_config = db.relationship('RankingDefinition', backref='owner', lazy=True)
    matches = db.relationship('Match', backref='coach', lazy=True)
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password) if self.password_hash else False

class Invitation(db.Model):
    """Invitaciones enviadas por el admin"""
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)
    invited_at = db.Column(db.DateTime, default=datetime.utcnow)
    registered_at = db.Column(db.DateTime, nullable=True)  # Fecha de alta
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Usuario creado
    user = db.relationship('User', backref='invitation')

class UserAccess(db.Model):
    """Registro de accesos de usuarios"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    accessed_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='accesses')

class AppSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(100), nullable=True)

class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=True)
    logo_file = db.Column(db.String(120), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    visibility_top_x = db.Column(db.Integer, default=3)
    visibility_top_pct = db.Column(db.Integer, default=25)
    visibility_mode = db.Column(db.String(20), default='fixed')
    quarters = db.Column(db.Integer, default=4)
    public_notes = db.Column(db.Text, nullable=True)
    # Configuración de Analytics en portal público
    analytics_visible = db.Column(db.Boolean, default=False)
    analytics_players_count = db.Column(db.Integer, default=5)
    # Gráficos individuales visibles en portal
    chart_all_visible = db.Column(db.Boolean, default=True)  # Ataque y defensa
    chart_attack_visible = db.Column(db.Boolean, default=False)  # Ataque
    chart_attack_no_shots_visible = db.Column(db.Boolean, default=False)  # Ataque (sin puntos)
    chart_defense_visible = db.Column(db.Boolean, default=False)  # Defensa
    players = db.relationship('Player', backref='team', lazy=True, cascade="all, delete-orphan")
    staff = db.relationship('TeamStaff', backref='team', lazy=True, cascade="all, delete-orphan")
    sessions = db.relationship('TrainingSession', backref='team', lazy=True, cascade="all, delete-orphan")
    gallery_drills = db.relationship('Drill', secondary=team_gallery_drills, backref='teams_in_gallery')
    gallery_items = db.relationship('TeamGalleryItem', backref='team', lazy=True, cascade="all, delete-orphan")
    action_categories_list = db.relationship('ActionCategory', backref='team', lazy=True, cascade='all, delete-orphan')
    team_actions = db.relationship('ActionDefinition', backref=db.backref('team', lazy=True), lazy=True, foreign_keys='ActionDefinition.team_id')
    team_rankings = db.relationship('RankingDefinition', backref=db.backref('team', lazy=True), lazy=True, foreign_keys='RankingDefinition.team_id')

class TeamStaff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    email = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), default='assistant')
    status = db.Column(db.String(20), default='pending')

class TeamGalleryItem(db.Model):
    """Ejercicios en la galería del portal público con notas y orden"""
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    drill_id = db.Column(db.Integer, db.ForeignKey('drill.id'), nullable=False)
    note = db.Column(db.Text, nullable=True)  # Nota del entrenador para los niños
    display_order = db.Column(db.Integer, default=0)
    drill = db.relationship('Drill', backref='gallery_items')

class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    dorsal = db.Column(db.Integer, nullable=False)
    photo_file = db.Column(db.String(120), nullable=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)

class TrainingSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('training_plan.id'), nullable=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='active')
    plan = db.relationship('TrainingPlan', backref='sessions')
    attendance = db.relationship('SessionAttendance', backref='session', lazy=True, cascade="all, delete-orphan")
    scores = db.relationship('SessionScore', backref='session', lazy=True, cascade="all, delete-orphan")

class SessionAttendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('training_session.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    is_present = db.Column(db.Boolean, default=False)
    player = db.relationship('Player', backref='session_attendances')

class SessionScore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('training_session.id'), nullable=False)
    drill_id = db.Column(db.Integer, db.ForeignKey('drill.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    raw_score = db.Column(db.Float, default=0.0)
    points = db.Column(db.Integer, default=0)

class SessionItemExecution(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('training_session.id'), nullable=False)
    training_item_id = db.Column(db.Integer, db.ForeignKey('training_item.id'), nullable=False)
    was_completed = db.Column(db.Boolean, default=True)
    actual_duration = db.Column(db.Integer, nullable=True)  # minutos, null si no se hizo
    notes = db.Column(db.Text, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    session = db.relationship('TrainingSession', backref='executions')
    training_item = db.relationship('TrainingItem', backref='executions')

class ActionCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)

class ActionDefinition(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    value = db.Column(db.Float, nullable=False) 
    score_value = db.Column(db.Integer, default=0)
    is_positive = db.Column(db.Boolean, default=True) 
    icon = db.Column(db.String(50), nullable=True)
    display_section = db.Column(db.String(20), nullable=True)
    display_order = db.Column(db.Integer, default=0)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    is_system = db.Column(db.Boolean, default=False)
    system_key = db.Column(db.String(50), nullable=True)
    custom_slot = db.Column(db.Integer, nullable=True)
    visible = db.Column(db.Boolean, default=True)
    description = db.Column(db.String(255), nullable=True)
    grid_row = db.Column(db.Integer, default=1)
    grid_col = db.Column(db.Integer, default=1)
    categories = db.relationship('ActionCategory', secondary=action_categories, backref='actions')

class RankingDefinition(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    icon = db.Column(db.String(50), default="trophy") 
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    ingredients = db.relationship('ActionDefinition', secondary=ranking_ingredients, backref='used_in_rankings')

class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    opponent = db.Column(db.String(100), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    is_home = db.Column(db.Boolean, default=True)
    quarters = db.Column(db.Integer, default=4)
    result_us = db.Column(db.Integer, default=0)
    result_them = db.Column(db.Integer, default=0)
    current_period = db.Column(db.Integer, default=1)
    court_lineup = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False) 
    roster = db.relationship('Player', secondary=match_roster, backref='matches_played')
    events = db.relationship('MatchEvent', backref='match', lazy=True, cascade="all, delete-orphan")

class MatchEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)
    action_id = db.Column(db.Integer, db.ForeignKey('action_definition.id'), nullable=True)
    opponent_points = db.Column(db.Integer, default=0)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    game_minute = db.Column(db.Integer, default=0)
    period = db.Column(db.Integer, default=1)
    player = db.relationship('Player', backref='events')
    action = db.relationship('ActionDefinition', backref='events')

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
    group_id = db.Column(db.Integer, db.ForeignKey('tag_group.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    is_custom = db.Column(db.Boolean, default=False)
    display_order = db.Column(db.Integer, default=0)
    group = db.relationship('TagGroup', backref='tags')

class TagGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    display_order = db.Column(db.Integer, default=0)

class TagGroupImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('tag_group.id'), nullable=False)
    filename = db.Column(db.String(120), nullable=False)
    group = db.relationship('TagGroup', backref='images')

class TagImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tag_id = db.Column(db.Integer, db.ForeignKey('tag.id'), nullable=False)
    filename = db.Column(db.String(120), nullable=False)
    tag = db.relationship('Tag', backref='images')

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
    primary_tag_id = db.Column(db.Integer, db.ForeignKey('tag.id'), nullable=True)
    primary_tag = db.relationship('Tag', foreign_keys=[primary_tag_id])
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
    
    # Inyectar color del tema
    theme_color = get_user_theme_color()
    
    return dict(site_config=site_config, get_config_url=get_config_url, theme_color=theme_color)

def get_user_theme_color():
    """Devuelve el color del tema: primero del usuario, luego global, luego por defecto"""
    from flask_login import current_user
    
    # 1. Color personalizado del usuario
    if current_user.is_authenticated and current_user.theme_color:
        return current_user.theme_color
    
    # 2. Color global de la aplicación
    app_setting = AppSettings.query.filter_by(key='primary_color').first()
    if app_setting and app_setting.value:
        return app_setting.value
    
    # 3. Color por defecto
    return '#FFD700'

def get_tag_groups_for_user(user):
    groups = TagGroup.query.order_by(TagGroup.display_order.asc(), TagGroup.name.asc()).all()
    if user and user.is_authenticated:
        tags = Tag.query.filter(or_(Tag.user_id == None, Tag.user_id == user.id)).order_by(Tag.display_order.asc(), Tag.name.asc()).all()
    else:
        tags = Tag.query.filter_by(user_id=None).order_by(Tag.display_order.asc(), Tag.name.asc()).all()
    group_map = {g.id: [] for g in groups}
    for t in tags:
        if t.group_id in group_map:
            group_map[t.group_id].append(t)
    grouped = []
    for g in groups:
        grouped.append({'group': g, 'tags': group_map.get(g.id, [])})
    return grouped

def pick_cover_from_tag(tag):
    if tag and tag.images:
        return random.choice(tag.images).filename
    if tag and tag.group and tag.group.images:
        return random.choice(tag.group.images).filename
    return None

def get_drill_origin(drill):
    link = drill.external_link or ''
    if drill.media_type == 'pdf':
        return 'pdf'
    if drill.media_type == 'image':
        return 'image'
    if 'tiktok' in link:
        return 'tiktok'
    if 'instagram' in link:
        return 'instagram'
    if 'facebook' in link:
        return 'facebook'
    if 'youtu' in link:
        return 'youtube'
    if drill.media_type == 'link':
        return 'link'
    return 'other'

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
def get_youtube_id(url): return extract_youtube_id(url)

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
    r_mvp = RankingDefinition(name="Valoración", icon="star", user_id=user_id)
    r_mvp.ingredients.extend(list(created_actions.values()))
    db.session.add(r_mvp)
    db.session.commit()

def _run_alter(cmd):
    try:
        db.session.execute(text(cmd))
        db.session.commit()
    except Exception as e:
        s = str(e).lower()
        if 'duplicate column' in s or 'already exists' in s or 'no such table' in s:
            db.session.rollback()
            return
        raise

def run_migrations():
    _run_alter('ALTER TABLE action_definition ADD COLUMN icon VARCHAR(50)')
    _run_alter('ALTER TABLE action_definition ADD COLUMN team_id INTEGER REFERENCES team(id)')
    _run_alter('ALTER TABLE action_definition ADD COLUMN display_section VARCHAR(20)')
    _run_alter('ALTER TABLE action_definition ADD COLUMN display_order INTEGER DEFAULT 0')
    _run_alter('ALTER TABLE action_definition ADD COLUMN score_value INTEGER DEFAULT 0')
    _run_alter('ALTER TABLE ranking_definition ADD COLUMN team_id INTEGER REFERENCES team(id)')
    _run_alter('ALTER TABLE match_event ADD COLUMN opponent_points INTEGER DEFAULT 0')
    _run_alter('ALTER TABLE match ADD COLUMN current_period INTEGER DEFAULT 1')
    _run_alter('ALTER TABLE match ADD COLUMN court_lineup TEXT')
    _run_alter('ALTER TABLE user ADD COLUMN theme_color VARCHAR(7)')
    _run_alter('ALTER TABLE drill ADD COLUMN primary_tag_id INTEGER REFERENCES tag(id)')
    _run_alter('ALTER TABLE tag ADD COLUMN group_id INTEGER REFERENCES tag_group(id)')
    _run_alter('ALTER TABLE tag ADD COLUMN user_id INTEGER REFERENCES user(id)')
    _run_alter('ALTER TABLE tag ADD COLUMN is_custom BOOLEAN DEFAULT 0')
    _run_alter('ALTER TABLE action_definition ADD COLUMN is_system BOOLEAN DEFAULT 0')
    _run_alter('ALTER TABLE action_definition ADD COLUMN system_key VARCHAR(50)')
    _run_alter('ALTER TABLE action_definition ADD COLUMN custom_slot INTEGER')
    _run_alter('ALTER TABLE action_definition ADD COLUMN visible BOOLEAN DEFAULT 1')
    _run_alter('ALTER TABLE action_definition ADD COLUMN description VARCHAR(255)')
    _run_alter('ALTER TABLE action_definition ADD COLUMN grid_row INTEGER DEFAULT 1')
    _run_alter('ALTER TABLE action_definition ADD COLUMN grid_col INTEGER DEFAULT 1')
    # Gráficos visibles en portal público
    _run_alter('ALTER TABLE team ADD COLUMN chart_all_visible BOOLEAN DEFAULT 1')
    _run_alter('ALTER TABLE team ADD COLUMN chart_attack_visible BOOLEAN DEFAULT 0')
    _run_alter('ALTER TABLE team ADD COLUMN chart_attack_no_shots_visible BOOLEAN DEFAULT 0')
    _run_alter('ALTER TABLE team ADD COLUMN chart_defense_visible BOOLEAN DEFAULT 0')
    # Sistema de invitaciones
    _run_alter('''CREATE TABLE IF NOT EXISTS invitation (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email VARCHAR(120) UNIQUE NOT NULL,
        token VARCHAR(64) UNIQUE NOT NULL,
        invited_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        registered_at DATETIME,
        user_id INTEGER REFERENCES user(id)
    )''')
    _run_alter('''CREATE TABLE IF NOT EXISTS user_access (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES user(id),
        accessed_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    # Orden de etiquetas dentro de grupos
    _run_alter('ALTER TABLE tag ADD COLUMN display_order INTEGER DEFAULT 0')

# Posiciones de doble ancho: (display_section, is_positive, grid_row, grid_col)
DOUBLE_WIDTH_POSITIONS = [("ATAQUE", True, 1, 1), ("ATAQUE", False, 1, 1)]

# Lista canónica: (name, value, score_value, is_positive, section, order, is_system, system_key, custom_slot, description, grid_row, grid_col)
# Posiciones fijas según documento: Ataque+/- 7 huecos (1,1)doble,(2,1),(2,2),(3,1),(3,2),(4,1),(4,2); Defensa+/- 6 huecos (1,1),(1,2),(2,1),(2,2),(3,1),(3,2)
ACTION_DEFAULTS = [
    # Ataque+ (7). (1,1) doble ancho
    ("Tiro 2", 2.0, 2, True, "ATAQUE", 101, True, "ATAQUE_TIRO2_POS", None, "Tiro de 2 anotado", 1, 1),
    ("Tiro 1", 1.0, 1, True, "ATAQUE", 102, True, "ATAQUE_TIRO1_POS", None, "Tiro libre anotado", 2, 1),
    ("Tiro 3", 3.0, 3, True, "ATAQUE", 103, True, "ATAQUE_TIRO3_POS", None, "Tiro de 3 anotado", 2, 2),
    ("Reb.Of.", 1.0, 0, True, "ATAQUE", 201, True, "ATAQUE_REBOF", None, "Rebote ofensivo", 3, 1),
    ("Asist", 2.0, 0, True, "ATAQUE", 202, True, "ATAQUE_ASIST", None, "Asistencia", 3, 2),
    ("Personali.", 0.0, 0, True, "ATAQUE", 203, False, None, 1, "Personalizable", 4, 1),
    ("Personali.", 0.0, 0, True, "ATAQUE", 204, False, None, 2, "Personalizable", 4, 2),
    # Ataque- (7). (1,1) doble ancho
    ("Tiro 2", -0.5, 0, False, "ATAQUE", 301, True, "ATAQUE_TIRO2_NEG", None, "Tiro de 2 fallado", 1, 1),
    ("Tiro 1", -0.25, 0, False, "ATAQUE", 302, True, "ATAQUE_TIRO1_NEG", None, "Tiro libre fallado", 2, 1),
    ("Tiro 3", -0.5, 0, False, "ATAQUE", 303, True, "ATAQUE_TIRO3_NEG", None, "Tiro de 3 fallado", 2, 2),
    ("Tap.Rec", -0.25, 0, False, "ATAQUE", 401, True, "ATAQUE_TAPREC", None, "Tapón recibido", 3, 1),
    ("Bal.Per", -0.5, 0, False, "ATAQUE", 402, True, "ATAQUE_BALPER", None, "Balón perdido", 3, 2),
    ("Personali.", 0.0, 0, False, "ATAQUE", 403, False, None, 3, "Personalizable", 4, 1),
    ("Personali.", 0.0, 0, False, "ATAQUE", 404, False, None, 4, "Personalizable", 4, 2),
    # Defensa+ (6)
    ("Reb.Def", 1.0, 0, True, "DEFENSA", 101, True, "DEFENSA_REBDEF", None, "Rebote defensivo", 1, 1),
    ("Robo", 1.0, 0, True, "DEFENSA", 102, True, "DEFENSA_ROBO", None, "Robo", 1, 2),
    ("Tapón", 1.0, 0, True, "DEFENSA", 103, True, "DEFENSA_TAPON", None, "Tapón", 2, 1),
    ("Prov.Pe", 1.0, 0, True, "DEFENSA", 201, False, None, 5, "Provoca pérdida o robo", 2, 2),
    ("Personali.", 0.0, 0, True, "DEFENSA", 202, False, None, 6, "Personalizable", 3, 1),
    ("Personali.", 0.0, 0, True, "DEFENSA", 203, False, None, 7, "Personalizable", 3, 2),
    # Defensa- (6)
    ("Falta", 0.0, 0, False, "DEFENSA", 301, True, "DEFENSA_FALTA", None, "Falta cometida", 1, 1),
    ("Can.Fác", -2.0, 0, False, "DEFENSA", 302, False, None, 8, "Canasta fácil concedida", 1, 2),
    ("NoAyuda", -1.0, 0, False, "DEFENSA", 303, False, None, 9, "No ayuda defensiva", 2, 1),
    ("Personali.", 0.0, 0, False, "DEFENSA", 401, False, None, 10, "Personalizable", 2, 2),
    ("Personali.", 0.0, 0, False, "DEFENSA", 402, False, None, 11, "Personalizable", 3, 1),
    ("Personali.", 0.0, 0, False, "DEFENSA", 403, False, None, 12, "Personalizable", 3, 2),
]

def _truncate_action_name(name, max_len=10):
    return (name or '')[:max_len]

def create_default_actions_for_user(user_id):
    """Crea el set estándar de acciones para un usuario (ej. al registrarse). Solo acciones de usuario (team_id=None)."""
    if ActionDefinition.query.filter_by(user_id=user_id, team_id=None).first():
        return
    for t in ACTION_DEFAULTS:
        name, val, score, is_pos, section, order, is_sys, sys_key, cslot, desc, grow, gcol = t
        a = ActionDefinition(
            name=_truncate_action_name(name),
            value=val,
            score_value=score,
            is_positive=is_pos,
            display_section=section,
            display_order=order,
            user_id=user_id,
            team_id=None,
            is_system=is_sys,
            system_key=sys_key,
            custom_slot=cslot,
            visible=True,
            description=(desc or '')[:255],
            grid_row=grow,
            grid_col=gcol
        )
        db.session.add(a)
    db.session.commit()

def copy_actions_from_admin_to_user(target_user_id):
    """Copia la configuración de acciones del primer admin al nuevo usuario."""
    admin = User.query.filter_by(is_admin=True).first()
    if not admin:
        create_default_actions_for_user(target_user_id)
        return
    source_actions = ActionDefinition.query.filter_by(user_id=admin.id, team_id=None).order_by(
        ActionDefinition.display_section, ActionDefinition.display_order
    ).all()
    if not source_actions or not any(getattr(a, 'display_section', None) for a in source_actions):
        create_default_actions_for_user(target_user_id)
        return
    for src in source_actions:
        a = ActionDefinition(
            name=_truncate_action_name(src.name),
            value=src.value,
            score_value=src.score_value or 0,
            is_positive=src.is_positive,
            display_section=src.display_section,
            display_order=src.display_order,
            user_id=target_user_id,
            team_id=None,
            is_system=src.is_system,
            system_key=src.system_key,
            custom_slot=src.custom_slot,
            visible=src.visible,
            description=getattr(src, 'description', None) and (src.description or '')[:255],
            grid_row=getattr(src, 'grid_row', 1) or 1,
            grid_col=getattr(src, 'grid_col', 1) or 1
        )
        db.session.add(a)
    db.session.commit()

def seed_team_actions(team_id):
    team = Team.query.get(team_id)
    if not team or ActionDefinition.query.filter_by(team_id=team_id).first():
        return
    defaults = [
        ("Tiro 2", 2.0, 2, True, "ATAQUE", 101),
        ("Tiro 2", -0.5, 0, False, "ATAQUE", 102),
        ("Tiro 1", 1.0, 1, True, "ATAQUE", 201),
        ("Tiro 3", 3.0, 3, True, "ATAQUE", 202),
        ("Tiro 1", -0.25, 0, False, "ATAQUE", 203),
        ("Tiro 3", -0.5, 0, False, "ATAQUE", 204),
        ("Reb.Of.", 1.0, 0, True, "ATAQUE", 301),
        ("Asist", 2.0, 0, True, "ATAQUE", 302),
        ("Tap.Rec", -0.25, 0, False, "ATAQUE", 303),
        ("Bal.Per", -0.5, 0, False, "ATAQUE", 304),
        ("Reb.Def", 1.0, 0, True, "DEFENSA", 101),
        ("Robo", 1.0, 0, True, "DEFENSA", 102),
        ("Can.Fác", -2.0, 0, False, "DEFENSA", 103),
        ("NoAyuda", -1.0, 0, False, "DEFENSA", 104),
        ("Tapón", 1.0, 0, True, "DEFENSA", 201),
        ("Prov.Pe", 1.0, 0, True, "DEFENSA", 202),
        ("Falta", 0.0, 0, False, "DEFENSA", 203),
    ]
    created = {}
    for name, val, score, is_pos, section, order in defaults:
        a = ActionDefinition(
            name=name[:8], 
            value=val, 
            score_value=score,
            is_positive=is_pos, 
            display_section=section,
            display_order=order,
            user_id=team.user_id, 
            team_id=team_id
        )
        db.session.add(a)
        key = f"{name}_{order}"
        created[key] = a
    db.session.flush()
    def_actions = [a for a in created.values() if a.display_section == "DEFENSA" and a.is_positive]
    off_actions = [a for a in created.values() if a.display_section == "ATAQUE" and a.is_positive]
    r1 = RankingDefinition(name="Muro Defensivo", icon="shield", user_id=team.user_id, team_id=team_id)
    r1.ingredients = def_actions[:3]
    r2 = RankingDefinition(name="Motor Ofensivo", icon="lightning", user_id=team.user_id, team_id=team_id)
    r2.ingredients = off_actions[:4]
    db.session.add(r1)
    db.session.add(r2)
    db.session.commit()

def _action_sort_key(a):
    """Orden: bloque (Ataque+, Ataque-, Defensa+, Defensa-) luego grid_row, grid_col."""
    block_order = [("ATAQUE", True), ("ATAQUE", False), ("DEFENSA", True), ("DEFENSA", False)]
    section = a.display_section or "ATAQUE"
    pos = a.is_positive if a.is_positive is not None else True
    try:
        bi = block_order.index((section, pos))
    except ValueError:
        bi = 0
    grow = getattr(a, 'grid_row', 0) or 0
    gcol = getattr(a, 'grid_col', 0) or 0
    return (bi, grow, gcol)

def get_actions_for_user(user_id, include_hidden=False):
    """Acciones del usuario ordenadas por bloque y posición en rejilla. Por defecto excluye no visibles."""
    q = ActionDefinition.query.filter_by(user_id=user_id, team_id=None).all()
    if not include_hidden:
        q = [a for a in q if a.visible]
    return sorted(q, key=_action_sort_key)

def get_actions_for_team(team_id, user_id):
    """Acciones para partidos: siempre usa las acciones del usuario (configuración global).
    Esto garantiza que el tracker sea un espejo exacto de /game_config."""
    # Siempre usar las acciones del usuario para consistencia con la configuración
    return get_actions_for_user(user_id, include_hidden=False)

def get_rankings_for_team(team_id, user_id):
    team_rankings = RankingDefinition.query.filter_by(team_id=team_id).all()
    if team_rankings:
        return team_rankings
    return RankingDefinition.query.filter_by(user_id=user_id).all()

# --- RUTAS ---
@app.route('/')
def home():
    query = request.args.get('q', '').strip()
    primary_ids_raw = request.args.getlist('primary')
    sort_by = request.args.get('sort_by', 'smart_order') 
    origin_filter = request.args.get('origin', '').strip()
    base_condition = or_(Drill.is_public == True, Drill.user_id == current_user.id) if current_user.is_authenticated else (Drill.is_public == True)
    drills_query = Drill.query.filter(base_condition)
    if query:
        search_term = f"%{query}%"
        drills_query = drills_query.filter(or_(Drill.title.ilike(search_term), Drill.description.ilike(search_term)))
    if primary_ids_raw:
        try:
            primary_ids = [int(x) for x in primary_ids_raw]
            drills_query = drills_query.filter(
                or_(
                    Drill.primary_tag_id.in_(primary_ids),
                    Drill.secondary_tags.any(Tag.id.in_(primary_ids))
                )
            )
        except ValueError: pass
    if origin_filter:
        if origin_filter == 'pdf':
            drills_query = drills_query.filter(Drill.media_type == 'pdf')
        elif origin_filter == 'image':
            drills_query = drills_query.filter(Drill.media_type == 'image')
        elif origin_filter == 'youtube':
            drills_query = drills_query.filter(Drill.external_link.ilike('%youtu%'))
        elif origin_filter == 'tiktok':
            drills_query = drills_query.filter(Drill.external_link.ilike('%tiktok%'))
        elif origin_filter == 'instagram':
            drills_query = drills_query.filter(Drill.external_link.ilike('%instagram%'))
        elif origin_filter == 'facebook':
            drills_query = drills_query.filter(Drill.external_link.ilike('%facebook%'))
        elif origin_filter == 'link':
            drills_query = drills_query.filter(Drill.media_type == 'link')
    drills = drills_query.all()
    if current_user.is_authenticated and sort_by == 'smart_order':
        my_fav_ids = [d.id for d in current_user.favoritos]
        drills.sort(key=lambda d: (1 if d.id in my_fav_ids else 0, d.favorited_by.count(), d.views), reverse=True)
    elif sort_by == 'views_desc': drills.sort(key=lambda x: x.views, reverse=True)
    elif sort_by == 'favs_desc': drills.sort(key=lambda x: x.favorited_by.count(), reverse=True)
    elif sort_by == 'date_desc': drills.sort(key=lambda x: x.date_posted, reverse=True)
    for d in drills:
        if not d.cover_image and d.primary_tag:
            d.cover_fallback = pick_cover_from_tag(d.primary_tag)
        else:
            d.cover_fallback = None
        d.origin = get_drill_origin(d)
    if current_user.is_authenticated:
        tags = Tag.query.filter(or_(Tag.user_id == None, Tag.user_id == current_user.id)).order_by(Tag.display_order.asc(), Tag.name.asc()).all()
        tag_groups = get_tag_groups_for_user(current_user)
    else:
        tags = Tag.query.filter_by(user_id=None).order_by(Tag.display_order.asc(), Tag.name.asc()).all()
        tag_groups = get_tag_groups_for_user(None)
    pending_invites = TeamStaff.query.filter_by(email=current_user.email, status='pending').all() if current_user.is_authenticated else []
    return render_template('index.html', drills=drills, tags=tags, tag_groups=tag_groups, pending_invites=pending_invites)

@app.route('/create')
@login_required
def create():
    # Crear ejercicio borrador y redirigir a edición
    nuevo = Drill(
        title='',
        description='',
        is_public=True,
        user_id=current_user.id,
        media_type='link'
    )
    db.session.add(nuevo)
    db.session.commit()
    return redirect(url_for('edit_drill', id=nuevo.id, new=1))

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_drill(id):
    drill = Drill.query.get_or_404(id)
    if drill.user_id != current_user.id and not current_user.is_admin: return redirect('/')
    tag_groups = get_tag_groups_for_user(current_user)
    if request.method == 'POST':
        drill.title = request.form['titulo']
        drill.description = request.form['descripcion']
        drill.is_public = 'is_public' in request.form
        cover_option = request.form.get('cover_option')
        content_type = request.form.get('content_type') 
        if content_type:
            drill.media_type = content_type
            if content_type == 'link':
                drill.external_link = request.form.get('external_link', '').strip()
                drill.media_file = None
        elif content_type in ['image', 'pdf', 'video_file']:
            file = request.files.get('archivo')
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                if content_type == 'image':
                    ext = filename.split('.')[-1].lower()
                    if ext in ['jpg', 'jpeg', 'png', 'webp']:
                        filename = f"{int(datetime.now().timestamp())}_{filename.rsplit('.', 1)[0]}.jpg"
                        compressed_file = compress_image(file)
                        with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), 'wb') as f:
                            f.write(compressed_file.getbuffer())
                        drill.media_file = filename
                        drill.external_link = None
                elif content_type == 'pdf':
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    drill.media_file = filename
                    drill.external_link = None
                elif content_type == 'video_file' and current_user.is_admin:
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    drill.media_file = filename
                    drill.external_link = None
        tag_ids = [int(x) for x in request.form.getlist('tag_ids') if str(x).isdigit()]
        primary_tag_id = request.form.get('primary_tag_id', type=int)
        if not tag_ids or not primary_tag_id or primary_tag_id not in tag_ids:
            flash('Selecciona etiquetas y marca una principal')
            return redirect(request.url)
        if len(tag_ids) > 3:
            flash('Máximo 3 etiquetas por ejercicio')
            return redirect(request.url)
        drill.primary_tag_id = primary_tag_id
        secondary_ids = [tid for tid in tag_ids if tid != primary_tag_id][:2]
        drill.secondary_tags = Tag.query.filter(Tag.id.in_(secondary_ids)).all()
        if cover_option == 'custom':
            cover_file = request.files.get('custom_cover_file')
            if cover_file and cover_file.filename != '':
                c_filename = f"cover_{int(datetime.now().timestamp())}.jpg"
                c_comp = compress_image(cover_file)
                with open(os.path.join(app.config['UPLOAD_FOLDER'], c_filename), 'wb') as f:
                    f.write(c_comp.getbuffer())
                drill.cover_image = c_filename
        elif cover_option == 'default':
            drill.cover_image = None
        db.session.commit()
        return redirect('/')
    is_new = request.args.get('new') == '1'
    theme_color = current_user.theme_color
    if not theme_color:
        conf = SiteConfig.query.get('primary_color')
        theme_color = conf.value if conf else '#FFD700'
    return render_template('edit_drill.html', drill=drill, tag_groups=tag_groups, is_new=is_new, theme_color=theme_color)

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
        # Eliminar todas las referencias antes de borrar el ejercicio
        TeamGalleryItem.query.filter_by(drill_id=id).delete()
        db.session.execute(team_gallery_drills.delete().where(team_gallery_drills.c.drill_id == id))
        db.session.execute(favorites.delete().where(favorites.c.drill_id == id))
        db.session.execute(drill_primary_tags.delete().where(drill_primary_tags.c.drill_id == id))
        db.session.execute(drill_secondary_tags.delete().where(drill_secondary_tags.c.drill_id == id))
        SessionScore.query.filter_by(drill_id=id).delete()
        DrillView.query.filter_by(drill_id=id).delete()
        TrainingItem.query.filter_by(drill_id=id).delete()
        # Ahora eliminar el ejercicio
        db.session.delete(drill)
        db.session.commit()
        flash('Ejercicio eliminado correctamente')
    return redirect('/')

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
        exercises_json = request.form.get('exercises_json', '{}')
        current_user.last_blocks_config = blocks_csv
        plan_date = datetime.strptime(date_str, '%Y-%m-%d') if date_str else datetime.utcnow()
        new_plan = TrainingPlan(name=name, team_name=team, date=plan_date, notes=notes, structure=blocks_csv, user_id=current_user.id, is_public=False)
        db.session.add(new_plan)
        db.session.flush()  # Para obtener el ID del plan
        
        # Añadir ejercicios si hay
        try:
            exercises_data = json.loads(exercises_json)
            for block_name, exercises in exercises_data.items():
                for idx, ex in enumerate(exercises):
                    item = TrainingItem(
                        training_plan_id=new_plan.id,
                        drill_id=ex['drill_id'],
                        block_name=block_name,
                        order=idx,
                        duration=ex.get('duration', 10)
                    )
                    db.session.add(item)
        except (json.JSONDecodeError, KeyError, TypeError):
            pass  # Si hay error, simplemente no añadimos ejercicios
        
        db.session.commit()
        return redirect(url_for('view_plan', id=new_plan.id))
    user_blocks = current_user.last_blocks_config if current_user.last_blocks_config else STANDARD_BLOCKS
    blocks_list = user_blocks.split(',')
    tags = Tag.query.order_by(Tag.display_order.asc(), Tag.name.asc()).all()
    today = datetime.utcnow().strftime('%Y-%m-%d')
    return render_template('create_plan.html', blocks=blocks_list, standard_blocks=STANDARD_BLOCKS, tags=tags, now=today)

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
    tags = Tag.query.order_by(Tag.display_order.asc(), Tag.name.asc()).all()
    total_minutes = sum(item.duration for item in plan.items)
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

@app.route('/api/add_item_to_plan', methods=['POST'])
@login_required
def api_add_item_to_plan():
    data = request.json
    plan_id = data.get('plan_id')
    drill_id = data.get('drill_id')
    block_name = data.get('block_name')
    duration = data.get('duration', 10)
    
    if not plan_id:  # Si no hay plan_id, es porque estamos creando el plan
        return jsonify({'status': 'ok', 'temp_id': f'temp_{drill_id}_{block_name}'})
    
    plan = TrainingPlan.query.get(plan_id)
    if not plan or plan.user_id != current_user.id: 
        return jsonify({'status': 'error', 'message': 'No autorizado'}), 403
    
    item = TrainingItem(training_plan_id=plan.id, drill_id=drill_id, block_name=block_name, duration=duration)
    db.session.add(item)
    db.session.commit()
    return jsonify({'status': 'ok', 'item_id': item.id})

@app.route('/api/get_drill_title/<int:drill_id>')
@login_required
def api_get_drill_title(drill_id):
    drill = Drill.query.get_or_404(drill_id)
    base_condition = or_(Drill.is_public == True, Drill.user_id == current_user.id)
    if not (drill.is_public or drill.user_id == current_user.id):
        return jsonify({'error': 'Unauthorized'}), 403
    return jsonify({'title': drill.title})

@app.route('/api/get_drills', methods=['GET'])
@login_required
def api_get_drills():
    query = request.args.get('q', '').strip()
    tag_ids = request.args.getlist('tags')
    
    base_condition = or_(Drill.is_public == True, Drill.user_id == current_user.id)
    drills_query = Drill.query.filter(base_condition)
    
    if query:
        search_term = f"%{query}%"
        drills_query = drills_query.filter(or_(Drill.title.ilike(search_term), Drill.description.ilike(search_term)))
    
    if tag_ids:
        try:
            tag_ids_int = [int(tid) for tid in tag_ids]
            drills_query = drills_query.filter(
                or_(
                    Drill.primary_tag_id.in_(tag_ids_int),
                    Drill.secondary_tags.any(Tag.id.in_(tag_ids_int))
                )
            )
        except ValueError:
            pass
    
    drills = drills_query.limit(50).all()
    result = []
    for drill in drills:
        tag_names = []
        if drill.primary_tag:
            tag_names.append(drill.primary_tag.name)
        tag_names.extend([t.name for t in drill.secondary_tags[:2]])
        result.append({
            'id': drill.id,
            'title': drill.title,
            'description': drill.description or '',
            'media_type': drill.media_type,
            'external_link': drill.external_link or '',
            'media_file': drill.media_file or '',
            'cover_image': drill.cover_image or '',
            'tags': tag_names
        })
    return jsonify({'drills': result})

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
    clon.primary_tag_id = original.primary_tag_id
    clon.secondary_tags = list(original.secondary_tags)
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
    STANDARD_BLOCKS = "Calentamiento,Técnica Individual,Tiro,Táctica,Físico,Vuelta a la Calma"
    
    if request.method == 'POST':
        plan.name = request.form.get('name')
        plan.team_name = request.form.get('team')
        date_str = request.form.get('date')
        if date_str: plan.date = datetime.strptime(date_str, '%Y-%m-%d')
        plan.notes = request.form.get('notes')
        blocks_csv = request.form.get('blocks_csv')
        plan.structure = blocks_csv
        current_user.last_blocks_config = blocks_csv
        
        # Eliminar ejercicios existentes
        TrainingItem.query.filter_by(training_plan_id=plan.id).delete()
        
        # Añadir nuevos ejercicios si hay
        exercises_json = request.form.get('exercises_json', '{}')
        try:
            exercises_data = json.loads(exercises_json)
            for block_name, exercises in exercises_data.items():
                for idx, ex in enumerate(exercises):
                    item = TrainingItem(
                        training_plan_id=plan.id,
                        drill_id=ex['drill_id'],
                        block_name=block_name,
                        order=idx,
                        duration=ex.get('duration', 10)
                    )
                    db.session.add(item)
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
        
        db.session.commit()
        flash('Plan actualizado correctamente')
        return redirect(url_for('view_plan', id=plan.id))
    
    # Preparar datos para el template (igual que create_plan)
    user_blocks = plan.structure if plan.structure else STANDARD_BLOCKS
    blocks_list = user_blocks.split(',')
    tags = Tag.query.order_by(Tag.display_order.asc(), Tag.name.asc()).all()
    plan_date = plan.date.strftime('%Y-%m-%d') if plan.date else datetime.utcnow().strftime('%Y-%m-%d')
    
    # Preparar ejercicios existentes en formato JSON
    existing_exercises = {}
    for item in plan.items:
        if item.block_name not in existing_exercises:
            existing_exercises[item.block_name] = []
        existing_exercises[item.block_name].append({
            'drill_id': item.drill_id,
            'duration': item.duration
        })
    
    return render_template('create_plan.html', 
                         plan=plan, 
                         blocks=blocks_list, 
                         standard_blocks=STANDARD_BLOCKS, 
                         tags=tags, 
                         now=plan_date,
                         existing_exercises=json.dumps(existing_exercises))

@app.route('/drill/<int:id>')
def view_drill(id):
    drill = Drill.query.get_or_404(id)
    if not drill.is_public:
        if not current_user.is_authenticated or drill.user_id != current_user.id: return redirect('/')
    drill.views += 1
    db.session.commit()
    # Determinar el tipo de media para el template
    media_type = drill.media_type
    if media_type == 'link' and drill.external_link and 'youtu' in drill.external_link:
        media_type = 'youtube'
    elif media_type == 'image':
        media_type = 'image_file'
    elif media_type == 'video_file':
        media_type = 'video_file'
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

@app.route('/api/toggle_fav/<int:id>', methods=['POST'])
@login_required
def api_toggle_fav(id):
    drill = Drill.query.get(id)
    if drill:
        is_fav = drill in current_user.favoritos
        if is_fav:
            current_user.favoritos.remove(drill)
        else:
            current_user.favoritos.append(drill)
        db.session.commit()
        return jsonify({'status': 'ok', 'is_fav': not is_fav})
    return jsonify({'status': 'error'}), 404

# --- AUTH ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    # Registro público desactivado - solo por invitación
    flash('⚠️ El registro está cerrado. Necesitas una invitación para acceder.')
    return redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect('/')
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            if not user.actions_config: copy_actions_from_admin_to_user(user.id)
            # Registrar acceso
            access = UserAccess(user_id=user.id)
            db.session.add(access)
            db.session.commit()
            return redirect('/')
        else: flash('Email o contraseña incorrectos')
    return render_template('login.html')

@app.route('/login/google')
def google_login():
    # Usar localhost explícitamente para desarrollo local
    redirect_uri = 'http://localhost:5001/auth/callback'
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/callback')
def google_auth():
    try:
        token = google.authorize_access_token()
        if not token:
            flash('Error en la autenticación con Google')
            return redirect('/login')
        email = token.get('userinfo', {}).get('email')
        if not email:
            flash('No se pudo obtener el email de Google')
            return redirect('/login')
        
        user = User.query.filter_by(email=email).first()
        
        if not user:
            # Verificar si tiene invitación (excepto admin)
            is_admin = (email.lower() == 'jcaplliure@gmail.com')
            invitation = Invitation.query.filter_by(email=email.lower()).first()
            
            if not is_admin and not invitation:
                flash('❌ No tienes invitación. Contacta con el administrador.')
                return redirect('/login')
            
            # Crear usuario
            user = User(email=email, name=token.get('userinfo', {}).get('name', email.split('@')[0]), is_admin=is_admin)
            db.session.add(user)
            db.session.commit()
            copy_actions_from_admin_to_user(user.id)
            
            # Actualizar invitación si existe
            if invitation:
                invitation.registered_at = datetime.utcnow()
                invitation.user_id = user.id
                db.session.commit()
        
        login_user(user)
        if not user.actions_config:
            copy_actions_from_admin_to_user(user.id)
        
        # Registrar acceso
        access = UserAccess(user_id=user.id)
        db.session.add(access)
        db.session.commit()
        
        return redirect('/')
    except Exception as e:
        flash(f'Error en la autenticación: {str(e)}')
        return redirect('/login')

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
        action = request.form.get('action')
        if action == 'add_tag':
            tag_name = (request.form.get('tag_name') or '').strip()
            group_id = request.form.get('group_id', type=int)
            if tag_name and group_id and not Tag.query.filter_by(name=tag_name).first():
                db.session.add(Tag(name=tag_name, group_id=group_id, is_custom=False))
            db.session.commit()
        elif action == 'add_group_image':
            group_id = request.form.get('group_id', type=int)
            file = request.files.get('image')
            if group_id and file and file.filename != '':
                count = TagGroupImage.query.filter_by(group_id=group_id).count()
                if count >= 10:
                    flash('Máximo 10 imágenes por grupo')
                else:
                    filename = f"group_{group_id}_{int(datetime.now().timestamp())}.jpg"
                    comp = compress_image(file)
                    with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), 'wb') as f:
                        f.write(comp.getbuffer())
                    db.session.add(TagGroupImage(group_id=group_id, filename=filename))
                    db.session.commit()
        elif action == 'add_tag_image':
            tag_id = request.form.get('tag_id', type=int)
            file = request.files.get('image')
            if tag_id and file and file.filename != '':
                count = TagImage.query.filter_by(tag_id=tag_id).count()
                if count >= 10:
                    flash('Máximo 10 imágenes por etiqueta')
                else:
                    filename = f"tag_{tag_id}_{int(datetime.now().timestamp())}.jpg"
                    comp = compress_image(file)
                    with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), 'wb') as f:
                        f.write(comp.getbuffer())
                    db.session.add(TagImage(tag_id=tag_id, filename=filename))
                    db.session.commit()
        elif action == 'edit_tag':
            tag_id = request.form.get('tag_id', type=int)
            new_name = (request.form.get('tag_name') or '').strip()
            new_group_id = request.form.get('group_id', type=int)
            tag = Tag.query.get(tag_id)
            if tag and new_name:
                # Verificar que no exista otra etiqueta con ese nombre
                existing = Tag.query.filter(func.lower(Tag.name) == new_name.lower(), Tag.id != tag_id).first()
                if not existing:
                    tag.name = new_name
                    if new_group_id:
                        tag.group_id = new_group_id
                    db.session.commit()
                    flash(f'Etiqueta "{new_name}" actualizada')
                else:
                    flash(f'Ya existe una etiqueta con el nombre "{new_name}"')
        elif action == 'delete_tag':
            tag_id = request.form.get('tag_id', type=int)
            tag = Tag.query.get(tag_id)
            if tag:
                # Eliminar imágenes asociadas
                TagImage.query.filter_by(tag_id=tag_id).delete()
                db.session.delete(tag)
                db.session.commit()
                flash('Etiqueta eliminada')
        elif action == 'delete_tag_image':
            image_id = request.form.get('image_id', type=int)
            img = TagImage.query.get(image_id)
            if img:
                # Eliminar archivo físico
                try:
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], img.filename)
                    if os.path.exists(filepath):
                        os.remove(filepath)
                except:
                    pass
                db.session.delete(img)
                db.session.commit()
                flash('Imagen eliminada')
        elif action == 'delete_group_image':
            image_id = request.form.get('image_id', type=int)
            img = TagGroupImage.query.get(image_id)
            if img:
                # Eliminar archivo físico
                try:
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], img.filename)
                    if os.path.exists(filepath):
                        os.remove(filepath)
                except:
                    pass
                db.session.delete(img)
                db.session.commit()
                flash('Imagen eliminada')
    # Redirigir a la página de configuración unificada con la pestaña de etiquetas activa
    return redirect('/admin/config#tags')

@app.route('/api/custom_tag', methods=['POST'])
@login_required
def api_custom_tag():
    data = request.json or {}
    name = (data.get('name') or '').strip()
    group_id = data.get('group_id')
    if not name or not group_id:
        return jsonify({'error': 'Datos incompletos'}), 400
    group = TagGroup.query.get(group_id)
    if not group:
        return jsonify({'error': 'Grupo inválido'}), 400
    existing = Tag.query.filter(func.lower(Tag.name) == name.lower()).first()
    if existing:
        return jsonify({'error': 'La etiqueta ya existe'}), 400
    custom_count = Tag.query.filter_by(user_id=current_user.id, is_custom=True).count()
    if custom_count >= 5:
        return jsonify({'error': 'Máximo 5 etiquetas personalizadas'}), 400
    tag = Tag(name=name, group_id=group.id, user_id=current_user.id, is_custom=True)
    db.session.add(tag)
    db.session.commit()
    return jsonify({'status': 'ok', 'id': tag.id, 'name': tag.name, 'group_id': tag.group_id})

@app.route('/user/tags')
@login_required
def user_tags():
    custom_tags = Tag.query.filter_by(user_id=current_user.id, is_custom=True).all()
    tag_groups = TagGroup.query.order_by(TagGroup.display_order).all()
    theme_color = current_user.theme_color
    if not theme_color:
        conf = SiteConfig.query.get('primary_color')
        theme_color = conf.value if conf else '#FFD700'
    return render_template('user_tags.html', custom_tags=custom_tags, tag_groups=tag_groups, theme_color=theme_color)

@app.route('/api/custom_tag/<int:tag_id>', methods=['PUT'])
@login_required
def api_custom_tag_update(tag_id):
    tag = Tag.query.get_or_404(tag_id)
    if tag.user_id != current_user.id or not tag.is_custom:
        return jsonify({'error': 'No tienes permiso para editar esta etiqueta'}), 403
    data = request.json or {}
    name = (data.get('name') or '').strip()
    group_id = data.get('group_id')
    if not name:
        return jsonify({'error': 'El nombre es requerido'}), 400
    existing = Tag.query.filter(func.lower(Tag.name) == name.lower(), Tag.id != tag_id).first()
    if existing:
        return jsonify({'error': 'Ya existe una etiqueta con ese nombre'}), 400
    tag.name = name
    if group_id:
        group = TagGroup.query.get(group_id)
        if group:
            tag.group_id = group.id
    db.session.commit()
    return jsonify({'status': 'ok', 'id': tag.id, 'name': tag.name})

@app.route('/api/custom_tag/<int:tag_id>', methods=['DELETE'])
@login_required
def api_custom_tag_delete(tag_id):
    tag = Tag.query.get_or_404(tag_id)
    if tag.user_id != current_user.id or not tag.is_custom:
        return jsonify({'error': 'No tienes permiso para eliminar esta etiqueta'}), 403
    drills_with_tag = Drill.query.filter(
        or_(Drill.primary_tag_id == tag_id, Drill.secondary_tags.any(id=tag_id))
    ).all()
    for drill in drills_with_tag:
        if drill.primary_tag_id == tag_id:
            drill.primary_tag_id = None
        if tag in drill.secondary_tags:
            drill.secondary_tags.remove(tag)
    db.session.delete(tag)
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/reorder_tag', methods=['POST'])
@login_required
def api_reorder_tag():
    if not current_user.is_admin:
        return jsonify({'error': 'No autorizado'}), 403
    data = request.json or {}
    tag_id = data.get('tag_id')
    direction = data.get('direction')  # 'up' o 'down'
    if not tag_id or direction not in ('up', 'down'):
        return jsonify({'error': 'Datos incompletos'}), 400
    tag = Tag.query.get(tag_id)
    if not tag:
        return jsonify({'error': 'Etiqueta no encontrada'}), 404
    # Obtener todas las etiquetas del mismo grupo ordenadas
    tags_in_group = Tag.query.filter_by(group_id=tag.group_id).order_by(Tag.display_order.asc(), Tag.name.asc()).all()
    # Encontrar el índice actual
    current_idx = next((i for i, t in enumerate(tags_in_group) if t.id == tag_id), None)
    if current_idx is None:
        return jsonify({'error': 'Etiqueta no encontrada en grupo'}), 404
    # Calcular nuevo índice
    if direction == 'up' and current_idx > 0:
        swap_idx = current_idx - 1
    elif direction == 'down' and current_idx < len(tags_in_group) - 1:
        swap_idx = current_idx + 1
    else:
        return jsonify({'status': 'ok', 'message': 'No se puede mover más'})
    # Intercambiar órdenes
    tag_a = tags_in_group[current_idx]
    tag_b = tags_in_group[swap_idx]
    tag_a.display_order, tag_b.display_order = swap_idx, current_idx
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/tag_cover_preview/<int:tag_id>')
def api_tag_cover_preview(tag_id):
    tag = Tag.query.get_or_404(tag_id)
    filename = pick_cover_from_tag(tag)
    if filename:
        return jsonify({'url': url_for('static', filename='uploads/' + filename)})
    conf = SiteConfig.query.get('generic_bg')
    if conf and conf.value:
        if conf.value.startswith('http'):
            return jsonify({'url': conf.value})
        return jsonify({'url': url_for('static', filename='uploads/' + conf.value)})
    return jsonify({'url': 'https://placehold.co/600x400/0d1f2d/FFF?text=Etiqueta'})

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
    # Datos para la pestaña de etiquetas
    groups = TagGroup.query.order_by(TagGroup.display_order.asc(), TagGroup.name.asc()).all()
    tags = Tag.query.join(TagGroup, Tag.group_id == TagGroup.id, isouter=True).order_by(
        TagGroup.display_order.asc(), TagGroup.name.asc(), Tag.display_order.asc(), Tag.name.asc()
    ).all()
    # Color del tema
    theme_setting = AppSettings.query.filter_by(key='primary_color').first()
    theme_color = theme_setting.value if theme_setting else '#FFD700'
    return render_template('admin_config.html', config_dict=config_dict, keys_needed=keys_needed,
                           groups=groups, tags=tags, theme_color=theme_color)

@app.route('/admin/update_primary_color', methods=['POST'])
@login_required
def admin_update_primary_color():
    if not current_user.is_admin: return jsonify({'error': 'No autorizado'}), 403
    color = request.json.get('color', '').strip()
    if not color or not color.startswith('#'):
        return jsonify({'error': 'Color inválido'}), 400
    
    setting = AppSettings.query.filter_by(key='primary_color').first()
    if not setting:
        setting = AppSettings(key='primary_color', value=color)
        db.session.add(setting)
    else:
        setting.value = color
    db.session.commit()
    return jsonify({'status': 'ok', 'color': color})

@app.route('/user/update_theme_color', methods=['POST'])
@login_required
def user_update_theme_color():
    color = request.json.get('color', '').strip()
    if color and not color.startswith('#'):
        return jsonify({'error': 'Color inválido'}), 400
    
    current_user.theme_color = color if color else None
    db.session.commit()
    return jsonify({'status': 'ok', 'color': color or get_user_theme_color()})

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
        rejected = []
        line_num = 0
        for row in csv_input:
            line_num += 1
            if len(row) < 3:
                rejected.append(f"Línea {line_num}: columnas insuficientes")
                continue
            link = row[0].strip()
            desc = row[1].strip()
            primary_name = row[2].strip()
            secondary_raw = row[3].strip() if len(row) > 3 else ''
            secondary_names = [t.strip() for t in secondary_raw.split(',') if t.strip()]
            all_tag_names = [primary_name] + secondary_names
            if len(all_tag_names) > 3:
                rejected.append(f"Línea {line_num}: más de 3 etiquetas")
                continue
            primary_tag = Tag.query.filter(func.lower(Tag.name) == primary_name.lower()).first()
            if not primary_tag:
                rejected.append(f"Línea {line_num}: etiqueta principal no existe ({primary_name})")
                continue
            secondary_tags = []
            invalid = False
            for sec_name in secondary_names[:2]:
                sec_tag = Tag.query.filter(func.lower(Tag.name) == sec_name.lower()).first()
                if not sec_tag:
                    rejected.append(f"Línea {line_num}: etiqueta secundaria no existe ({sec_name})")
                    invalid = True
                    break
                secondary_tags.append(sec_tag)
            if invalid:
                continue
            existing_drill = Drill.query.filter_by(external_link=link).first()
            target_drill = None
            if existing_drill:
                target_drill = existing_drill
                target_drill.description = desc
                target_drill.primary_tag_id = primary_tag.id
                target_drill.secondary_tags = secondary_tags
                target_drill.cover_image = pick_cover_from_tag(primary_tag)
                count_updated += 1
            else:
                title = desc[:60] if desc else "Ejercicio importado"
                target_drill = Drill(
                    title=title,
                    description=desc,
                    external_link=link,
                    media_type='link',
                    user_id=current_user.id,
                    is_public=True,
                    primary_tag_id=primary_tag.id,
                    cover_image=pick_cover_from_tag(primary_tag)
                )
                target_drill.secondary_tags = secondary_tags
                db.session.add(target_drill)
                count_success += 1
            db.session.commit()
        flash(f'✅ Importación: {count_success} nuevos, {count_updated} actualizados, {len(rejected)} rechazados.')
        if rejected:
            flash('Filas rechazadas: ' + ' | '.join(rejected))
    except Exception as e: flash(f'❌ Error al importar: {str(e)}')
    return redirect('/admin/config')

@app.route('/admin/download_db')
@login_required
def download_db():
    if not current_user.is_admin: return redirect('/')
    path = os.path.join(basedir, 'basket.db')
    return send_file(path, as_attachment=True)

# --- SISTEMA DE INVITACIONES ---

@app.route('/admin/invitations')
@login_required
def admin_invitations():
    if not current_user.is_admin: return redirect('/')
    invitations = Invitation.query.order_by(Invitation.invited_at.desc()).all()
    
    # Calcular accesos últimos 30 días para cada usuario
    from datetime import timedelta
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    invitation_data = []
    for inv in invitations:
        data = {
            'email': inv.email,
            'invited_at': inv.invited_at,
            'registered_at': inv.registered_at,
            'accesses_30d': 0,
            'last_access': None
        }
        if inv.user_id:
            # Contar accesos últimos 30 días
            data['accesses_30d'] = UserAccess.query.filter(
                UserAccess.user_id == inv.user_id,
                UserAccess.accessed_at >= thirty_days_ago
            ).count()
            # Último acceso
            last = UserAccess.query.filter_by(user_id=inv.user_id).order_by(UserAccess.accessed_at.desc()).first()
            if last:
                data['last_access'] = last.accessed_at
        invitation_data.append(data)
    
    return render_template('admin_invitations.html', invitations=invitation_data)

@app.route('/admin/invite', methods=['POST'])
@login_required
def admin_invite():
    if not current_user.is_admin: return redirect('/')
    email = request.form.get('email', '').strip().lower()
    
    if not email:
        flash('❌ Introduce un email válido')
        return redirect('/admin/invitations')
    
    # Verificar si ya existe
    existing = Invitation.query.filter_by(email=email).first()
    if existing:
        flash(f'⚠️ Ya existe una invitación para {email}')
        return redirect('/admin/invitations')
    
    # Crear invitación
    token = secrets.token_urlsafe(32)
    invitation = Invitation(email=email, token=token)
    db.session.add(invitation)
    db.session.commit()
    
    # Intentar enviar email
    try:
        send_invitation_email(email, token)
        flash(f'✅ Invitación enviada a {email}')
    except Exception as e:
        flash(f'⚠️ Invitación creada pero no se pudo enviar el email: {str(e)}')
    
    return redirect('/admin/invitations')

@app.route('/admin/resend_invite/<email>')
@login_required
def resend_invite(email):
    if not current_user.is_admin: return redirect('/')
    invitation = Invitation.query.filter_by(email=email).first()
    if invitation and not invitation.registered_at:
        try:
            send_invitation_email(email, invitation.token)
            flash(f'✅ Invitación reenviada a {email}')
        except Exception as e:
            flash(f'❌ Error al reenviar: {str(e)}')
    return redirect('/admin/invitations')

@app.route('/admin/delete_invite/<email>')
@login_required
def delete_invite(email):
    if not current_user.is_admin: return redirect('/')
    invitation = Invitation.query.filter_by(email=email).first()
    if invitation and not invitation.registered_at:
        db.session.delete(invitation)
        db.session.commit()
        flash(f'✅ Invitación eliminada')
    return redirect('/admin/invitations')

def send_invitation_email(email, token):
    """Enviar email de invitación"""
    # Configuración SMTP (configurar según tu proveedor)
    smtp_host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_user = os.environ.get('SMTP_USER', '')
    smtp_pass = os.environ.get('SMTP_PASS', '')
    
    if not smtp_user or not smtp_pass:
        raise Exception('SMTP no configurado. Configura SMTP_USER y SMTP_PASS')
    
    # URL de registro
    register_url = f"http://localhost:5001/register/{token}"
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = '🏀 Invitación a EntrenadorBasket'
    msg['From'] = smtp_user
    msg['To'] = email
    
    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background: #0a1929; color: white; padding: 20px;">
        <div style="max-width: 500px; margin: 0 auto; background: #0d1f2d; padding: 30px; border-radius: 12px;">
            <h1 style="color: #3b82f6;">🏀 EntrenadorBasket</h1>
            <p>Has sido invitado a unirte a la plataforma de gestión de equipos de baloncesto.</p>
            <p>Haz clic en el siguiente enlace para crear tu cuenta:</p>
            <a href="{register_url}" style="display: inline-block; background: #3b82f6; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; margin: 20px 0;">
                Crear mi cuenta
            </a>
            <p style="color: #888; font-size: 12px;">Si no esperabas esta invitación, puedes ignorar este mensaje.</p>
        </div>
    </body>
    </html>
    """
    
    msg.attach(MIMEText(html, 'html'))
    
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, email, msg.as_string())

@app.route('/register/<token>', methods=['GET', 'POST'])
def register_with_invitation(token):
    """Registro con token de invitación"""
    invitation = Invitation.query.filter_by(token=token).first()
    
    if not invitation:
        flash('❌ Enlace de invitación inválido')
        return redirect('/login')
    
    if invitation.registered_at:
        flash('⚠️ Esta invitación ya fue utilizada')
        return redirect('/login')
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        password = request.form.get('password', '')
        
        if not name or not password:
            flash('❌ Completa todos los campos')
            return render_template('register_invite.html', email=invitation.email, token=token)
        
        # Crear usuario
        user = User(email=invitation.email, name=name)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        # Actualizar invitación
        invitation.registered_at = datetime.utcnow()
        invitation.user_id = user.id
        db.session.commit()
        
        # Copiar acciones del admin
        copy_actions_from_admin_to_user(user.id)
        
        # Login automático
        login_user(user)
        
        # Registrar acceso
        access = UserAccess(user_id=user.id)
        db.session.add(access)
        db.session.commit()
        
        flash('✅ ¡Bienvenido a EntrenadorBasket!')
        return redirect('/')
    
    return render_template('register_invite.html', email=invitation.email, token=token)

# --- TEAMS & PLAYERS ---

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
    owned = Team.query.filter_by(user_id=current_user.id).all()
    staff_memberships = TeamStaff.query.filter_by(email=current_user.email, status='accepted').all()
    staff_teams = [s.team for s in staff_memberships]
    all_teams = list(set(owned + staff_teams))
    return render_template('my_teams.html', teams=all_teams)

@app.route('/team/<int:id>', methods=['GET', 'POST'])
@login_required
def view_team(id):
    team = Team.query.get_or_404(id)
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return redirect('/')
    if request.method == 'POST':
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
    
    sessions = TrainingSession.query.filter_by(team_id=team.id, status='finished').order_by(TrainingSession.date.desc()).all()
    team_actions = ActionDefinition.query.filter_by(team_id=team.id).order_by(ActionDefinition.display_section, ActionDefinition.display_order).all()
    if not team_actions:
        team_actions = get_actions_for_user(team.user_id, include_hidden=True)
    team_rankings = RankingDefinition.query.filter_by(team_id=team.id).all()
    if not team_rankings:
        team_rankings = RankingDefinition.query.filter_by(user_id=team.user_id, team_id=None).all()
    categories = ActionCategory.query.filter_by(team_id=team.id).all()
    
    # Obtener ejercicios de la galería ordenados con sus notas
    gallery_items = TeamGalleryItem.query.filter_by(team_id=team.id).order_by(TeamGalleryItem.display_order).all()
    drill_notes = {item.drill_id: item.note for item in gallery_items}
    drill_order = {item.drill_id: item.display_order for item in gallery_items}
    
    # Ordenar gallery_drills según TeamGalleryItem.display_order
    gallery_items_ordered = []
    for d in team.gallery_drills:
        if not d.cover_image and d.primary_tag:
            d.cover_fallback = pick_cover_from_tag(d.primary_tag)
        else:
            d.cover_fallback = None
        d.origin = get_drill_origin(d)
        d.gallery_note = drill_notes.get(d.id, '')
        d.gallery_order = drill_order.get(d.id, 999)
        gallery_items_ordered.append(d)
    
    # Ordenar por display_order
    gallery_items_ordered.sort(key=lambda x: x.gallery_order)
    
    return render_template('view_team.html', team=team, is_owner=is_owner, sessions=sessions, actions=team_actions, rankings=team_rankings, categories=categories, gallery_items_ordered=gallery_items_ordered)

def _user_teams():
    owned = Team.query.filter_by(user_id=current_user.id).all()
    staff = [s.team for s in TeamStaff.query.filter_by(email=current_user.email, status='accepted').all()]
    return list(set(owned + staff))

def _can_edit_team(team):
    if team.user_id == current_user.id: return True
    return bool(TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first())

@app.route('/api/my_teams', methods=['GET'])
@login_required
def api_my_teams():
    teams = _user_teams()
    teams_data = []
    for team in teams:
        teams_data.append({
            'id': team.id,
            'name': team.name,
            'logo_file': team.logo_file
        })
    return jsonify({'teams': teams_data})

@app.route('/api/team/<int:team_id>/category_add', methods=['POST'])
@login_required
def api_team_category_add(team_id):
    team = Team.query.get_or_404(team_id)
    if not _can_edit_team(team): return jsonify({'error': 'No autorizado'}), 403
    name = (request.json or request.form).get('name', '').strip()
    if not name: return jsonify({'error': 'Nombre vacío'}), 400
    c = ActionCategory(name=name, team_id=team_id)
    db.session.add(c)
    db.session.commit()
    return jsonify({'status': 'ok', 'id': c.id})

@app.route('/api/team/<int:team_id>/category_delete/<int:cid>', methods=['POST'])
@login_required
def api_team_category_delete(team_id, cid):
    team = Team.query.get_or_404(team_id)
    if not _can_edit_team(team): return jsonify({'error': 'No autorizado'}), 403
    c = ActionCategory.query.filter_by(id=cid, team_id=team_id).first()
    if c:
        db.session.delete(c)
        db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/team/<int:team_id>/action_add', methods=['POST'])
@login_required
def api_team_action_add(team_id):
    team = Team.query.get_or_404(team_id)
    if not _can_edit_team(team): return jsonify({'error': 'No autorizado'}), 403
    d = request.json or request.form
    name = (d.get('name') or '').strip()[:8]
    if not name: return jsonify({'error': 'Nombre vacío'}), 400
    try:
        val = float(d.get('value', 1))
    except (TypeError, ValueError):
        val = 1.0
    val = max(-10, min(10, val))
    is_pos = (d.get('is_positive') not in (False, 'false', '0', 0)) if val >= 0 else False
    if val < 0: is_pos = False
    icon = (d.get('icon') or '').strip() or None
    apply_all = d.get('apply_to_all') in (True, 'true', '1', 1)
    team_ids = [team_id]
    if apply_all:
        team_ids = [t.id for t in _user_teams()]
    for tid in team_ids:
        a = ActionDefinition(name=name, value=val, is_positive=is_pos, icon=icon, user_id=team.user_id, team_id=tid)
        db.session.add(a)
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/team/<int:team_id>/action_update', methods=['POST'])
@login_required
def api_team_action_update(team_id):
    team = Team.query.get_or_404(team_id)
    if not _can_edit_team(team): return jsonify({'error': 'No autorizado'}), 403
    d = request.json or request.form
    aid = d.get('action_id')
    act = ActionDefinition.query.filter_by(id=aid, team_id=team_id).first() if aid else None
    if not act: return jsonify({'error': 'Acción no encontrada'}), 404
    apply_all = d.get('apply_to_all') in (True, 'true', '1', 1)
    teams = [team] if not apply_all else _user_teams()
    for t in teams:
        others = ActionDefinition.query.filter_by(team_id=t.id, name=act.name).all()
        for o in others:
            if 'value' in d: o.value = max(-10, min(10, float(d.get('value', o.value))))
            if 'name' in d: o.name = (d.get('name') or '')[:8]
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/team/<int:team_id>/action_delete/<int:aid>', methods=['POST'])
@login_required
def api_team_action_delete(team_id, aid):
    team = Team.query.get_or_404(team_id)
    if not _can_edit_team(team): return jsonify({'error': 'No autorizado'}), 403
    act = ActionDefinition.query.filter_by(id=aid, team_id=team_id).first()
    if not act: return jsonify({'error': 'No encontrada'}), 404
    name = act.name
    apply_all = (request.json or request.form or {}).get('apply_to_all') in (True, 'true', '1', 1)
    teams = [team_id] if not apply_all else [t.id for t in _user_teams()]
    for tid in teams:
        for a in ActionDefinition.query.filter_by(team_id=tid, name=name).all():
            db.session.delete(a)
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/team/<int:team_id>/ranking_add', methods=['POST'])
@login_required
def api_team_ranking_add(team_id):
    team = Team.query.get_or_404(team_id)
    if not _can_edit_team(team): return jsonify({'error': 'No autorizado'}), 403
    d = request.json or request.form
    name = (d.get('name') or '').strip()
    if not name: return jsonify({'error': 'Nombre vacío'}), 400
    icon = (d.get('icon') or 'trophy').strip()
    raw = d.get('action_ids') or d.getlist('action_ids') or []
    action_ids = [int(x) for x in raw if str(x).isdigit()]
    apply_all = d.get('apply_to_all') in (True, 'true', '1', 1)
    team_ids = [team_id]
    if apply_all: team_ids = [t.id for t in _user_teams()]
    action_names = []
    for aid in action_ids:
        a = ActionDefinition.query.filter_by(id=aid, team_id=team_id).first()
        if a: action_names.append(a.name)
    for tid in team_ids:
        r = RankingDefinition(name=name, icon=icon, user_id=team.user_id, team_id=tid)
        db.session.add(r)
        db.session.flush()
        for aname in action_names:
            a = ActionDefinition.query.filter_by(team_id=tid, name=aname).first()
            if a: r.ingredients.append(a)
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/team/<int:team_id>/ranking_delete/<int:rid>', methods=['POST'])
@login_required
def api_team_ranking_delete(team_id, rid):
    team = Team.query.get_or_404(team_id)
    if not _can_edit_team(team): return jsonify({'error': 'No autorizado'}), 403
    r = RankingDefinition.query.filter_by(id=rid, team_id=team_id).first()
    if not r: return jsonify({'error': 'No encontrado'}), 404
    name = r.name
    apply_all = (request.json or request.form or {}).get('apply_to_all') in (True, 'true', '1', 1)
    teams = [team_id] if not apply_all else [t.id for t in _user_teams()]
    for tid in teams:
        for x in RankingDefinition.query.filter_by(team_id=tid, name=name).all():
            db.session.delete(x)
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/team_attendance_stats/<int:team_id>', methods=['GET'])
@login_required
def api_team_attendance_stats(team_id):
    team = Team.query.get_or_404(team_id)
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return jsonify({'error': 'No autorizado'}), 403
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    query = TrainingSession.query.filter_by(team_id=team_id, status='finished')
    if start_date:
        query = query.filter(TrainingSession.date >= datetime.strptime(start_date, '%Y-%m-%d'))
    if end_date:
        query = query.filter(TrainingSession.date <= datetime.strptime(end_date, '%Y-%m-%d'))
    
    sessions = query.order_by(TrainingSession.date.desc()).all()
    
    # Calcular estadísticas
    player_stats = {}
    sessions_list = []
    
    for session in sessions:
        plan = TrainingPlan.query.get(session.plan_id) if session.plan_id else None
        session_data = {
            'id': session.id,
            'date': session.date.strftime('%d/%m/%Y'),
            'plan_name': plan.name if plan else 'Sin plan',
            'players_present': []
        }
        
        for att in session.attendance:
            if att.is_present:
                player = Player.query.get(att.player_id)
                if player:
                    session_data['players_present'].append({
                        'id': player.id,
                        'name': player.name,
                        'dorsal': player.dorsal
                    })
                    
                    # Actualizar estadísticas del jugador
                    if player.id not in player_stats:
                        player_stats[player.id] = {
                            'name': player.name,
                            'dorsal': player.dorsal,
                            'photo': player.photo_file,
                            'total_sessions': 0,
                            'attended': 0
                        }
                    player_stats[player.id]['total_sessions'] += 1
                    player_stats[player.id]['attended'] += 1
        
        sessions_list.append(session_data)
    
    # Calcular porcentajes y ordenar por asistencia
    attendance_ranking = []
    for pid, stats in player_stats.items():
        percentage = (stats['attended'] / stats['total_sessions'] * 100) if stats['total_sessions'] > 0 else 0
        attendance_ranking.append({
            **stats,
            'percentage': round(percentage, 1),
            'player_id': pid
        })
    
    attendance_ranking.sort(key=lambda x: x['attended'], reverse=True)
    
    return jsonify({
        'sessions': sessions_list,
        'ranking': attendance_ranking,
        'total_sessions': len(sessions)
    })

@app.route('/edit_team_settings/<int:id>', methods=['POST'])
@login_required
def edit_team_settings(id):
    team = Team.query.get_or_404(id)
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return redirect('/')
    team.name = request.form.get('name')
    file = request.files.get('logo')
    if file and file.filename != '':
        logo_filename = f"team_{int(datetime.now().timestamp())}.jpg"
        comp = compress_image(file)
        with open(os.path.join(app.config['UPLOAD_FOLDER'], logo_filename), 'wb') as f: f.write(comp.getbuffer())
        team.logo_file = logo_filename
    team.visibility_mode = request.form.get('visibility_mode', 'fixed')
    team.visibility_top_x = int(request.form.get('visibility_top_x', 3))
    team.visibility_top_pct = int(request.form.get('visibility_top_pct', 25))
    team.quarters = int(request.form.get('quarters', 4))
    db.session.commit()
    flash('Equipo actualizado')
    return redirect(url_for('view_team', id=team.id))

@app.route('/api/save_team_notes', methods=['POST'])
@login_required
def api_save_team_notes():
    data = request.json
    team_id = data.get('team_id')
    notes = data.get('notes', '')
    team = Team.query.get_or_404(team_id)
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return jsonify({'error': 'Unauthorized'}), 403
    team.public_notes = notes
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/add_to_gallery', methods=['POST'])
@login_required
def api_add_to_gallery():
    data = request.json
    team_id = data.get('team_id')
    drill_id = data.get('drill_id')
    team = Team.query.get_or_404(team_id)
    drill = Drill.query.get_or_404(drill_id)
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return jsonify({'error': 'Unauthorized'}), 403
    if drill not in team.gallery_drills:
        team.gallery_drills.append(drill)
        db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/remove_from_gallery', methods=['POST'])
@login_required
def api_remove_from_gallery():
    data = request.json
    team_id = data.get('team_id')
    drill_id = data.get('drill_id')
    team = Team.query.get_or_404(team_id)
    drill = Drill.query.get_or_404(drill_id)
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return jsonify({'error': 'Unauthorized'}), 403
    if drill in team.gallery_drills:
        team.gallery_drills.remove(drill)
        # También eliminar el TeamGalleryItem asociado
        TeamGalleryItem.query.filter_by(team_id=team_id, drill_id=drill_id).delete()
        db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/save_analytics_settings', methods=['POST'])
@login_required
def api_save_analytics_settings():
    """Guardar configuración de analytics del portal público"""
    data = request.json
    team_id = data.get('team_id')
    analytics_visible = data.get('analytics_visible', False)
    analytics_players_count = data.get('analytics_players_count', 5)
    
    team = Team.query.get_or_404(team_id)
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff:
        return jsonify({'error': 'Unauthorized'}), 403
    
    team.analytics_visible = analytics_visible
    team.analytics_players_count = int(analytics_players_count)
    
    # Guardar configuración de gráficos individuales
    if 'chart_all_visible' in data:
        team.chart_all_visible = data.get('chart_all_visible', False)
    if 'chart_attack_visible' in data:
        team.chart_attack_visible = data.get('chart_attack_visible', False)
    if 'chart_attack_no_shots_visible' in data:
        team.chart_attack_no_shots_visible = data.get('chart_attack_no_shots_visible', False)
    if 'chart_defense_visible' in data:
        team.chart_defense_visible = data.get('chart_defense_visible', False)
    
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/save_gallery_item_note', methods=['POST'])
@login_required
def api_save_gallery_item_note():
    """Guardar nota de un ejercicio en la galería"""
    data = request.json
    team_id = data.get('team_id')
    drill_id = data.get('drill_id')
    note = data.get('note', '')
    
    team = Team.query.get_or_404(team_id)
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff:
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Buscar o crear el TeamGalleryItem
    item = TeamGalleryItem.query.filter_by(team_id=team_id, drill_id=drill_id).first()
    if not item:
        item = TeamGalleryItem(team_id=team_id, drill_id=drill_id)
        db.session.add(item)
    item.note = note
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/reorder_gallery', methods=['POST'])
@login_required
def api_reorder_gallery():
    """Reordenar ejercicios de la galería"""
    data = request.json
    team_id = data.get('team_id')
    order = data.get('order', [])  # Lista de drill_ids en orden
    
    team = Team.query.get_or_404(team_id)
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff:
        return jsonify({'error': 'Unauthorized'}), 403
    
    for idx, drill_id in enumerate(order):
        item = TeamGalleryItem.query.filter_by(team_id=team_id, drill_id=drill_id).first()
        if not item:
            item = TeamGalleryItem(team_id=team_id, drill_id=drill_id)
            db.session.add(item)
        item.display_order = idx
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/get_team_players')
@login_required
def api_get_team_players():
    team_id = request.args.get('team_id')
    team = Team.query.get_or_404(team_id)
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return jsonify({'error': 'Unauthorized'}), 403
    
    players = []
    for player in team.players:
        players.append({
            'id': player.id,
            'name': player.name,
            'dorsal': player.dorsal,
            'photo': player.photo_file
        })
    
    return jsonify({'players': players})

@app.route('/api/start_session_from_court', methods=['POST'])
@login_required
def api_start_session_from_court():
    data = request.json
    plan_id = data.get('plan_id')
    team_id = data.get('team_id')
    player_ids = data.get('player_ids', [])
    
    team = Team.query.get_or_404(team_id)
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return jsonify({'error': 'Unauthorized'}), 403
    
    # Crear nueva sesión
    new_session = TrainingSession(team_id=team_id, plan_id=plan_id, status='active')
    db.session.add(new_session)
    db.session.flush()
    
    # Añadir asistencia para TODOS los jugadores del equipo (presentes y ausentes)
    for player in team.players:
        is_present = player.id in player_ids
        att = SessionAttendance(session_id=new_session.id, player_id=player.id, is_present=is_present)
        db.session.add(att)
    
    db.session.commit()
    return jsonify({'status': 'ok', 'session_id': new_session.id})

@app.route('/api/get_absent_players')
@login_required
def api_get_absent_players():
    session_id = request.args.get('session_id')
    session = TrainingSession.query.get_or_404(session_id)
    team = session.team
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return jsonify({'error': 'Unauthorized'}), 403
    
    # Obtener jugadores ausentes (del equipo pero no presentes en sesión)
    attendance_map = {att.player_id: att.is_present for att in session.attendance}
    absent_players = []
    
    for player in team.players:
        if not attendance_map.get(player.id, False):
            absent_players.append({
                'id': player.id,
                'name': player.name,
                'dorsal': player.dorsal,
                'photo': player.photo_file
            })
    
    return jsonify({'players': absent_players})

@app.route('/api/save_exercise_execution', methods=['POST'])
@login_required
def api_save_exercise_execution():
    data = request.json
    session_id = data.get('session_id')
    training_item_id = data.get('training_item_id')
    was_completed = data.get('was_completed', True)
    actual_duration = data.get('actual_duration')
    
    session = TrainingSession.query.get_or_404(session_id)
    team = session.team
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return jsonify({'error': 'Unauthorized'}), 403
    
    # Buscar ejecución existente o crear nueva
    execution = SessionItemExecution.query.filter_by(
        session_id=session_id,
        training_item_id=training_item_id
    ).first()
    
    if execution:
        execution.was_completed = was_completed
        execution.actual_duration = actual_duration
        if was_completed:
            execution.completed_at = datetime.utcnow()
        else:
            execution.completed_at = None
    else:
        execution = SessionItemExecution(
            session_id=session_id,
            training_item_id=training_item_id,
            was_completed=was_completed,
            actual_duration=actual_duration,
            completed_at=datetime.utcnow() if was_completed else None
        )
        db.session.add(execution)
    
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/finish_session/<int:session_id>', methods=['POST'])
@login_required
def api_finish_session(session_id):
    session = TrainingSession.query.get_or_404(session_id)
    team = session.team
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return jsonify({'error': 'Unauthorized'}), 403
    
    session.status = 'finished'
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/get_finished_sessions')
@login_required
def api_get_finished_sessions():
    team_id = request.args.get('team_id')
    team = Team.query.get_or_404(team_id)
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return jsonify({'error': 'Unauthorized'}), 403
    
    sessions = TrainingSession.query.filter_by(team_id=team_id, status='finished').order_by(TrainingSession.date.desc()).all()
    
    result = []
    for session in sessions:
        # Jugadores presentes
        players_present = [{'id': att.player.id, 'name': att.player.name, 'dorsal': att.player.dorsal} 
                          for att in session.attendance if att.is_present]
        
        # Ejercicios del plan
        exercises = []
        if session.plan:
            for item in session.plan.items:
                # Buscar ejecución
                execution = SessionItemExecution.query.filter_by(
                    session_id=session.id,
                    training_item_id=item.id
                ).first()
                
                # Buscar gamificación
                gamification = []
                scores = SessionScore.query.filter_by(session_id=session.id, drill_id=item.drill_id).all()
                if scores:
                    # Ordenar por puntos (mejor a peor)
                    sorted_scores = sorted(scores, key=lambda x: x.points, reverse=True)
                    for score in sorted_scores:
                        player = Player.query.get(score.player_id)
                        if player:
                            gamification.append({
                                'player_name': player.name,
                                'player_dorsal': player.dorsal,
                                'raw_score': score.raw_score,
                                'points': score.points
                            })
                
                exercises.append({
                    'id': item.id,
                    'title': item.drill.title,
                    'planned_duration': item.duration,
                    'was_completed': execution.was_completed if execution else True,
                    'actual_duration': execution.actual_duration if execution else item.duration,
                    'gamification': gamification
                })
        
        result.append({
            'id': session.id,
            'date': session.date.isoformat() if session.date else None,
            'plan_name': session.plan.name if session.plan else None,
            'players_present': players_present,
            'exercises': exercises
        })
    
    return jsonify({'sessions': result})

@app.route('/edit_session/<int:session_id>')
@login_required
def edit_session(session_id):
    session = TrainingSession.query.get_or_404(session_id)
    team = session.team
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return redirect('/')
    
    plan = session.plan
    attendance_map = {att.player_id: att.is_present for att in session.attendance}
    
    # Obtener ejecuciones de ejercicios
    executions = {ex.training_item_id: ex for ex in session.executions}
    
    # Obtener gamificaciones por ejercicio
    gamifications = {}
    if plan:
        for item in plan.items:
            scores = SessionScore.query.filter_by(session_id=session.id, drill_id=item.drill_id).all()
            if scores:
                gamifications[item.id] = sorted(scores, key=lambda x: x.points, reverse=True)
    
    return render_template('edit_session.html', session=session, plan=plan, 
                         attendance_map=attendance_map, executions=executions, 
                         gamifications=gamifications)

@app.route('/api/recalculate_gamification', methods=['POST'])
@login_required
def api_recalculate_gamification():
    data = request.json
    session_id = data.get('session_id')
    drill_id = data.get('drill_id')
    scores_data = data.get('scores', [])
    
    session = TrainingSession.query.get_or_404(session_id)
    team = session.team
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return jsonify({'error': 'Unauthorized'}), 403
    
    # Actualizar raw_scores
    for score_data in scores_data:
        score = SessionScore.query.get(score_data['score_id'])
        if score and score.session_id == session_id and score.drill_id == drill_id:
            score.raw_score = score_data['raw_score']
    
    db.session.flush()
    
    # Obtener criterio del ejercicio (por defecto "higher")
    # Buscar en la primera gamificación guardada para este drill
    first_score = SessionScore.query.filter_by(session_id=session_id, drill_id=drill_id).first()
    criteria = 'higher'  # Por defecto, asumimos "mayor es mejor"
    
    # Recalcular puntos basándose en raw_scores
    all_scores = SessionScore.query.filter_by(session_id=session_id, drill_id=drill_id).all()
    raw_scores = [(s.player_id, s.raw_score) for s in all_scores if s.raw_score > 0]
    
    if criteria == 'higher':
        raw_scores.sort(key=lambda x: x[1], reverse=True)
    else:
        raw_scores.sort(key=lambda x: x[1])
    
    # Asignar puntos
    points_map = {}
    for rank, (player_id, raw_score) in enumerate(raw_scores, 1):
        if len(raw_scores) == 1:
            points = 15
        elif len(raw_scores) == 2:
            points = 15 if rank == 1 else 14
        else:
            points = max(15 - (rank - 1), 1)
        points_map[player_id] = points
    
    # Actualizar puntos
    for score in all_scores:
        if score.player_id in points_map:
            score.points = points_map[score.player_id]
    
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/import_players/<int:id>', methods=['POST'])
@login_required
def import_players(id):
    team = Team.query.get_or_404(id)
    if team.user_id != current_user.id: return "No autorizado", 403
    file = request.files.get('csv_file')
    if not file or file.filename == '':
        flash('Fichero no válido')
        return redirect(url_for('view_team', id=team.id))
    try:
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.reader(stream)
        count = 0
        for row in csv_input:
            if len(row) < 2: continue
            try:
                dorsal = int(row[0].strip())
                name = row[1].strip()
                if name:
                    db.session.add(Player(name=name, dorsal=dorsal, team_id=team.id))
                    count += 1
            except: continue
        db.session.commit()
        flash(f'{count} Jugadores importados correctamente')
    except Exception as e: flash(f'Error al importar: {str(e)}')
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
            existing_user = User.query.filter_by(email=email).first()
            uid = existing_user.id if existing_user else None
            exists = TeamStaff.query.filter_by(team_id=team.id, email=email).first()
            if not exists:
                new_staff = TeamStaff(team_id=team.id, user_id=uid, email=email, status='pending')
                db.session.add(new_staff)
                db.session.commit()
                flash(f'Invitación enviada a {email}')
            else: flash('Usuario ya invitado')
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
    if not team_id: return "Error: Equipo no seleccionado", 400
    team = Team.query.get(team_id)
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return "No autorizado", 403
    new_session = TrainingSession(team_id=team_id, plan_id=plan_id, status='active')
    db.session.add(new_session)
    db.session.commit()
    for p in team.players:
        att = SessionAttendance(session_id=new_session.id, player_id=p.id, is_present=True)
        db.session.add(att)
    db.session.commit()
    return redirect(url_for('session_tracker', id=new_session.id))

@app.route('/session/<int:id>')
@login_required
def session_tracker(id):
    session = TrainingSession.query.get_or_404(id)
    team = session.team
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return redirect('/')
    plan = TrainingPlan.query.get(session.plan_id) if session.plan_id else None
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
    results = data.get('results')
    criteria = data.get('criteria')
    reverse_sort = (criteria == 'high')
    sorted_results = sorted(results, key=lambda x: float(x['raw_score']), reverse=reverse_sort)
    points_map = {}
    current_points = 15
    for res in sorted_results:
        points_map[res['player_id']] = max(1, current_points)
        current_points -= 1
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
    new_player = Player(name=name, dorsal=int(dorsal), team_id=session.team_id)
    db.session.add(new_player)
    db.session.commit()
    att = SessionAttendance(session_id=session.id, player_id=new_player.id, is_present=True)
    db.session.add(att)
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/get_session_players')
@login_required
def api_get_session_players():
    session_id = request.args.get('session_id')
    session = TrainingSession.query.get(session_id)
    if not session: return jsonify({'error': 'No session'}), 404
    
    # Verificar permisos
    team = session.team
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return jsonify({'error': 'Unauthorized'}), 403
    
    # Crear mapa de asistencia
    attendance_map = {att.player_id: att.is_present for att in session.attendance}
    
    players = []
    # Incluir todos los jugadores del equipo, no solo los presentes
    for player in team.players:
        is_present = attendance_map.get(player.id, False)
        players.append({
            'id': player.id,
            'name': player.name,
            'dorsal': player.dorsal,
            'photo': player.photo_file,
            'is_present': is_present
        })
    
    return jsonify({'players': players})

@app.route('/api/get_session_ranking')
@login_required
def api_get_session_ranking():
    session_id = request.args.get('session_id')
    top_x = int(request.args.get('top_x', 6))
    session = TrainingSession.query.get(session_id)
    if not session: return jsonify({'error': 'No session'}), 404
    
    # Verificar permisos
    team = session.team
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff: return jsonify({'error': 'Unauthorized'}), 403
    
    # Calcular puntos totales por jugador en esta sesión
    scores = db.session.query(
        SessionScore.player_id,
        func.sum(SessionScore.points).label('total_points')
    ).filter(SessionScore.session_id == session_id).group_by(SessionScore.player_id).all()
    
    ranking = []
    for pid, total in scores:
        player = Player.query.get(pid)
        if player:
            ranking.append({
                'id': player.id,
                'name': player.name,
                'dorsal': player.dorsal,
                'photo': player.photo_file,
                'total_points': int(total) if total else 0
            })
    
    ranking.sort(key=lambda x: x['total_points'], reverse=True)
    
    # Limitar a top X
    visible_ranking = ranking[:top_x]
    
    return jsonify({'ranking': visible_ranking})

@app.route('/finish_session/<int:id>')
@login_required
def finish_session(id):
    session = TrainingSession.query.get_or_404(id)
    session.status = 'finished'
    db.session.commit()
    return redirect('/my_teams')

@app.route('/team/<int:id>/public')
def public_team_ranking(id):
    team = Team.query.get_or_404(id)
    
    # Obtener parámetros de filtro de partidos
    filter_type = request.args.get('filter', 'all')
    selected_match_ids = request.args.getlist('match_ids', type=int)
    
    # Obtener todos los partidos del equipo
    all_matches = Match.query.filter_by(team_id=team.id).order_by(Match.date.desc()).all()
    
    # Determinar qué partidos incluir
    if filter_type == 'last1':
        filtered_matches = all_matches[:1]
    elif filter_type == 'last5':
        filtered_matches = all_matches[:5]
    elif filter_type == 'last10':
        filtered_matches = all_matches[:10]
    elif filter_type == 'custom' and selected_match_ids:
        filtered_matches = [m for m in all_matches if m.id in selected_match_ids]
    else:
        filtered_matches = all_matches
    
    match_ids = [m.id for m in filtered_matches]
    num_matches = len(match_ids)
    
    # Obtener acciones del equipo
    all_actions = ActionDefinition.query.filter_by(team_id=team.id).all()
    if not all_actions:
        all_actions = ActionDefinition.query.filter_by(user_id=team.user_id, team_id=None).all()
    
    shot_names = ['Tiro 1', 'Tiro 2', 'Tiro 3']
    
    # Función auxiliar para calcular ranking por tipo
    def calculate_ranking(action_filter_type):
        if action_filter_type == 'all':
            action_ids = [a.id for a in all_actions]
        elif action_filter_type == 'attack':
            action_ids = [a.id for a in all_actions if a.display_section == 'ATAQUE']
        elif action_filter_type == 'attack_no_shots':
            action_ids = [a.id for a in all_actions if a.display_section == 'ATAQUE' and a.name not in shot_names]
        elif action_filter_type == 'defense':
            action_ids = [a.id for a in all_actions if a.display_section == 'DEFENSA']
        else:
            action_ids = [a.id for a in all_actions]
        
        if not match_ids or not action_ids:
            return []
        
        # Calcular puntos
        events = MatchEvent.query.filter(
            MatchEvent.match_id.in_(match_ids),
            MatchEvent.action_id.in_(action_ids)
        ).all()
        
        player_stats = {}
        for e in events:
            if not e.player_id or not e.action_id:
                continue
            a = ActionDefinition.query.get(e.action_id)
            if not a:
                continue
            if e.player_id not in player_stats:
                player_stats[e.player_id] = 0.0
            player_stats[e.player_id] += a.value
        
        # Convertir a lista y ordenar
        ranking_data = []
        for pid, total in player_stats.items():
            player = Player.query.get(pid)
            if player:
                avg = round(total / num_matches, 2) if num_matches > 1 else total
                ranking_data.append({
                    'name': player.name,
                    'points': avg,
                    'photo': player.photo_file,
                    'dorsal': player.dorsal
                })
        
        ranking_data.sort(key=lambda x: x['points'], reverse=True)
        limit = team.analytics_players_count or 5
        return ranking_data[:limit]
    
    # Calcular rankings solo para gráficos habilitados
    charts = {}
    if team.analytics_visible:
        if team.chart_all_visible:
            charts['all'] = {'title': 'LÍDERES EN ATAQUE Y DEFENSA', 'data': calculate_ranking('all')}
        if team.chart_attack_visible:
            charts['attack'] = {'title': 'LÍDERES EN ATAQUE', 'data': calculate_ranking('attack')}
        if team.chart_attack_no_shots_visible:
            charts['attack_no_shots'] = {'title': 'LÍDERES EN ATAQUE (SIN PUNTOS)', 'data': calculate_ranking('attack_no_shots')}
        if team.chart_defense_visible:
            charts['defense'] = {'title': 'LÍDERES EN DEFENSA', 'data': calculate_ranking('defense')}
    
    # Obtener ejercicios de la galería ordenados con notas
    gallery_items = TeamGalleryItem.query.filter_by(team_id=team.id).order_by(TeamGalleryItem.display_order).all()
    drill_notes = {item.drill_id: item.note for item in gallery_items}
    drill_order = {item.drill_id: item.display_order for item in gallery_items}
    
    gallery_drills_ordered = []
    for d in (team.gallery_drills if team.gallery_drills else []):
        if not d.cover_image and d.primary_tag:
            d.cover_fallback = pick_cover_from_tag(d.primary_tag)
        else:
            d.cover_fallback = None
        d.origin = get_drill_origin(d)
        d.gallery_note = drill_notes.get(d.id, '')
        d.gallery_order = drill_order.get(d.id, 999)
        gallery_drills_ordered.append(d)
    
    gallery_drills_ordered.sort(key=lambda x: x.gallery_order)
    
    return render_template('public_ranking.html', 
                          team=team, 
                          charts=charts,
                          all_matches=all_matches,
                          filter_type=filter_type,
                          selected_match_ids=selected_match_ids,
                          num_matches=num_matches,
                          gallery_drills=gallery_drills_ordered)

@app.route('/team/<int:id>/stats')
@login_required
def team_stats(id):
    team = Team.query.get_or_404(id)
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff:
        return redirect('/')
    
    # Obtener parámetros de filtro
    filter_type = request.args.get('filter', 'last1')
    show_type = request.args.get('show', 'all')
    custom_actions = request.args.getlist('actions', type=int)
    selected_match_ids = request.args.getlist('match_ids', type=int)
    
    # Determinar qué partidos incluir
    all_matches = Match.query.filter_by(team_id=team.id).order_by(Match.date.desc()).all()
    
    if filter_type == 'last1':
        filtered_matches = all_matches[:1]
    elif filter_type == 'last5':
        filtered_matches = all_matches[:5]
    elif filter_type == 'last10':
        filtered_matches = all_matches[:10]
    elif filter_type == 'custom' and selected_match_ids:
        filtered_matches = [m for m in all_matches if m.id in selected_match_ids]
    else:
        filtered_matches = all_matches
    
    match_ids = [m.id for m in filtered_matches]
    num_matches = len(match_ids)
    
    # Obtener las acciones que se usaron en los partidos del equipo
    # Primero buscamos acciones del equipo, si no hay, del usuario
    all_actions = ActionDefinition.query.filter_by(team_id=team.id).order_by(ActionDefinition.display_section, ActionDefinition.display_order).all()
    if not all_actions:
        all_actions = ActionDefinition.query.filter_by(user_id=team.user_id, team_id=None).order_by(ActionDefinition.display_section, ActionDefinition.display_order).all()
    
    # Determinar qué acciones incluir según el filtro "show"
    # Lista de nombres de tiros a excluir para la opción "sin puntos"
    shot_names = ['Tiro 1', 'Tiro 2', 'Tiro 3']
    
    if show_type == 'all':
        action_ids = [a.id for a in all_actions]
    elif show_type == 'attack':
        action_ids = [a.id for a in all_actions if a.display_section == 'ATAQUE']
    elif show_type == 'attack_no_shots':
        # Solo acciones de ATAQUE excluyendo los tiros (1, 2, 3 puntos)
        action_ids = [a.id for a in all_actions if a.display_section == 'ATAQUE' and a.name not in shot_names]
    elif show_type == 'defense':
        action_ids = [a.id for a in all_actions if a.display_section == 'DEFENSA']
    elif show_type == 'custom' and custom_actions:
        action_ids = custom_actions
    else:
        action_ids = [a.id for a in all_actions]
    
    # Calcular estadísticas por jugador
    player_stats = {}
    for player in team.players:
        player_stats[player.id] = {
            'player': player,
            'total': 0.0,
            'matches_played': 0
        }
    
    if match_ids:
        # Primero: Obtener TODOS los jugadores que jugaron en esos partidos (sin filtro de acciones)
        all_events = MatchEvent.query.filter(MatchEvent.match_id.in_(match_ids)).all()
        players_with_events = set()
        for e in all_events:
            if e.player_id:
                players_with_events.add(e.player_id)
        
        # Marcar como "jugó" a todos los que tienen eventos
        for pid in players_with_events:
            if pid in player_stats:
                player_stats[pid]['matches_played'] = num_matches
        
        # Segundo: Calcular puntuaciones con el filtro de acciones
        if action_ids:
            events = MatchEvent.query.filter(
                MatchEvent.match_id.in_(match_ids),
                MatchEvent.action_id.in_(action_ids)
            ).all()
            
            for e in events:
                if not e.player_id or not e.action_id:
                    continue
                
                if e.player_id not in player_stats:
                    continue
                
                a = ActionDefinition.query.get(e.action_id)
                if not a:
                    continue
                
                ps = player_stats[e.player_id]
                ps['total'] += a.value
    
    # Calcular promedio si hay múltiples partidos
    for pid in player_stats:
        ps = player_stats[pid]
        if ps['matches_played'] > 0:
            ps['avg'] = round(ps['total'] / ps['matches_played'], 1)
        else:
            ps['avg'] = 0
    
    # Ordenar por valoración total y filtrar jugadores que jugaron
    ranking = sorted(player_stats.values(), key=lambda x: x['total'], reverse=True)
    ranking = [r for r in ranking if r['matches_played'] > 0]
    
    # Preparar acciones agrupadas para el modal (separando positivas y negativas)
    actions_by_section = {
        'ATAQUE +': [a for a in all_actions if a.display_section == 'ATAQUE' and a.value >= 0],
        'ATAQUE -': [a for a in all_actions if a.display_section == 'ATAQUE' and a.value < 0],
        'DEFENSA +': [a for a in all_actions if a.display_section == 'DEFENSA' and a.value >= 0],
        'DEFENSA -': [a for a in all_actions if a.display_section == 'DEFENSA' and a.value < 0]
    }
    
    return render_template('team_stats.html', 
                         team=team, 
                         ranking=ranking,
                         num_matches=num_matches,
                         filter_type=filter_type,
                         show_type=show_type,
                         all_matches=all_matches,
                         selected_match_ids=selected_match_ids,
                         custom_actions=custom_actions,
                         actions_by_section=actions_by_section)

@app.route('/delete_player/<int:id>')
@login_required
def delete_player(id):
    player = Player.query.get_or_404(id)
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

# --- CONFIGURACIÓN PARTIDO ---
# Regla: las posiciones (grid_row, grid_col) solo aplican dentro del mismo bloque (display_section, is_positive).
# Un botón de Ataque+ no puede moverse a Ataque-, Defensa+ ni Defensa-. Cualquier API de posición solo debe
# actualizar grid_row/grid_col del mismo registro, nunca display_section ni is_positive.

@app.route('/game_config', methods=['GET', 'POST'])
@login_required
def game_config():
    if request.method == 'POST':
        actions = ActionDefinition.query.filter_by(user_id=current_user.id, team_id=None).all()
        for action in actions:
            val_str = request.form.get(f'val_{action.id}')
            if val_str is not None:
                try:
                    action.value = max(-10, min(10, float(val_str)))
                except ValueError:
                    pass
            gr = request.form.get(f'grid_row_{action.id}')
            gc = request.form.get(f'grid_col_{action.id}')
            if gr is not None and gc is not None:
                try:
                    action.grid_row = max(1, min(10, int(gr)))
                    action.grid_col = max(1, min(10, int(gc)))
                except ValueError:
                    pass
            vis = request.form.get(f'visible_{action.id}')
            action.visible = (vis == 'on' or vis == '1' or vis == True)
            if action.custom_slot is not None:
                name_val = request.form.get(f'name_{action.id}')
                if name_val is not None:
                    action.name = _truncate_action_name(name_val)
                desc_val = request.form.get(f'desc_{action.id}')
                if desc_val is not None:
                    action.description = (desc_val or '')[:255]
            else:
                if current_user.is_admin and action.is_system:
                    name_val = request.form.get(f'name_{action.id}')
                    if name_val is not None:
                        action.name = _truncate_action_name(name_val)
                if current_user.is_admin:
                    desc_val = request.form.get(f'desc_{action.id}')
                    if desc_val is not None:
                        action.description = (desc_val or '')[:255]
        # Evitar posiciones duplicadas dentro del mismo bloque (display_section, is_positive)
        def _block_key(a):
            return (a.display_section or 'ATAQUE', bool(a.is_positive))
        from collections import defaultdict
        by_block = defaultdict(list)
        for a in actions:
            by_block[_block_key(a)].append(a)
        for block_key, block_actions in by_block.items():
            used = set()
            for a in sorted(block_actions, key=lambda x: (x.grid_row or 1, x.grid_col or 1, x.id)):
                r, c = a.grid_row or 1, a.grid_col or 1
                while (r, c) in used:
                    c += 1
                    if c > 10:
                        c = 1
                        r += 1
                    if r > 10:
                        r = 1
                used.add((r, c))
                a.grid_row, a.grid_col = r, c
        db.session.commit()
        flash('Configuración guardada')
        return redirect('/game_config')
    actions = get_actions_for_user(current_user.id, include_hidden=True)
    if not actions:
        copy_actions_from_admin_to_user(current_user.id)
        actions = get_actions_for_user(current_user.id, include_hidden=True)
    # Asignar grid por defecto a acciones de sistema que no lo tengan (p. ej. tras migración)
    need_save = False
    for a in actions:
        if (getattr(a, 'grid_row', None) is None or getattr(a, 'grid_row', 0) == 0) and a.is_system and a.system_key:
            for t in ACTION_DEFAULTS:
                name, val, score, is_pos, section, order, is_sys, sys_key, cslot, desc, grow, gcol = t
                if sys_key and a.system_key == sys_key:
                    a.grid_row, a.grid_col = grow, gcol
                    need_save = True
                    break
    if need_save:
        db.session.commit()
        actions = get_actions_for_user(current_user.id, include_hidden=True)
    # Migrar acciones antiguas sin display_section al conjunto estándar
    if actions and not any(getattr(a, 'display_section', None) for a in actions):
        for a in ActionDefinition.query.filter_by(user_id=current_user.id, team_id=None).all():
            db.session.delete(a)
        db.session.commit()
        copy_actions_from_admin_to_user(current_user.id)
        actions = get_actions_for_user(current_user.id, include_hidden=True)
    # Garantizar que siempre haya acciones para mostrar (p. ej. admin sin acciones aún)
    if not actions:
        create_default_actions_for_user(current_user.id)
        actions = get_actions_for_user(current_user.id, include_hidden=True)
    # Posiciones fijas por bloque (documento Excel): huecos que existen; los botones los rellenan e intercambian
    SLOTS_ATAQUE = [(1, 1), (2, 1), (2, 2), (3, 1), (3, 2), (4, 1), (4, 2)]   # 7 huecos; (1,1) doble ancho
    SLOTS_DEFENSA = [(1, 1), (1, 2), (2, 1), (2, 2), (3, 1), (3, 2)]           # 6 huecos
    expected_counts = {('ATAQUE', True): 7, ('ATAQUE', False): 7, ('DEFENSA', True): 6, ('DEFENSA', False): 6}
    # Comprobar si el usuario tiene el número correcto de acciones por bloque
    def _block_key(a):
        return (a.display_section or 'ATAQUE', bool(a.is_positive))
    from collections import defaultdict
    by_block = defaultdict(list)
    for a in actions:
        by_block[_block_key(a)].append(a)
    # Si falta algún bloque o no tiene el número correcto de acciones, recrear todo
    needs_reset = False
    for bk, expected in expected_counts.items():
        if len(by_block.get(bk, [])) != expected:
            needs_reset = True
            break
    if needs_reset:
        for a in ActionDefinition.query.filter_by(user_id=current_user.id, team_id=None).all():
            db.session.delete(a)
        db.session.commit()
        create_default_actions_for_user(current_user.id)
        actions = get_actions_for_user(current_user.id, include_hidden=True)
        by_block = defaultdict(list)
        for a in actions:
            by_block[_block_key(a)].append(a)
    # Migrar posiciones al nuevo layout (2 cols con huecos fijos)
    slots_per_block = {('ATAQUE', True): SLOTS_ATAQUE, ('ATAQUE', False): SLOTS_ATAQUE, ('DEFENSA', True): SLOTS_DEFENSA, ('DEFENSA', False): SLOTS_DEFENSA}
    migrate_pos = False
    for bk, block_actions in by_block.items():
        slots = slots_per_block.get(bk, [])
        if len(block_actions) != len(slots):
            continue
        sorted_actions = sorted(block_actions, key=lambda x: (x.grid_row or 1, x.grid_col or 1, x.id))
        for i, (r, c) in enumerate(slots):
            if sorted_actions[i].grid_row != r or sorted_actions[i].grid_col != c:
                sorted_actions[i].grid_row, sorted_actions[i].grid_col = r, c
                migrate_pos = True
    if migrate_pos:
        db.session.commit()
        actions = get_actions_for_user(current_user.id, include_hidden=True)
    rankings = RankingDefinition.query.filter_by(user_id=current_user.id).filter(RankingDefinition.team_id.is_(None)).all()
    blocks_with_slots = [
        ('Ataque +', 'ATAQUE', True, SLOTS_ATAQUE),
        ('Ataque -', 'ATAQUE', False, SLOTS_ATAQUE),
        ('Defensa +', 'DEFENSA', True, SLOTS_DEFENSA),
        ('Defensa -', 'DEFENSA', False, SLOTS_DEFENSA),
    ]
    return render_template('game_config.html', actions=actions, rankings=rankings, blocks_with_slots=blocks_with_slots)

@app.route('/game_config_add', methods=['POST'])
@login_required
def game_config_add():
    if not current_user.is_admin:
        return redirect('/game_config')
    name = request.form.get('name')
    val = float(request.form.get('value', 1))
    is_pos = (val > 0)
    new_act = ActionDefinition(name=_truncate_action_name(name or ''), value=val, is_positive=is_pos, user_id=current_user.id, team_id=None)
    db.session.add(new_act)
    db.session.commit()
    flash('Acción creada')
    return redirect('/game_config')

@app.route('/game_config_delete/<int:id>')
@login_required
def game_config_delete(id):
    act = ActionDefinition.query.get_or_404(id)
    if act.user_id != current_user.id:
        return redirect('/game_config')
    if act.is_system and not current_user.is_admin:
        return redirect('/game_config')
        db.session.delete(act)
        db.session.commit()
    return redirect('/game_config')

@app.route('/game_config_reset', methods=['POST'])
@login_required
def game_config_reset():
    """Resetea las acciones del usuario a los valores por defecto."""
    for a in ActionDefinition.query.filter_by(user_id=current_user.id, team_id=None).all():
        db.session.delete(a)
    db.session.commit()
    create_default_actions_for_user(current_user.id)
    flash('Acciones reseteadas a valores por defecto')
    return redirect('/game_config')

@app.route('/api/action/<int:id>', methods=['PATCH'])
@login_required
def api_action_update(id):
    """Actualiza nombre, valor, descripción o visible de una acción. No cambia bloque (display_section/is_positive)."""
    act = ActionDefinition.query.filter_by(id=id, user_id=current_user.id, team_id=None).first_or_404()
    data = request.get_json() or {}
    if 'value' in data:
        try:
            act.value = max(-10, min(10, float(data['value'])))
        except (TypeError, ValueError):
            pass
    if 'visible' in data:
        act.visible = bool(data['visible'])
    can_edit_name = (act.custom_slot is not None) or (current_user.is_admin and act.is_system)
    if can_edit_name and 'name' in data:
        act.name = _truncate_action_name(data.get('name') or '')
    can_edit_desc = (act.custom_slot is not None) or current_user.is_admin
    if can_edit_desc and 'description' in data:
        act.description = (str(data.get('description') or '')[:255])
    db.session.commit()
    return jsonify({'status': 'ok', 'action': {'id': act.id, 'name': act.name, 'value': act.value, 'description': act.description or '', 'visible': act.visible}})

@app.route('/api/game_config/positions', methods=['POST'])
@login_required
def api_game_config_positions():
    """Actualiza grid_row y grid_col de varias acciones. Solo acciones del usuario; no se cambia bloque."""
    data = request.get_json() or {}
    updates = data.get('updates') or []
    if not isinstance(updates, list):
        return jsonify({'status': 'error', 'message': 'updates debe ser una lista'}), 400
    ids_ok = set()
    for item in updates:
        if not isinstance(item, dict):
            continue
        aid = item.get('id')
        gr, gc = item.get('grid_row'), item.get('grid_col')
        if aid is None or gr is None or gc is None:
            continue
        try:
            aid, gr, gc = int(aid), int(gr), int(gc)
        except (TypeError, ValueError):
            continue
        gr = max(1, min(10, gr))
        gc = max(1, min(10, gc))
        act = ActionDefinition.query.filter_by(id=aid, user_id=current_user.id, team_id=None).first()
        if not act:
            continue
        act.grid_row, act.grid_col = gr, gc
        ids_ok.add(aid)
    # Normalizar duplicados por bloque
    from collections import defaultdict
    def _block_key(a):
        return (a.display_section or 'ATAQUE', bool(a.is_positive))
    all_user = ActionDefinition.query.filter_by(user_id=current_user.id, team_id=None).all()
    by_block = defaultdict(list)
    for a in all_user:
        by_block[_block_key(a)].append(a)
    for block_key, block_actions in by_block.items():
        used = set()
        for a in sorted(block_actions, key=lambda x: (x.grid_row or 1, x.grid_col or 1, x.id)):
            r, c = a.grid_row or 1, a.grid_col or 1
            while (r, c) in used:
                c += 1
                if c > 10:
                    c, r = 1, r + 1
                if r > 10:
                    r = 1
            used.add((r, c))
            a.grid_row, a.grid_col = r, c
    db.session.commit()
    return jsonify({'status': 'ok', 'updated': len(ids_ok)})

@app.route('/ranking_add', methods=['POST'])
@login_required
def ranking_add():
    name = request.form.get('name')
    action_ids = request.form.getlist('action_ids')
    new_rank = RankingDefinition(name=name, user_id=current_user.id, team_id=None)
    for aid in action_ids:
        try:
            aid = int(aid)
        except (TypeError, ValueError):
            continue
        act = ActionDefinition.query.filter_by(id=aid, user_id=current_user.id, team_id=None).first()
        if act:
            new_rank.ingredients.append(act)
    db.session.add(new_rank)
    db.session.commit()
    return redirect('/game_config')

@app.route('/ranking_delete/<int:id>')
@login_required
def ranking_delete(id):
    rank = RankingDefinition.query.get_or_404(id)
    if rank.user_id == current_user.id:
        db.session.delete(rank)
        db.session.commit()
    return redirect('/game_config')

@app.route('/new_match', methods=['GET', 'POST'])
@login_required
def new_match():
    if request.method == 'POST':
        team_id = request.form.get('team_id')
        opponent = request.form.get('opponent')
        match_date_str = request.form.get('match_date')
        player_ids = request.form.getlist('roster')
        team = Team.query.get(team_id)
        q_default = int(team.quarters) if team else 4
        q_conf = int(request.form.get('quarters', q_default))
        q_conf = max(2, min(8, q_conf))
        match_date = None
        if match_date_str:
            try:
                match_date = datetime.strptime(match_date_str, '%Y-%m-%d')
            except ValueError:
                match_date = None
        match = Match(
            opponent=opponent,
            team_id=team_id,
            user_id=current_user.id,
            quarters=q_conf,
            date=match_date or datetime.utcnow()
        )
        db.session.add(match)
        db.session.commit()
        for pid in player_ids:
            player = Player.query.get(int(pid))
            if player: match.roster.append(player)
        db.session.commit()
        return redirect(url_for('match_tracker', id=match.id))
    owned = Team.query.filter_by(user_id=current_user.id).all()
    staff_teams = [s.team for s in TeamStaff.query.filter_by(user_id=current_user.id, status='accepted').all()]
    all_teams = list(set(owned + staff_teams))
    if not all_teams: return redirect('/my_teams')
    today_date = datetime.utcnow().strftime('%Y-%m-%d')
    return render_template('new_match.html', teams=all_teams, today_date=today_date)

@app.route('/match/<int:id>')
@login_required
def match_tracker(id):
    match = Match.query.get_or_404(id)
    if match.user_id != current_user.id:
        is_staff = TeamStaff.query.filter_by(team_id=match.team_id, email=current_user.email, status='accepted').first()
        if not is_staff: return redirect('/')
    # Acciones visibles para registrar eventos
    actions = get_actions_for_team(match.team_id, match.user_id)
    # Todas las acciones (incluye ocultas) para mantener posiciones en el grid
    all_actions = get_actions_for_user(match.user_id, include_hidden=True)
    saved_lineup = []
    if match.court_lineup:
        try:
            saved_lineup = json.loads(match.court_lineup)
        except:
            saved_lineup = []
    saved_period = match.current_period if match.current_period else 1
    return render_template('tracker.html', match=match, actions=actions, all_actions=all_actions, saved_period=saved_period, saved_lineup=saved_lineup)

@app.route('/api/add_event', methods=['POST'])
@login_required
def api_add_event():
    data = request.json
    match_id = data.get('match_id')
    player_id = data.get('player_id')
    action_id = data.get('action_id')
    opponent_points = int(data.get('opponent_points', 0) or 0)
    game_minute = data.get('game_minute', 0)
    period = data.get('period', 1)
    match = Match.query.get(match_id)
    if not match: return jsonify({'error': 'No match'}), 404
    if opponent_points:
        player_id = None
        action_id = None
    event = MatchEvent(match_id=match_id, player_id=player_id, action_id=action_id, opponent_points=opponent_points, game_minute=game_minute, period=period)
    db.session.add(event)
    if opponent_points:
        match.result_them = (match.result_them or 0) + opponent_points
    db.session.commit()
    return jsonify({'status': 'ok', 'event_id': event.id, 'opponent_points': opponent_points})

@app.route('/api/undo_event', methods=['POST'])
@login_required
def api_undo_event():
    data = request.json
    event_id = data.get('event_id')
    event = MatchEvent.query.get(event_id)
    if event:
        if getattr(event, 'opponent_points', 0):
            m = Match.query.get(event.match_id)
            if m: m.result_them = max(0, (m.result_them or 0) - event.opponent_points)
        db.session.delete(event)
        db.session.commit()
        return jsonify({'status': 'ok'})
    return jsonify({'error': 'Error'}), 400

@app.route('/api/match/<int:match_id>/live_stats')
@login_required
def api_match_live_stats(match_id):
    match = Match.query.get_or_404(match_id)
    if match.user_id != current_user.id:
        st = TeamStaff.query.filter_by(team_id=match.team_id, email=current_user.email, status='accepted').first()
        if not st: return jsonify({'error': 'No autorizado'}), 403
    
    players = {}
    for p in match.roster:
        players[p.id] = {
            'name': p.name, 'dorsal': p.dorsal, 'photo': p.photo_file,
            'val': 0.0, 'ata': 0.0, 'def': 0.0, 'fouls': 0
        }
    
    score_home = 0
    score_away = 0
    
    for e in match.events:
        opp = getattr(e, 'opponent_points', 0)
        if opp:
            score_away += opp
            continue
        if not e.player_id or not e.action_id: continue
        a = ActionDefinition.query.get(e.action_id)
        if not a or e.player_id not in players: continue
        
        players[e.player_id]['val'] += a.value
        if a.display_section == 'ATAQUE': players[e.player_id]['ata'] += a.value
        elif a.display_section == 'DEFENSA': players[e.player_id]['def'] += a.value
        
        if a.name == 'Falta': players[e.player_id]['fouls'] += 1
        if a.score_value: score_home += a.score_value
    
    return jsonify({'players': players, 'score_home': score_home, 'score_away': score_away})

@app.route('/api/match/<int:match_id>/save_state', methods=['POST'])
@login_required
def api_match_save_state(match_id):
    match = Match.query.get_or_404(match_id)
    if match.user_id != current_user.id:
        st = TeamStaff.query.filter_by(team_id=match.team_id, email=current_user.email, status='accepted').first()
        if not st: return jsonify({'error': 'No autorizado'}), 403
    data = request.json
    match.current_period = data.get('period', 1)
    match.court_lineup = json.dumps(data.get('lineup', []))
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/last_events')
@login_required
def api_last_events():
    match_id = request.args.get('match_id', type=int)
    n = request.args.get('n', 3, type=int)
    match = Match.query.get_or_404(match_id) if match_id else None
    if not match: return jsonify({'error': 'No match'}), 404
    events = MatchEvent.query.filter_by(match_id=match_id).order_by(MatchEvent.timestamp.desc()).limit(n).all()
    roster = {p.id: {'name': p.name, 'dorsal': p.dorsal} for p in match.roster}
    actions_map = {a.id: {'name': a.name, 'value': a.value} for a in get_actions_for_team(match.team_id, match.user_id)}
    out = []
    for e in events:
        if getattr(e, 'opponent_points', 0):
            out.append({'id': e.id, 'kind': 'rival', 'pts': e.opponent_points, 'period': e.period})
        else:
            p = roster.get(e.player_id, {})
            a = actions_map.get(e.action_id, {})
            out.append({'id': e.id, 'kind': 'action', 'player': p, 'action': a, 'period': e.period})
    return jsonify({'events': out})

@app.route('/api/edit_event', methods=['POST'])
@login_required
def api_edit_event():
    data = request.json
    event_id = data.get('event_id')
    event = MatchEvent.query.get(event_id)
    if not event: return jsonify({'error': 'Not found'}), 404
    if data.get('delete'):
        if getattr(event, 'opponent_points', 0):
            m = Match.query.get(event.match_id)
            if m: m.result_them = max(0, (m.result_them or 0) - event.opponent_points)
        db.session.delete(event)
        db.session.commit()
        return jsonify({'status': 'ok', 'deleted': True})
    player_id = data.get('player_id')
    action_id = data.get('action_id')
    if player_id is not None: event.player_id = int(player_id)
    if action_id is not None: event.action_id = int(action_id)
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/match_stats/<int:id>')
@login_required
def match_stats(id):
    match = Match.query.get_or_404(id)
    stats = {}
    for player in match.roster:
        stats[player.id] = { 'name': player.name, 'dorsal': player.dorsal, 'photo': player.photo_file, 'total_val': 0.0, 'actions': {} }
    
    events_list = match.events
    for event in events_list:
        if getattr(event, 'opponent_points', 0): continue
        pid = event.player_id
        aid = event.action_id
        if not pid or not aid: continue
        action_def = ActionDefinition.query.get(aid)
        if pid in stats and action_def:
            current_count = stats[pid]['actions'].get(action_def.name, 0)
            stats[pid]['actions'][action_def.name] = current_count + 1
            stats[pid]['total_val'] += action_def.value
            
    actions_list = get_actions_for_team(match.team_id, match.user_id)
    action_names = [a.name for a in actions_list]
    rankings = get_rankings_for_team(match.team_id, match.user_id)
    for pid, p_data in stats.items():
        p_data['rankings'] = {}
        for r in rankings:
            score = 0
            for ing in r.ingredients:
                score += p_data['actions'].get(ing.name, 0)
            p_data['rankings'][r.name] = score

    return render_template('match_stats.html', match=match, stats=stats, action_names=action_names, rankings=rankings)

@app.route('/matches')
@login_required
def matches_list():
    matches = Match.query.filter_by(user_id=current_user.id).order_by(Match.date.desc()).all()
    match_info = []
    for m in matches:
        has_events = len(m.events) > 0
        current_p = m.current_period if m.current_period else 1
        period_label = f"Q{current_p}" if current_p <= m.quarters else "OT"
        score_home = 0
        score_away = 0
        for e in m.events:
            opp_points = getattr(e, 'opponent_points', 0)
            if opp_points:
                score_away += opp_points
                continue
            if not e.action_id:
                continue
            a = ActionDefinition.query.get(e.action_id)
            if a and a.score_value:
                score_home += a.score_value
        match_info.append({
            'match': m,
            'has_events': has_events,
            'period_label': period_label,
            'score_home': score_home,
            'score_away': score_away
        })
    return render_template('matches_list.html', match_info=match_info)

@app.route('/analytics')
@login_required
def analytics():
    teams = Team.query.filter_by(user_id=current_user.id).all()
    # Si solo tiene un equipo, redirigir directamente a sus estadísticas
    if len(teams) == 1:
        return redirect(url_for('team_stats', id=teams[0].id))
    return render_template('analytics.html', teams=teams)

@app.route('/match/delete/<int:id>', methods=['POST'])
@login_required
def delete_match(id):
    match = Match.query.get_or_404(id)
    if match.user_id != current_user.id:
        is_staff = TeamStaff.query.filter_by(team_id=match.team_id, email=current_user.email, status='accepted').first()
        if not is_staff:
            return jsonify({'error': 'No autorizado'}), 403
    
    # Eliminar eventos asociados (cascada ya configurada en el modelo)
    db.session.delete(match)
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/match_log/<int:id>')
@login_required
def match_log(id):
    match = Match.query.get_or_404(id)
    events = MatchEvent.query.filter_by(match_id=match.id).order_by(MatchEvent.timestamp.desc()).all()
    actions = get_actions_for_team(match.team_id, match.user_id)
    return render_template('match_log.html', match=match, events=events, actions=actions)

@app.route('/edit_match_event', methods=['POST'])
@login_required
def edit_match_event():
    event_id = request.form.get('event_id')
    new_player_id = request.form.get('player_id')
    new_action_id = request.form.get('action_id')
    delete_flag = request.form.get('delete')
    event = MatchEvent.query.get(event_id)
    if event:
        if delete_flag == 'yes':
            if getattr(event, 'opponent_points', 0):
                m = Match.query.get(event.match_id)
                if m: m.result_them = max(0, (m.result_them or 0) - event.opponent_points)
            db.session.delete(event)
        else:
            if new_player_id: event.player_id = int(new_player_id)
            if new_action_id: event.action_id = int(new_action_id)
        db.session.commit()
    return redirect(url_for('match_log', id=event.match_id))

@app.route('/export/match/<int:id>')
@login_required
def export_match(id):
    match = Match.query.get_or_404(id)
    team = Team.query.get_or_404(match.team_id)
    
    # Verificar permisos
    is_owner = (team.user_id == current_user.id)
    is_staff = TeamStaff.query.filter_by(team_id=team.id, email=current_user.email, status='accepted').first()
    if not is_owner and not is_staff:
        return redirect('/')
    
    # Obtener todos los eventos del partido
    events = MatchEvent.query.filter_by(match_id=match.id).order_by(MatchEvent.period, MatchEvent.timestamp).all()
    score_home = 0
    score_away = 0
    
    # Calcular estadísticas por jugador
    player_stats = {}
    for player in team.players:
        player_stats[player.id] = {
            'player': player,
            'val': 0.0,
            'ata': 0.0,
            'def': 0.0,
            'tiros_2': 0,
            'tiros_3': 0,
            'tiros_1': 0,
            'rebotes': 0,
            'asist': 0,
            'robos': 0,
            'tapones': 0,
            'tiros_2_fallados': 0,
            'tiros_3_fallados': 0,
            'tiros_1_fallados': 0,
            'balones_perdidos': 0,
            'tapones_recibidos': 0,
            'faltas': 0
        }
    
    # Procesar eventos
    for e in events:
        opp_points = getattr(e, 'opponent_points', 0)
        if opp_points:
            score_away += opp_points
            continue
        if not e.player_id or not e.action_id:
            continue
        
        if e.player_id not in player_stats:
            continue
        
        a = ActionDefinition.query.get(e.action_id)
        if not a:
            continue
        
        ps = player_stats[e.player_id]
        ps['val'] += a.value

        if a.score_value:
            score_home += a.score_value
        
        if a.display_section == 'ATAQUE':
            ps['ata'] += a.value
        elif a.display_section == 'DEFENSA':
            ps['def'] += a.value
        
        # Contadores específicos - POSITIVOS
        if a.name == 'Tiro 2' and a.value > 0:
            ps['tiros_2'] += 1
        elif a.name == 'Tiro 3' and a.value > 0:
            ps['tiros_3'] += 1
        elif a.name == 'Tiro 1' and a.value > 0:
            ps['tiros_1'] += 1
        elif 'Reb' in a.name:
            ps['rebotes'] += 1
        elif a.name == 'Asist':
            ps['asist'] += 1
        elif a.name == 'Robo':
            ps['robos'] += 1
        elif a.name == 'Tapón' and a.value > 0:
            ps['tapones'] += 1
        
        # Contadores específicos - NEGATIVOS
        if a.name == 'Tiro 2' and a.value < 0:
            ps['tiros_2_fallados'] += 1
        elif a.name == 'Tiro 3' and a.value < 0:
            ps['tiros_3_fallados'] += 1
        elif a.name == 'Tiro 1' and a.value < 0:
            ps['tiros_1_fallados'] += 1
        elif 'Bal.Per' in a.name or 'Balón Perdido' in a.name:
            ps['balones_perdidos'] += 1
        elif 'Tapón Rec' in a.name:
            ps['tapones_recibidos'] += 1
        elif a.name == 'Falta':
            ps['faltas'] += 1
    
    # Ordenar por valoración
    ranking = sorted(player_stats.values(), key=lambda x: x['val'], reverse=True)
    ranking = [r for r in ranking if r['val'] != 0 or r['tiros_2'] != 0 or r['tiros_3'] != 0]  # Solo jugadores con actividad
    
    # Preparar eventos con detalles
    events_data = []
    for idx, e in enumerate(events, 1):
        if not e.player_id or not e.action_id:
            continue
        
        player = Player.query.get(e.player_id)
        action = ActionDefinition.query.get(e.action_id)
        
        if not player or not action:
            continue
        
        period_label = f'Q{e.period}' if e.period <= 4 else 'OT' if e.period == 5 else f'OT{e.period - 4}'
        
        events_data.append({
            'orden': idx,
            'period': period_label,
            'player': player.name,
            'action': action.name,
            'value': action.value
        })
    
    return render_template('match_export.html', 
                          match=match,
                          team=team,
                          ranking=ranking, 
                          events=events_data,
                          score_home=score_home,
                          score_away=score_away)

@app.route('/court_mode/<int:id>')
@login_required
def court_mode(id):
    plan = TrainingPlan.query.get_or_404(id)
    owned = Team.query.filter_by(user_id=current_user.id).all()
    staff_teams = [s.team for s in TeamStaff.query.filter_by(user_id=current_user.id, status='accepted').all()]
    my_teams = list(set(owned + staff_teams))
    
    # Buscar sesión activa para cualquier equipo del usuario
    active_session = TrainingSession.query.filter(
        TrainingSession.status == 'active',
        TrainingSession.team_id.in_([t.id for t in my_teams])
    ).first()
    
    return render_template('court_mode.html', plan=plan, teams=my_teams, active_session=active_session)

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
    # Solo crear datos iniciales si no hay etiquetas (primera ejecución)
    if Tag.query.first():
        return  # Ya hay etiquetas, no recrear
    groups_data = [
        ("💪 FÍSICO", [
            "Activación/Calentamiento",
            "Coordinación/Agilidad",
            "Fuerza/Potencia/Salto",
            "Velocidad/Resistencia",
            "Estiramientos/vuelta a la calma"
        ]),
        ("🏀 TÉCNICA INDIVIDUAL", [
            "Tiro",
            "Bote",
            "Pase",
            "Finalizaciones",
            "Juego de pies"
        ]),
        ("🛡️ DEFENSA", [
            "Defensa al jugador (1x1)",
            "Rebote/Box out",
            "Líneas de Pase",
            "Ayudas y Rotaciones",
            "Defensa del Bloqueo Directo (PDR)",
            "Defensa del Bloqueo Indirecto",
            "Defensa presionante & Trap",
            "Balance Defensivo"
        ]),
        ("🧠 ATAQUE", [
            "Rebote ataque",
            "Spacing (Ocupación de espacios)",
            "Juego sin balón (Cortes, puertas atrás)",
            "Toma de Decisiones (Lectura)",
            "Bloqueo Directo (Pick & Roll)",
            "Bloqueo Indirecto",
            "Mano a mano (Handoff)",
            "Contraataque y Transición",
            "Sistemas ataque (5c5)",
            "BLOB (Saque de Fondo)",
            "SLOB (Saque de Banda)",
            "Salida de Presión"
        ]),
        ("🔢 SITUACIÓN DE JUEGO", [
            "1x0 (Técnica sin oposición)",
            "1x1",
            "2x2",
            "3x3",
            "4x4",
            "5x5 (Juego real)",
            "Superioridad/Inferioridad"
        ]),
        ("🏅 CATEGORÍA / NIVEL", [
            "Minibasket fundamentos",
            "Minibasket juegos",
            "Formación",
            "Profesional"
        ])
    ]
    for idx, (g_name, tag_list) in enumerate(groups_data, 1):
        group = TagGroup.query.filter_by(name=g_name).first()
        if not group:
            group = TagGroup(name=g_name, display_order=idx)
            db.session.add(group)
            db.session.flush()
        for tag_name in tag_list:
            existing = Tag.query.filter_by(name=tag_name).first()
            if not existing:
                db.session.add(Tag(name=tag_name, group_id=group.id, is_custom=False))
            else:
                if not existing.group_id:
                    existing.group_id = group.id
                    existing.is_custom = False
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
        if not db.session.get(SiteConfig, k): db.session.add(SiteConfig(key=k, value=v))
    db.session.commit()

if __name__ == '__main__':
    with app.app_context():
        run_migrations()
        db.create_all()
        crear_datos_prueba()
    # Puerto 5001: en macOS el 5000 suele estar ocupado por AirPlay
    app.run(debug=True, port=5001)