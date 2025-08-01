from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from db import get_connection
import bcrypt
import os
from werkzeug.utils import secure_filename
from datetime import datetime
import shutil
from werkzeug.security import generate_password_hash
from pinecone import Pinecone
from openai import OpenAI
from flask_cors import CORS

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
CORS(app)  # Habilita CORS para aceptar peticiones desde otras páginas web


# Inicializar claves
OpenAI.api_key = os.getenv("OPENAI_API_KEY")
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))

index = pc.Index("neon-chatbot")

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
from pinecone import Pinecone
from openai import OpenAI

# Inicializar Pinecone y OpenAI
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
pinecone_index = pc.Index("neon-chatbot")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
@app.route("/")
def index():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        nombre_usuario = request.form["nombre_usuario"]
        contrasena = request.form["contrasena"].encode('utf-8')

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, contrasena_hash, nombre_usuario, rol FROM usuarios WHERE nombre_usuario = %s", (nombre_usuario,))
        usuario = cur.fetchone()
        cur.close()
        conn.close()

        if usuario and bcrypt.checkpw(contrasena, usuario[1].encode('utf-8')):
            session["usuario_id"] = usuario[0]
            session["nombre_usuario"] = usuario[2]
            session["rol"] = usuario[3]
            return redirect(url_for("panel"))
        else:
            flash("Usuario o contraseña incorrectos")
            return redirect(url_for("login"))

    return render_template("login.html")
@app.route('/panel')
def panel():
    conn = get_connection()
    cur = conn.cursor()

    # ✅ Trae todos los PDF subidos, ordenados por fecha
    cur.execute("SELECT id, nombre_archivo, fecha_subida, entrenado FROM archivos_pdf ORDER BY fecha_subida DESC")
    lista_pdfs = cur.fetchall()

    # ✅ Si no hay un PDF guardado en sesión, usa el primero de la lista que sí exista físicamente
    ultimo_pdf = session.get('ultimo_pdf')
    if not ultimo_pdf:
        for pdf in lista_pdfs:
            posible = pdf[1]
            ruta = os.path.join('static/uploads', posible)
            if os.path.exists(ruta):
                ultimo_pdf = posible
                session['ultimo_pdf'] = posible
                break
    else:
        ruta = os.path.join('static/uploads', ultimo_pdf)
        if not os.path.exists(ruta):
            ultimo_pdf = None
            session.pop('ultimo_pdf', None)

    cur.close()
    conn.close()

    return render_template('panel.html', lista_pdfs=lista_pdfs, ultimo_pdf=ultimo_pdf)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))
@app.route("/subir_pdf", methods=["POST"])
def subir_pdf():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    archivo = request.files.get("archivo_pdf")

    if archivo and allowed_file(archivo.filename):
        filename = secure_filename(archivo.filename)
        ruta_guardado = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        # Crear la carpeta si no existe
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        os.makedirs("static/uploads", exist_ok=True)

        # Guardar el archivo
        archivo.save(ruta_guardado)

        # Copiar también a static/uploads para visualizarlo
        shutil.copy(ruta_guardado, os.path.join("static/uploads", filename))

        # Guardar en base de datos
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO archivos_pdf (nombre_archivo, ruta_archivo, usuario_id, fecha_subida, entrenado)
            VALUES (%s, %s, %s, %s, %s)
        """, (filename, ruta_guardado, session["usuario_id"], datetime.now(), False))
        conn.commit()
        cur.close()
        conn.close()

        flash("✅ PDF subido y registrado correctamente.")
    else:
        flash("❌ El archivo debe ser un PDF válido.")

    return redirect(url_for("panel"))
@app.route('/ver_pdf/<nombre_archivo>')
def ver_pdf(nombre_archivo):
    # Guarda en sesión el PDF seleccionado para que el visor lo muestre
    session['ultimo_pdf'] = nombre_archivo

    # Verifica que el archivo exista físicamente
    ruta_archivo = os.path.join('static/uploads', nombre_archivo)
    if os.path.exists(ruta_archivo):
        session['ultimo_pdf'] = nombre_archivo
    else:
        flash("El archivo solicitado no existe.")
    return redirect(url_for('panel'))

@app.route('/eliminar_pdf', methods=['GET'])
def eliminar_pdf():
    nombre_archivo = request.args.get('nombre_archivo')

    if not nombre_archivo:
        flash("Nombre de archivo no proporcionado.")
        return redirect(url_for('panel'))

    ruta = os.path.join('static', 'uploads', nombre_archivo)

    try:
        # Eliminar archivo físico
        if os.path.exists(ruta):
            os.remove(ruta)

        # Eliminar de la base de datos
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM archivos_pdf WHERE nombre_archivo = %s", (nombre_archivo,))
        conn.commit()
        cur.close()
        conn.close()

        # 🔄 Limpiar visor si es el archivo eliminado
        if session.get('ultimo_pdf') == nombre_archivo:
            session.pop('ultimo_pdf')

        flash(f"✅ Archivo '{nombre_archivo}' eliminado correctamente.")
    except Exception as e:
        flash(f"⚠️ Error al eliminar el archivo: {e}")

    return redirect(url_for('panel'))
@app.route('/usuarios')
def usuarios():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, nombre_usuario, contrasena_hash, correo, rol FROM usuarios ORDER BY id DESC")
    lista_usuarios = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('usuarios.html', lista_usuarios=lista_usuarios)

@app.route('/crear_usuario', methods=['POST'])
def crear_usuario():
    nombre_usuario = request.form.get('nombre_usuario')
    correo = request.form.get('correo')
    contrasena = request.form.get('contrasena_hash')
    rol = request.form.get('rol')

    if not nombre_usuario or not correo or not contrasena or not rol:
        return "Faltan datos en el formulario"

    try:
        hash_contrasena = generate_password_hash(contrasena)

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO usuarios (nombre_usuario, correo, contrasena_hash, rol)
            VALUES (%s, %s, %s, %s)
        """, (nombre_usuario, correo, hash_contrasena, rol))

        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('usuarios'))

    except Exception as e:
        print("Error:", e)
        return "Error interno al crear el usuario"
@app.route('/editar_usuario', methods=['POST'])
def editar_usuario():
    id_usuario = request.form['id_usuario']
    nombre_usuario = request.form['nombre_usuario']
    correo = request.form['correo']
    rol = request.form['rol']

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM usuarios WHERE id = %s", (id_usuario,))
    usuario_editar = cur.fetchone()

    cur.execute("SELECT * FROM usuarios ORDER BY id DESC")
    lista_usuarios = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('usuarios.html',
                           usuario_editar=usuario_editar,
                           lista_usuarios=lista_usuarios,
                           modo_edicion=True)
@app.route('/eliminar_usuario/<int:id>')
def eliminar_usuario(id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM usuarios WHERE id = %s", (id,))
    conn.commit()
    cur.close()
    conn.close()

    flash("Usuario eliminado correctamente.")
    return redirect(url_for('usuarios'))
# Mostrar usuarios (con edición si se pasa id)
# Actualizar usuario
@app.route('/actualizar_usuario', methods=['POST'])
def actualizar_usuario():
    id_usuario = request.form['id']
    nombre = request.form['nombre_usuario']
    correo = request.form['correo']
    rol = request.form['rol']

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET nombre_usuario=%s, correo=%s, rol=%s WHERE id=%s",
                (nombre, correo, rol, id_usuario))
    conn.commit()
    cur.close()
    conn.close()

    flash('Usuario actualizado correctamente.')
    return redirect(url_for('usuarios'))

def responder_con_chatbot(pregunta):
    try:
        # Generar embedding de la pregunta
        response = client.embeddings.create(
            input=pregunta,
            model="text-embedding-ada-002"
        )
        embedding_pregunta = response.data[0].embedding
    except Exception as e:
        return f"Bot: Error generando embedding: {str(e)}"

    # Buscar contexto en Pinecone
    try:
        resultados = pinecone_index.query(
            vector=embedding_pregunta,
            top_k=5,
            include_metadata=True,
            namespace="pdf_files"
        )
    except Exception as e:
        return f"Bot: Error buscando en Pinecone: {str(e)}"

    # Armar el contexto desde los vectores
    contexto = ""
    for match in resultados.get("matches", []):
        if match["score"] > 0.75 and "texto" in match["metadata"]:
            contexto += match["metadata"]["texto"] + "\n"

    # Construir prompt con o sin contexto
    if contexto.strip():
        prompt = f"""
        Responde SOLO en base a la siguiente información institucional:

        {contexto}

        Pregunta del usuario:
        {pregunta}

        Respuesta:
        """
    else:
        prompt = f"""
        No encontré información precisa en los documentos institucionales cargados.
        Por favor, responde esta pregunta de la mejor forma posible para orientar al estudiante:

        {pregunta}
        """

    # Generar respuesta con OpenAI
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        respuesta = response.choices[0].message.content.strip()
        return respuesta
    except Exception as e:
        return f"Bot: Error generando respuesta con OpenAI: {str(e)}"

@app.route("/chatbot_api", methods=["POST"])
def chatbot_api():
    pregunta = request.json.get("pregunta", "")
    respuesta = responder_con_chatbot(pregunta)  # Esta función buscará en Pinecone y luego en OpenAI
    return jsonify({"respuesta": respuesta})
#@app.route("/chatbot")
#def vista_chatbot():
    #return render_template("chatbot.html")

def responder_con_chatbot(pregunta):
    try:
        response = client.embeddings.create(
            input=pregunta,
            model="text-embedding-ada-002"
        )
        embedding_pregunta = response.data[0].embedding
    except Exception as e:
        return f"Bot: Error generando embedding: {str(e)}"

    try:
        resultados = pinecone_index.query(
            vector=embedding_pregunta,
            top_k=5,
            include_metadata=True,
            namespace="pdf_files"
        )
    except Exception as e:
        return f"Bot: Error buscando en Pinecone: {str(e)}"

    contexto = ""
    for match in resultados.get("matches", []):
        if match["score"] > 0.75 and "texto" in match["metadata"]:
            contexto += match["metadata"]["texto"] + "\n"

    if contexto.strip():
        prompt = f"""
        Responde SOLO en base a la siguiente información institucional:

        {contexto}

        Pregunta del usuario:
        {pregunta}

        Respuesta:
        """
    else:
        prompt = f"""
        No encontré información precisa en los documentos institucionales cargados.
        Por favor, responde esta pregunta de la mejor forma posible para orientar al estudiante:

        {pregunta}
        """

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        respuesta = response.choices[0].message.content.strip()
        return respuesta
    except Exception as e:
        return f"Bot: Error generando respuesta con OpenAI: {str(e)}"

