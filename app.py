from flask import Flask, request, redirect, url_for, render_template_string
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
import requests
import os
import psycopg2
from flask import session
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from urllib.parse import urlparse

DATABASE_URL = os.environ.get("DATABASE_URL") or "postgresql://control_de_alquileres_user:dKyL44SZqFEWl8oWHVS9Xl5yI234aHhP@dpg-d6ggtchaae7s73bc5au0-a.oregon-postgres.render.com/control_de_alquileres"

def get_db_connection():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL no configurada")
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

if DATABASE_URL:
    crear_tabla_usuarios()


   

def crear_tabla_indices():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS indices (
            id SERIAL PRIMARY KEY,
            tipo TEXT,
            fecha DATE,
            valor FLOAT
        );
    """)

    conn.commit()
    cur.close()
    conn.close()

if DATABASE_URL:
    crear_tabla_indices()

# ==============================
# CONEXIÓN A BASE DE DATOS
# ==============================

def get_db_connection():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL no configurada")

    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require"
    )


# ==============================
# CREACIÓN DE TABLAS
# ==============================

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


def crear_tabla_indices():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS indices (
            id SERIAL PRIMARY KEY,
            tipo TEXT,
            fecha DATE,
            valor FLOAT
        );
    """)

    conn.commit()
    cur.close()
    conn.close()


def crear_tabla_contratos():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS contratos (
            id SERIAL PRIMARY KEY,
            usuario TEXT,
            inquilino TEXT,
            monto FLOAT,
            monto_original FLOAT,
            indice TEXT,
            inicio DATE,
            periodo INTEGER,
            ultimo_aumento DATE,
            modo_aumento TEXT
        );
    """)

    conn.commit()
    cur.close()
    conn.close()

def crear_tabla_historial():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS historial_aumentos (
            id SERIAL PRIMARY KEY,
            contrato_id INTEGER,
            fecha DATE,
            indice TEXT,
            monto_anterior FLOAT,
            monto_nuevo FLOAT
        );
    """)

    conn.commit()
    cur.close()
    conn.close()


# ==============================
# EJECUTAR CREACIÓN DE TABLAS
# ==============================

if DATABASE_URL:
    crear_tabla_usuarios()
    crear_tabla_indices()
    crear_tabla_contratos()
    crear_tabla_historial()

    
def obtener_indice(tipo, fecha):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT valor
        FROM indices
        WHERE tipo = %s AND fecha <= %s
        ORDER BY fecha DESC
        LIMIT 1
    """, (tipo, fecha))

    resultado = cur.fetchone()

    cur.close()
    conn.close()

    if resultado:
        return float(resultado[0])

    return None


def crear_tabla_indices():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS indices (
            id SERIAL PRIMARY KEY,
            tipo TEXT,
            fecha DATE,
            valor FLOAT
        );
    """)

    conn.commit()
    cur.close()
    conn.close()



app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "clave-dev")



# =====================
# DATOS
# =====================


def aplicar_aumento(contrato):

    tipo = contrato["indice"]
    hoy = date.today()

    ultimo_pago = datetime.strptime(
        contrato["ultimo_pago"],
        "%Y-%m-%d"
    ).date()

    periodo = int(contrato["periodo"])

    # Verificamos si corresponde aumento
    proximo_aumento = ultimo_pago + relativedelta(months=periodo)

    if hoy < proximo_aumento:
        print("⚠️ Todavía no corresponde aumento")
        return

    indice_anterior = obtener_indice(tipo, ultimo_pago)
    indice_actual = obtener_indice(tipo, hoy)

    if not indice_anterior or not indice_actual:
        print("⚠️ No se encontraron índices")
        return

    if contrato.get("modo_aumento") == "original":
        monto_base = contrato["monto_original"]
    else:
        monto_base = contrato["monto"]

    factor = indice_actual / indice_anterior
    monto_nuevo = round(monto_base * factor, 2)

    contrato["historial"].append({
        "fecha": str(hoy),
        "indice": tipo,
        "monto_anterior": monto_base,
        "monto_nuevo": monto_nuevo
    })

    contrato["monto"] = monto_nuevo
    contrato["ultimo_pago"] = str(hoy)



# =====================
# LOGICA DE FECHAS
# =====================

def sumar_meses(fecha, meses):
    return fecha + relativedelta(months=meses)

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

    usuario_actual = session["usuario"]
    hoy = date.today()

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT monto, monto_original, indice,
               periodo, ultimo_aumento, modo_aumento
        FROM contratos
        WHERE id = %s AND usuario = %s
    """, (id, usuario_actual))

    row = cur.fetchone()

    if not row:
        cur.close()
        conn.close()
        return "Contrato no encontrado", 404

    monto_actual = float(row[0])
    monto_original = float(row[1])
    tipo_indice = row[2]
    periodo = int(row[3])
    ultimo_aumento = row[4]
    modo_aumento = row[5]

    proximo_aumento = ultimo_aumento + relativedelta(months=periodo)

    if hoy < proximo_aumento:
        cur.close()
        conn.close()
        return redirect(url_for("index"))

    # =========================
    # 🔹 OBTENER ÍNDICES CORRECTAMENTE
    # =========================

    if tipo_indice == "IPC":
        fecha_base = ultimo_aumento.replace(day=1)
        fecha_actual = hoy.replace(day=1)

        indice_anterior = obtener_indice("IPC", fecha_base)
        indice_actual = obtener_indice("IPC", fecha_actual)
    else:
        indice_anterior = obtener_indice(tipo_indice, ultimo_aumento)
        indice_actual = obtener_indice(tipo_indice, hoy)

    if not indice_anterior or not indice_actual:
        cur.close()
        conn.close()
        return redirect(url_for("index"))

    # =========================
    # 🔹 CALCULAR AUMENTO
    # =========================

    base = monto_original if modo_aumento == "original" else monto_actual

    factor = indice_actual / indice_anterior
    porcentaje = round((factor - 1) * 100, 2)

    monto_nuevo = round(base * factor, 2)

    # =========================
    # 🔹 GUARDAR HISTORIAL
    # =========================

    cur.execute("""
    INSERT INTO historial_aumentos (
        contrato_id,
        fecha,
        indice,
        monto_anterior,
        monto_nuevo,
        porcentaje
    )
    VALUES (%s, %s, %s, %s, %s, %s)
""", (id, hoy, tipo_indice, monto_actual, monto_nuevo, porcentaje))

    # =========================
    # 🔹 ACTUALIZAR CONTRATO
    # =========================

    cur.execute("""
        UPDATE contratos
        SET monto = %s,
            ultimo_aumento = %s
        WHERE id = %s AND usuario = %s
    """, (monto_nuevo, hoy, id, usuario_actual))

    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for("index"))

    return "Función deshabilitada (JSON eliminado)", 500

    


# =====================
# ELIMINAR (POST correcto)
# =====================

@app.route("/eliminar/<int:id>", methods=["POST"])
def eliminar(id):
    if "usuario" not in session:
        return redirect(url_for("login"))

    usuario_actual = session["usuario"]

    conn = get_db_connection()
    cur = conn.cursor()

    # Seguridad: eliminar solo si pertenece al usuario
    cur.execute("""
        DELETE FROM contratos
        WHERE id = %s AND usuario = %s
    """, (id, usuario_actual))

    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for("index"))

    return "Función deshabilitada (JSON eliminado)", 500  
@app.route("/indices", methods=["GET", "POST"])
def gestionar_indices():
    if "usuario" not in session:
        return redirect(url_for("login"))
    
    if session.get("rol") != "admin":
        return "Acceso no autorizado", 403

    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == "POST":
        tipo = request.form["tipo"]
        fecha = request.form["fecha"]
        valor = float(request.form["valor"])

        cur.execute("""
            INSERT INTO indices (tipo, fecha, valor)
            VALUES (%s, %s, %s)
        """, (tipo, fecha, valor))

        conn.commit()

    # Traer lista de índices
    cur.execute("""
        SELECT id, tipo, fecha, valor
        FROM indices
        ORDER BY fecha DESC
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return render_template_string("""
    <h2>Gestión de Índices</h2>

<form action="/actualizar_indices" method="post" style="margin-bottom:15px;">
    <button style="padding:8px;background:#28a745;color:white;border:none;border-radius:4px;">
        🔄 Actualizar índices oficiales
    </button>
</form>

<form method="post">
    Tipo:<br>
    <select name="tipo">
        <option>IPC</option>
        <option>ICL</option>
    </select><br><br>

        Fecha:<br>
        <input type="date" name="fecha" required><br><br>

        Valor:<br>
        <input type="number" step="0.01" name="valor" required><br><br>

        <button>Guardar índice</button>
    </form>

    <hr>

    <h3>Historial de índices</h3>

    <table border="1" cellpadding="5">
        <tr>
            <th>Tipo</th>
            <th>Fecha</th>
            <th>Valor</th>
        </tr>

        {% for r in rows %}
        <tr>
            <td>{{ r[1] }}</td>
            <td>{{ r[2] }}</td>
            <td>{{ r[3] }}</td>
        </tr>
        {% endfor %}
    </table>

    <br>
    <a href="/">⬅ Volver</a>
    """, rows=rows)

def guardar_indice(tipo, fecha, valor):
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO indices (tipo, fecha, valor)
            VALUES (%s, %s, %s)
            ON CONFLICT (tipo, fecha) DO NOTHING
        """, (tipo, fecha, valor))

        conn.commit()
    finally:
        cur.close()
        conn.close()

    

   

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
            "SELECT password, rol FROM usuarios WHERE usuario = %s",
            (usuario_form,)
        )

        user = cur.fetchone()

        cur.close()
        conn.close()

        if user and check_password_hash(user[0], password_form):
            session["usuario"] = usuario_form
            session["rol"] = user[1]   # 👈 guardamos el rol
            return redirect(url_for("index"))

        else:
            return "Usuario o contraseña incorrectos"

    # Si es GET, mostramos el formulario
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

@app.route("/actualizar_indices", methods=["POST"])
def actualizar_indices():
    if "usuario" not in session:
        return redirect(url_for("login"))

    if session.get("rol") != "admin":
        return "Acceso no autorizado", 403

    try:
        hoy = date.today().replace(day=1)

          # ===== IPC REAL (INDEC espejo) =====
        response_ipc = requests.get(
            "https://api.argentinadatos.com/v1/finanzas/indices/ipc"
        )

        if response_ipc.status_code == 200:
            data_ipc = response_ipc.json()

            if data_ipc:
                ultimo_ipc = data_ipc[-1]

                fecha_ipc = ultimo_ipc["fecha"][:10]
                valor_ipc = float(ultimo_ipc["valor"])

                guardar_indice("IPC", fecha_ipc, valor_ipc)
        else:
            print("Error consultando IPC:", response_ipc.status_code)

        # ===== ICL REAL (BCRA) =====
        token = os.environ.get("BCRA_TOKEN")

        headers = {
            "Authorization": f"Bearer {token}"
        }

        response = requests.get(
            "https://api.estadisticasbcra.com/icl",
            headers=headers
        )

        if response.status_code == 200:
            data = response.json()

            if data:
                ultimo = data[-1]
                fecha_icl = ultimo["d"]
                valor_icl = float(ultimo["v"])

                guardar_indice("ICL", fecha_icl, valor_icl)
        else:
            print("Error consultando ICL BCRA:", response.status_code)

        return redirect(url_for("gestionar_indices"))

    except Exception as e:
        return f"Error actualizando índices: {str(e)}"

@app.route("/logout")
def logout():
    session.pop("usuario", None)
    return redirect(url_for("login"))


@app.route("/")
def index():
    if "usuario" not in session:
        return redirect(url_for("login"))

    usuario_actual = session["usuario"]

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, inquilino, monto, monto_original,
               indice, inicio, periodo,
               ultimo_aumento, modo_aumento
        FROM contratos
        WHERE usuario = %s
        ORDER BY inicio DESC
    """, (usuario_actual,))

    rows = cur.fetchall()

    contratos = []

    for row in rows:
        contrato_id = row[0]

        # 🔹 Traer historial
        cur.execute("""
    SELECT fecha, indice, monto_anterior, monto_nuevo, porcentaje
    FROM historial_aumentos
    WHERE contrato_id = %s
    ORDER BY fecha DESC
""", (contrato_id,))

        historial_rows = cur.fetchall()

        historial = []
        for h in historial_rows:
            historial.append({
    "fecha": str(h[0]),
    "indice": h[1],
    "monto_anterior": float(h[2]),
    "monto_nuevo": float(h[3]),
    "porcentaje": float(h[4]) if h[4] else 0
})

        contratos.append({
            "id": contrato_id,
            "inquilino": row[1],
            "monto": row[2],
            "monto_original": row[3],
            "indice": row[4],
            "inicio": str(row[5]),
            "periodo": row[6],
            "ultimo_pago": str(row[7]) if row[7] else str(row[5]),
            "modo_aumento": row[8],
            "historial": historial
        })

    cur.close()
    conn.close()

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
 {% if session["rol"] == "admin" %}
<a href="/indices">
    <button style="padding:6px; margin-left:10px;">
        📊 Gestionar Índices
    </button>
</a>
{% endif %}

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

   <form action="/aumentar/{{ c["id"] }}" method="post" style="display:inline;">
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

    <a href="/editar/{{ c["id"] }}">
        <button style="padding:6px;margin-left:10px;">
            ✏️ Editar
        </button>
    </a>
      <form action="/eliminar/{{ c["id"]}}" method="post" style="display:inline;">
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
                  +{{ h["porcentaje"] }}% —
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
    if "usuario" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":

        usuario_actual = session["usuario"]

        inquilino = request.form["inquilino"]
        monto = float(request.form["monto"])
        indice = request.form["indice"]
        modo_aumento = request.form["modo_aumento"]
        inicio = request.form["inicio"]
        periodo = int(request.form["periodo"])

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO contratos (
                usuario,
                inquilino,
                monto,
                monto_original,
                indice,
                inicio,
                periodo,
                ultimo_aumento,
                modo_aumento
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            usuario_actual,
            inquilino,
            monto,
            monto,          # monto_original = monto inicial
            indice,
            inicio,
            periodo,
            inicio,         # ultimo_aumento arranca en inicio
            modo_aumento
        ))

        conn.commit()
        cur.close()
        conn.close()

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

    usuario_actual = session["usuario"]

    conn = get_db_connection()
    cur = conn.cursor()

    # Primero traemos el contrato
    cur.execute("""
        SELECT id, inquilino, monto, monto_original,
               indice, inicio, periodo,
               ultimo_aumento, modo_aumento
        FROM contratos
        WHERE id = %s AND usuario = %s
    """, (id, usuario_actual))

    row = cur.fetchone()

    if not row:
        cur.close()
        conn.close()
        return "Contrato no encontrado", 404

    if request.method == "POST":

        inquilino = request.form["inquilino"]
        monto = float(request.form["monto"])
        indice = request.form["indice"]
        periodo = int(request.form["periodo"])

        cur.execute("""
            UPDATE contratos
            SET inquilino = %s,
                monto = %s,
                indice = %s,
                periodo = %s
            WHERE id = %s AND usuario = %s
        """, (inquilino, monto, indice, periodo, id, usuario_actual))

        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for("index"))

    contrato = {
        "id": row[0],
        "inquilino": row[1],
        "monto": row[2],
        "indice": row[4],
        "periodo": row[6]
    }

    cur.close()
    conn.close()

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
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)