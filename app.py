from flask import Flask, request, redirect, url_for, render_template_string
import json
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
import requests
import os
import psycopg2
from flask import session
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from urllib.parse import urlparse

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)
def crear_tabla_usuarios():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            usuario TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

crear_tabla_usuarios()

BCRA_TOKEN = os.environ.get("BCRA_TOKEN")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "clave-dev")

ARCHIVO = "contratos.json"
ARCHIVO_USUARIOS = "usuarios.json"
# Crear archivos si no existen (importante para Render)
if not os.path.exists(ARCHIVO_USUARIOS):
    with open(ARCHIVO_USUARIOS, "w", encoding="utf-8") as f:
        json.dump([], f)

if not os.path.exists(ARCHIVO):
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump([], f)
def cargar_usuarios():
    try:
        with open(ARCHIVO_USUARIOS, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

# =====================
# DATOS
# =====================

def cargar_contratos():
    try:
        with open(ARCHIVO, "r", encoding="utf-8") as f:
            contratos = json.load(f)

            hoy = str(date.today())

            for c in contratos:
                if "inicio" not in c:
                    c["inicio"] = hoy
                if "ultimo_pago" not in c:
                    c["ultimo_pago"] = c["inicio"]
                if "periodo" not in c:
                    c["periodo"] = 6
                if "indice" not in c:
                    c["indice"] = "IPC"
                if "monto" not in c:
                    c["monto"] = 0.0
                if "monto_original" not in c:
                        c["monto_original"] = c["monto"]
                if "modo_aumento" not in c:
                    c["modo_aumento"] = "acumulativo"
                if "historial" not in c:
                    c["historial"] = []

            return contratos

    except (FileNotFoundError, json.JSONDecodeError):
        return []

def guardar_contratos(contratos):
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump(contratos, f, indent=4, ensure_ascii=False)

# =====================
# LOGICA DE FECHAS
# =====================

def sumar_meses(fecha, meses):
    return fecha + relativedelta(months=meses)


def obtener_indice_bcra(codigo):
    headers = {
        "Authorization": f"Bearer {BCRA_TOKEN}"
    }

    if codigo == "ipc":
        endpoint = "ipc"
    else:
        endpoint = "indice_contratos_locacion"

    url = f"https://api.estadisticasbcra.com/{endpoint}"

    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        print("Error BCRA:", response.status_code)
        print("URL usada:", url)
        return None


def obtener_valor_en_fecha(serie, fecha):
    if isinstance(fecha, str):
        fecha = datetime.strptime(fecha, "%Y-%m-%d").date()

    valores_validos = []

    for item in serie:
        fecha_item = datetime.strptime(item["d"], "%Y-%m-%d").date()

        if fecha_item <= fecha:
            valores_validos.append(item)

    if not valores_validos:
        return None

    return valores_validos[-1]["v"]


def aplicar_aumento(contrato):

    if contrato.get("modo_aumento") == "original":
        monto_base = contrato.get("monto_original", contrato["monto"])
    else:
        monto_base = contrato["monto"]

    if contrato["indice"] == "IPC":
        codigo = "ipc"
    else:
        codigo = "icl"

    serie = obtener_indice_bcra(codigo)

    if not serie:
        return

    fecha_inicio = contrato["inicio"]

    indice_inicio = obtener_valor_en_fecha(serie, fecha_inicio)
    indice_actual = obtener_valor_en_fecha(serie, date.today())

    if indice_inicio is None or indice_actual is None:
        print("No se pudo obtener valores del índice")
        return

    factor = indice_actual / indice_inicio
    monto_nuevo = round(monto_base * factor, 2)

    contrato["monto"] = monto_nuevo
    contrato["ultimo_pago"] = str(date.today())

    contrato["historial"].append({
        "fecha": str(date.today()),
        "indice": contrato["indice"],
        "monto_anterior": monto_base,
        "monto_nuevo": monto_nuevo
    })




def estado_pago(contrato):
    hoy = date.today()

    try:
        ultimo = datetime.strptime(
            contrato.get("ultimo_pago"),
            "%Y-%m-%d"
        ).date()
    except Exception:
        return "verde"

    periodo = int(contrato.get("periodo", 6))
    vencimiento = sumar_meses(ultimo, periodo)

    dias_restantes = (vencimiento - hoy).days

    if dias_restantes < 0:
        return "rojo"
    elif dias_restantes <= 60:
        return "amarillo"
    else:
        return "verde"

# =====================
# AUMENTAR
# =====================

@app.route("/aumentar/<int:id>", methods=["POST"])
def aumentar(id):
    if "usuario" not in session:
        return redirect(url_for("login"))

    contratos = cargar_contratos()
    contratos_usuario = [c for c in contratos if c.get("usuario") == session["usuario"]]

    if id < 0 or id >= len(contratos_usuario):
        return "Contrato no encontrado", 404

    contrato = contratos_usuario[id]
    aplicar_aumento(contrato)

    guardar_contratos(contratos)

    return redirect(url_for("index"))


# =====================
# ELIMINAR (POST correcto)
# =====================

@app.route("/eliminar/<int:id>", methods=["POST"])
def eliminar(id):
    if "usuario" not in session:
        return redirect(url_for("login"))

    contratos = cargar_contratos()
    contratos_usuario = [c for c in contratos if c.get("usuario") == session["usuario"]]

    if id < 0 or id >= len(contratos_usuario):
        return "Contrato no encontrado", 404

    contrato_a_borrar = contratos_usuario[id]
    contratos.remove(contrato_a_borrar)

    guardar_contratos(contratos)

    return redirect(url_for("index"))

# =====================
# HOME
# =====================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario_form = request.form["usuario"]
        password_form = request.form["password"]

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            "SELECT password FROM usuarios WHERE usuario = %s",
            (usuario_form,)
        )

        user = cur.fetchone()

        cur.close()
        conn.close()

        if user and check_password_hash(user[0], password_form):
            session["usuario"] = usuario_form
            return redirect(url_for("index"))

        return "Usuario o contraseña incorrectos"

    return render_template_string("""
        <h2>Login</h2>
        <form method="post">
            Usuario:<br>
            <input name="usuario"><br><br>
            Contraseña:<br>
            <input type="password" name="password"><br><br>
            <button>Ingresar</button>
        </form>
        <br>
        <a href="/registro">Crear cuenta</a>
    """)
@app.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "POST":
        usuario_nuevo = request.form["usuario"].strip()
        password_nuevo = request.form["password"]

        if len(usuario_nuevo) < 4:
            return "El usuario debe tener al menos 4 caracteres"

        if len(password_nuevo) < 6:
            return "La contraseña debe tener al menos 6 caracteres"

        password_hash = generate_password_hash(password_nuevo)

        try:
            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute(
                "INSERT INTO usuarios (usuario, password) VALUES (%s, %s)",
                (usuario_nuevo, password_hash)
            )

            conn.commit()
            cur.close()
            conn.close()

        except psycopg2.errors.UniqueViolation:
            return "El usuario ya existe"

        return redirect(url_for("login"))

    return render_template_string("""
        <h2>Registro</h2>
        <form method="post">
            Usuario:<br>
            <input name="usuario" required><br><br>
            Contraseña:<br>
            <input type="password" name="password" required><br><br>
            <button>Crear cuenta</button>
        </form>
        <br>
        <a href="/login">Ya tengo cuenta</a>
    """)
@app.route("/logout")
def logout():
    session.pop("usuario", None)
    return redirect(url_for("login"))


@app.route("/")
def index():
    if "usuario" not in session:
        return redirect(url_for("login"))

    contratos = cargar_contratos()
    contratos = [c for c in contratos if c.get("usuario") == session["usuario"]]

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <title>Gestión de Alquileres</title>
</head>
<body style="font-family:Arial; background:#f5f5f5; padding:20px;">

<h1>📄 Gestión de Alquileres</h1>
  <p>Usuario: {{ session["usuario"] }}</p>
<a href="/logout">Cerrar sesión</a>                                
<p>Listado de contratos activos</p>

<a href="/nuevo">
    <button style="padding:10px; font-size:16px;">
        ➕ Nuevo alquiler
    </button>
</a>

<hr><br>

{% for c in contratos %}
{% set estado = estado_pago(c) %}

<div style="
    background:white;
    border-radius:8px;
    padding:15px;
    margin-bottom:15px;
    box-shadow:0 2px 5px rgba(0,0,0,0.1);
">

    <h3>👤 {{ c["inquilino"] }}</h3>

    <p>
        💰 <b>Monto:</b> ${{ c["monto"] }} <br>
        📊 <b>Índice:</b> {{ c["indice"] }} <br>
        📅 <b>Inicio:</b> {{ c["inicio"] }}
    </p>

   <form action="/aumentar/{{ loop.index0 }}" method="post" style="display:inline;">
        <button type="submit"
            onclick="return confirm('¿Aplicar aumento?')"
            style="background:#007bff;color:white;padding:8px;border:none;border-radius:4px;">
            🔼 Aplicar aumento
        </button>
    </form>

    <br><br>

    {% if estado == "rojo" %}
        <button style="background:red;color:white;padding:6px;border:none;">
            ⛔ Pago vencido
        </button>
    {% elif estado == "amarillo" %}
        <button style="background:gold;padding:6px;border:none;">
            ⚠️ Próximo a vencer
        </button>
    {% else %}
        <button style="background:green;color:white;padding:6px;border:none;">
            ✅ Al día
        </button>
    {% endif %}

    <a href="/editar/{{ loop.index0 }}">
        <button style="padding:6px;margin-left:10px;">
            ✏️ Editar
        </button>
    </a>
      <form action="/eliminar/{{ loop.index0 }}" method="post" style="display:inline;">
    <button 
        type="submit"
        onclick="return confirm('¿Seguro que querés eliminar este contrato?')"
        style="padding:6px;margin-left:10px;background:red;color:white;border:none;border-radius:4px;">
        ❌
    </button>
</form>                       

    {% if c["historial"] %}
        <details style="margin-top:10px;">
            <summary>📜 Ver historial de aumentos</summary>
            <ul>
                {% for h in c["historial"] %}
                <li>
                    {{ h["fecha"] }} — {{ h["indice"] }} —
                    ${{ h["monto_anterior"] }} → ${{ h["monto_nuevo"] }}
                </li>
                {% endfor %}
            </ul>
        </details>
    {% endif %}

</div>

{% else %}
<p>No hay alquileres cargados</p>
{% endfor %}

</body>
</html>
""", contratos=contratos, estado_pago=estado_pago)

# =====================
# NUEVO ALQUILER
# =====================

@app.route("/nuevo", methods=["GET", "POST"])
def nuevo():
    if request.method == "POST":
        contratos = cargar_contratos()

        contratos.append({
    "usuario": session["usuario"],
    "inquilino": request.form["inquilino"],
    "monto": float(request.form["monto"]),
    "monto_original": float(request.form["monto"]),  # 👈 NUEVO
    "modo_aumento": request.form["modo_aumento"],    # 👈 NUEVO
    "indice": request.form["indice"],
    "inicio": request.form["inicio"],
    "periodo": int(request.form["periodo"]),
    "ultimo_pago": request.form["inicio"],
    "historial": []
})

        guardar_contratos(contratos)
        return redirect(url_for("index"))

    return render_template_string("""
    <h2>Nuevo alquiler</h2>

    <form method="post">
        Inquilino:<br>
        <input name="inquilino" required><br><br>

        Monto:<br>
        <input name="monto" type="number" step="0.01" required><br><br>

        Índice:<br>
        <select name="indice">
            <option>IPC</option>
            <option>ICL</option>
        </select><br><br>
           Modo de aumento:<br>
<select name="modo_aumento">
    <option value="acumulativo">Acumulativo</option>
    <option value="original">Desde monto original</option>
</select><br><br>                       

        Inicio contrato:<br>
        <input type="date" name="inicio" required><br><br>

        Periodo de ajuste:<br>
        <select name="periodo">
            <option value="3">Trimestral</option>
            <option value="4">Cuatrimestral</option>
            <option value="6">Semestral</option>
        </select><br><br>

        <button>Guardar</button>
    </form>

    <br>
    <a href="/">⬅ Volver</a>
    """)

# =====================
# EDITAR ALQUILER
# =====================

@app.route("/editar/<int:id>", methods=["GET", "POST"])
def editar(id):
    if "usuario" not in session:
        return redirect(url_for("login"))

    contratos = cargar_contratos()
    contratos_usuario = [c for c in contratos if c.get("usuario") == session["usuario"]]

    if id < 0 or id >= len(contratos_usuario):
        return "Contrato no encontrado", 404

    contrato = contratos_usuario[id]

    if request.method == "POST":
        contrato["inquilino"] = request.form["inquilino"]
        contrato["monto"] = float(request.form["monto"])
        contrato["indice"] = request.form["indice"]
        contrato["periodo"] = int(request.form["periodo"])

        guardar_contratos(contratos)
        return redirect(url_for("index"))

    return render_template_string("""
    <h2>Editar alquiler</h2>

    <form method="post">
        Inquilino:<br>
        <input name="inquilino" value="{{ c['inquilino'] }}"><br><br>

        Monto:<br>
        <input name="monto" type="number" step="0.01" value="{{ c['monto'] }}"><br><br>

        Índice:<br>
        <select name="indice">
            <option {% if c['indice']=='IPC' %}selected{% endif %}>IPC</option>
            <option {% if c['indice']=='ICL' %}selected{% endif %}>ICL</option>
        </select><br><br>

        Periodo:<br>
        <select name="periodo">
            <option value="3" {% if c['periodo']==3 %}selected{% endif %}>Trimestral</option>
            <option value="4" {% if c['periodo']==4 %}selected{% endif %}>Cuatrimestral</option>
            <option value="6" {% if c['periodo']==6 %}selected{% endif %}>Semestral</option>
        </select><br><br>

        <button>Guardar cambios</button>
    </form>

    <br>
    <a href="/">⬅ Volver</a>
    """, c=contrato)
    

# =====================
# START
# =====================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)