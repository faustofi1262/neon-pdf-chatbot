from flask import Flask, render_template, request, redirect, url_for, session, flash
from db import get_connection
import bcrypt
import os

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "clave-secreta-por-defecto")

@app.route("/")
def index():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        correo = request.form["correo"]
        contrasena = request.form["contrasena"].encode('utf-8')

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, contrasena_hash, nombre_usuario, rol FROM usuarios WHERE correo = %s", (correo,))
        usuario = cur.fetchone()
        cur.close()
        conn.close()

        if usuario and bcrypt.checkpw(contrasena, usuario[1].encode('utf-8')):
            session["usuario_id"] = usuario[0]
            session["nombre_usuario"] = usuario[2]
            session["rol"] = usuario[3]
            return redirect(url_for("panel"))
        else:
            flash("Correo o contraseña incorrectos")
            return redirect(url_for("login"))

    return render_template("login.html")

@app.route("/panel")
def panel():
    if "usuario_id" not in session:
        return redirect(url_for("login"))
    return render_template("panel.html", nombre=session["nombre_usuario"])

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))
