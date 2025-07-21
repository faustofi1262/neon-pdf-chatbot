from flask import Flask, render_template, request, redirect, url_for, session, flash, session, flash
from db import get_connection
import bcrypt
import os
from werkzeug.utils import secure_filename
from datetime import datetime
import shutil
from db import get_connection
from werkzeug.security import generate_password_hash
from flask import Flask, request, jsonify, render_template
import openai
from pinecone import Pinecone


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# Inicializar claves
openai.api_key = os.getenv("OPENAI_API_KEY")
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))

index = pc.Index("neon-chatbot")

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

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
    # Generar el embedding de la pregunta
    try:
        embedding_pregunta = openai.Embedding.create(
            input=pregunta,
            model="text-embedding-ada-002"
        )["data"][0]["embedding"]
    except Exception as e:
        return f"Error generando embedding: {str(e)}"

    # Buscar contexto en Pinecone
    try:
        resultados = index.query(
            vector=embedding_pregunta,
            top_k=5,
            include_metadata=True,
            namespace="pdf_files"
        )
    except Exception as e:
        return f"Error consultando Pinecone: {str(e)}"

    # Construir contexto
    contexto = ""
    for match in resultados.get("matches", []):
        if match["score"] > 0.75 and "texto" in match["metadata"]:
            contexto += match["metadata"]["texto"] + "\n"

    # Si hay contexto suficiente, usarlo
    if contexto.strip():
        prompt = f"""
        Responde la siguiente pregunta basada SOLO en el siguiente contenido extraído de documentos oficiales de la UTMACH.

        CONTEXTO:
        {contexto}

        PREGUNTA:
        {pregunta}

        RESPUESTA:
        """
    else:
        # Si no hay contexto, permitir consulta libre a OpenAI
        prompt = f"""
        No encontré información precisa en los documentos cargados.
        Por favor responde la siguiente pregunta con la mejor información general disponible para orientar a un estudiante nuevo en la UTMACH.

        PREGUNTA:
        {pregunta}

        RESPUESTA:
        """
    # Generar respuesta
    try:
        respuesta = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Error generando respuesta con OpenAI: {str(e)}"

    return respuesta.strip()
@app.route("/chatbot")
def vista_chatbot():
    return render_template("chatbot.html")

@app.route("/chatbot_api", methods=["POST"])
def chatbot_api():
    pregunta = request.json.get("pregunta", "")
    respuesta = responder_con_chatbot(pregunta)  # Esta función buscará en Pinecone y luego en OpenAI
    return jsonify({"respuesta": respuesta})



