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
from PIL import Image, ImageDraw

app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'basket.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'clave_secreta_super_segura'
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB Límite

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

# --- MODELOS ---
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

class SiteConfig(db.Model):
    key = db.Column(db.String(50), primary_key=True) 
    value = db.Column(db.String(255), nullable=False) 

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
    last_blocks_config = db.Column(db.String(500), nullable=True, default="Calentamiento,Técnica Individual,Tiro,Táctica,Físico,Vuelta a la Calma")
    favoritos = db.relationship('Drill', secondary=favorites, backref=db.backref('favorited_by', lazy='dynamic'))
    def set_password(self, password): self.password_hash = generate_password_hash(password)
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
    drill = db.relationship('Drill')

@login_manager.user_loader
def load_user(user_id): return User.query.get(int(user_id))

# --- CONTEXT PROCESSOR ---
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

# --- HELPERS ---
def compress_image(file):
    img = Image.open(file)
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    output = BytesIO()
    img.save(output, format='JPEG', quality=75, optimize=True)
    output.seek(0)
    return output

@app.template_filter('youtube_thumb')
def youtube_thumb(url):
    if not url: return None
    vid_id = None
    if 'youtu.be' in url: vid_id = url.split('/')[-1]
    elif 'v=' in url: vid_id = url.split('v=')[1].split('&')[0]
    if vid_id: return f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg"
    return None

@app.template_filter('get_youtube_id')
def get_youtube_id(url):
    if not url: return None
    if 'youtu.be' in url: return url.split('/')[-1]
    if 'youtube.com' in url and 'v=' in url: return url.split('v=')[1].split('&')[0]
    return None

# --- RUTAS PRINCIPALES ---
@app.route('/')
def home():
    query = request.args.get('q', '').strip()
    primary_ids = request.args.getlist('primary')
    filter_type = request.args.getlist('filter_type')
    sort_by = request.args.get('sort_by', 'favs_desc') 
    
    if current_user.is_authenticated: base_condition = or_(Drill.is_public == True, Drill.user_id == current_user.id)
    else: base_condition = (Drill.is_public == True)

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
        if conditions: drills_query = drills_query.filter(or_(*conditions))

    if query: drills_query = drills_query.filter(or_(Drill.title.ilike(f'%{query}%'), Drill.description.ilike(f'%{query}%')))
    if primary_ids: drills_query = drills_query.filter(Drill.primary_tags.any(Tag.id.in_(primary_ids)))

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
        content_type = request.form.get('content_type') 
        external_link = request.form.get('external_link', '').strip()
        
        nuevo = Drill(title=title, description=desc, is_public=is_public, user_id=current_user.id, media_type=content_type)

        if content_type == 'link':
            nuevo.external_link = external_link
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
                        nuevo.media_file = filename
                    else:
                        flash('Formato no válido')
                        return redirect(request.url)
                elif content_type == 'pdf':
                    if filename.lower().endswith('.pdf'):
                        file.seek(0, os.SEEK_END)
                        if file.tell() > 5 * 1024 * 1024:
                            flash('PDF muy grande (Máx 5MB)')
                            return redirect(request.url)
                        file.seek(0)
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
                with open(os.path.join(app.config['UPLOAD_FOLDER'], c_filename), 'wb') as f:
                    f.write(c_comp.getbuffer())
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
        response = requests.head(url, headers=headers, timeout=5, allow_redirects=True)
        if response.status_code < 400: return {'status': 'ok'}
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code < 400: return {'status': 'ok'}
        return {'status': 'error'}
    except: return {'status': 'error'}

@app.route('/delete/<int:id>')
@login_required
def delete_drill(id):
    drill = Drill.query.get(id)
    if drill and (drill.user_id == current_user.id or current_user.is_admin):
        db.session.delete(drill)
        db.session.commit()
    return redirect(request.referrer or '/')

# --- RUTAS DE PLANES ---
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
            name=name, team_name=team, date=plan_date, notes=notes,
            structure=blocks_csv, user_id=current_user.id, is_public=False
        )
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
    return render_template('view_plan.html', plan=plan, all_drills=all_drills, tags=tags)

@app.route('/add_item_to_plan', methods=['POST'])
@login_required
def add_item_to_plan():
    plan_id = request.form.get('plan_id')
    drill_id = request.form.get('drill_id')
    block_name = request.form.get('block_name')
    plan = TrainingPlan.query.get(plan_id)
    if not plan or plan.user_id != current_user.id: return "Error", 403
    item = TrainingItem(training_plan_id=plan.id, drill_id=drill_id, block_name=block_name)
    db.session.add(item)
    db.session.commit()
    return redirect(url_for('view_plan', id=plan.id))

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

@app.route('/drill/<int:id>')
def view_drill(id):
    drill = Drill.query.get_or_404(id)
    if not drill.is_public:
        if not current_user.is_authenticated or drill.user_id != current_user.id: return redirect('/')
    user_ip = request.remote_addr
    existing_view = DrillView.query.filter_by(drill_id=id, ip_address=user_ip).first()
    if not existing_view:
        drill.views += 1
        db.session.add(DrillView(drill_id=id, ip_address=user_ip))
        db.session.commit()
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

# --- AUTH & ADMIN ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect('/')
    if request.method == 'POST':
        email = request.form['email']
        if User.query.filter_by(email=email).first():
            flash('Email ya existe')
            return redirect('/register')
        new_user = User(email=email, name=request.form['name'])
        new_user.set_password(request.form['password'])
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
        user = User.query.filter_by(email=request.form['email']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
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
    login_user(user)
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
        if key and file and file.filename != '':
            filename = f"config_{key}_{int(datetime.now().timestamp())}.png"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            conf = SiteConfig.query.get(key)
            if not conf:
                conf = SiteConfig(key=key, value=filename)
                db.session.add(conf)
            else:
                conf.value = filename
            db.session.commit()
            flash(f'Configuración {key} actualizada.')
    
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

# --- GENERADOR AUTO DE ICONOS BANANA ---
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
        if not SiteConfig.query.get(k): 
            db.session.add(SiteConfig(key=k, value=v))
            
    db.session.commit()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        crear_datos_prueba()
    app.run(debug=True)