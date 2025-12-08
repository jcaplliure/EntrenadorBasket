import os
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import or_, and_
from datetime import datetime

# --- CONFIGURACIÓN ---
app = Flask(__name__)

# Configuración Rutas
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'basket.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'mi_clave_secreta_super_dificil'
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024 

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- FILTRO YOUTUBE ---
@app.template_filter('get_youtube_id')
def get_youtube_id(url):
    if not url: return None
    if 'youtu.be' in url:
        return url.split('/')[-1]
    if 'youtube.com' in url and 'v=' in url:
        return url.split('v=')[1].split('&')[0]
    return None

# --- MODELOS ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

drill_primary_tags = db.Table('drill_primary_tags',
    db.Column('drill_id', db.Integer, db.ForeignKey('drill.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)
drill_secondary_tags = db.Table('drill_secondary_tags',
    db.Column('drill_id', db.Integer, db.ForeignKey('drill.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)

class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    def __repr__(self): return f'<Tag {self.name}>'

class Drill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)
    media_file = db.Column(db.String(120), nullable=True)
    external_link = db.Column(db.String(500), nullable=True)
    primary_tags = db.relationship('Tag', secondary=drill_primary_tags, backref='primary_drills')
    secondary_tags = db.relationship('Tag', secondary=drill_secondary_tags, backref='secondary_drills')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- RUTAS ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            return "<h1>Error: Usuario existe</h1><a href='/register'>Volver</a>"
        es_admin = (username.lower() == 'admin')
        nuevo_user = User(username=username, is_admin=es_admin)
        nuevo_user.set_password(password)
        db.session.add(nuevo_user)
        db.session.commit()
        login_user(nuevo_user)
        return redirect('/')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect('/')
        else:
            return "<h1>Pass incorrecta</h1><a href='/login'>Reintentar</a>"
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')

@app.route('/')
@login_required
def home():
    search_query = request.args.get('q', '').strip()
    primary_filter = request.args.get('primary', '')
    secondary_filter = request.args.get('secondary', '')
    search_logic = request.args.get('logic', 'and')

    condiciones = []
    if search_query:
        condiciones.append(or_(Drill.title.ilike(f'%{search_query}%'), Drill.description.ilike(f'%{search_query}%')))
    if primary_filter and primary_filter.isdigit():
        condiciones.append(Drill.primary_tags.any(id=int(primary_filter)))
    if secondary_filter and secondary_filter.isdigit():
        condiciones.append(Drill.secondary_tags.any(id=int(secondary_filter)))

    if len(condiciones) > 0:
        if search_logic == 'or':
            ejercicios = Drill.query.filter(or_(*condiciones)).order_by(Drill.date_posted.desc()).all()
        else:
            ejercicios = Drill.query.filter(and_(*condiciones)).order_by(Drill.date_posted.desc()).all()
    else:
        ejercicios = Drill.query.order_by(Drill.date_posted.desc()).all()

    todas_tags = Tag.query.order_by(Tag.name).all()
    return render_template('index.html', lista_ejercicios=ejercicios, tags=todas_tags)

@app.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    todas_tags = Tag.query.order_by(Tag.name).all()

    if request.method == 'POST':
        titulo = request.form['titulo']
        desc = request.form['descripcion']
        nuevo_ejercicio = Drill(title=titulo, description=desc)
        
        # Link externo
        link_ext = request.form.get('external_link', '').strip()
        if link_ext: nuevo_ejercicio.external_link = link_ext

        # Archivo (Solo Admin)
        if current_user.is_admin and 'archivo' in request.files:
            file = request.files['archivo']
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                nuevo_ejercicio.media_file = filename

        # Etiquetas
        ids_principales = request.form.getlist('primary_tags')
        ids_secundarias = request.form.getlist('secondary_tags')
        
        for tag_id in ids_principales:
            tag = Tag.query.get(int(tag_id))
            if tag: nuevo_ejercicio.primary_tags.append(tag)
        for tag_id in ids_secundarias:
            if tag_id not in ids_principales:
                tag = Tag.query.get(int(tag_id))
                if tag: nuevo_ejercicio.secondary_tags.append(tag)

        db.session.add(nuevo_ejercicio)
        db.session.commit()
        return redirect('/')

    return render_template('create.html', etiquetas=todas_tags)

# --- NUEVA RUTA: EDITAR EJERCICIO ---
@app.route('/edit_drill/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_drill(id):
    ejercicio = Drill.query.get(id)
    if not ejercicio: return redirect('/')
    
    todas_tags = Tag.query.order_by(Tag.name).all()

    if request.method == 'POST':
        # 1. Actualizar textos
        ejercicio.title = request.form['titulo']
        ejercicio.description = request.form['descripcion']
        ejercicio.external_link = request.form.get('external_link', '').strip()

        # 2. Archivo (Solo Admin - Si sube uno nuevo, reemplaza)
        if current_user.is_admin and 'archivo' in request.files:
            file = request.files['archivo']
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                ejercicio.media_file = filename

        # 3. Actualizar Etiquetas (Borramos las viejas y ponemos las nuevas)
        ejercicio.primary_tags.clear()
        ejercicio.secondary_tags.clear()

        ids_principales = request.form.getlist('primary_tags')
        ids_secundarias = request.form.getlist('secondary_tags')

        for tag_id in ids_principales:
            tag = Tag.query.get(int(tag_id))
            if tag: ejercicio.primary_tags.append(tag)
            
        for tag_id in ids_secundarias:
            if tag_id not in ids_principales:
                tag = Tag.query.get(int(tag_id))
                if tag: ejercicio.secondary_tags.append(tag)

        db.session.commit()
        return redirect('/')

    return render_template('edit_drill.html', drill=ejercicio, etiquetas=todas_tags)

@app.route('/delete_drill/<int:id>')
@login_required
def delete_drill(id):
    ejercicio = Drill.query.get(id)
    if ejercicio:
        db.session.delete(ejercicio)
        db.session.commit()
    return redirect('/')

@app.route('/tags')
@login_required
def manage_tags():
    if not current_user.is_admin: return redirect('/')
    todas = Tag.query.order_by(Tag.name).all()
    return render_template('manage_tags.html', tags=todas)

@app.route('/add_tag', methods=['POST'])
@login_required
def add_tag():
    if not current_user.is_admin: return redirect('/')
    nombre = request.form['name'].strip().capitalize()
    if nombre and not Tag.query.filter_by(name=nombre).first():
        db.session.add(Tag(name=nombre))
        db.session.commit()
    return redirect('/tags')

@app.route('/update_tag', methods=['POST'])
@login_required
def update_tag():
    if not current_user.is_admin: return redirect('/')
    tag = Tag.query.get(request.form['id'])
    if tag:
        tag.name = request.form['name']
        db.session.commit()
    return redirect('/tags')

@app.route('/delete_tag/<int:id>')
@login_required
def delete_tag(id):
    if not current_user.is_admin: return redirect('/')
    tag = Tag.query.get(id)
    if tag:
        db.session.delete(tag)
        db.session.commit()
    return redirect('/tags')

def crear_datos_prueba():
    if Tag.query.count() == 0:
        lista = ["Tiro", "Entrada", "Pase", "Bote", "Defensa", "Rebote", "Físico", "Táctica", "Mental"]
        lista.sort()
        for nombre in lista: db.session.add(Tag(name=nombre))
        db.session.commit()

if __name__ == '__main__':
    with app.app_context():
        if not os.path.exists(app.config['UPLOAD_FOLDER']):
            os.makedirs(app.config['UPLOAD_FOLDER'])
        db.create_all()
        crear_datos_prueba()
    app.run(debug=True)