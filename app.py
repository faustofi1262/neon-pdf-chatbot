from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def index():
    return "✅ Chatbot Flask en Render funcionando correctamente"

@app.route("/login")
def login():
    return render_template("login.html")
