from flask import Flask, request, redirect, url_for, render_template_string
import json
from datetime import date, datetime
from dateutil.relativedelta import relativedelta

app = Flask(__name__)

ARCHIVO = "contratos.json"

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

def aplicar_aumento(contrato):
    monto_anterior = contrato["monto"]

    if contrato["indice"] == "IPC":
        factor = 1.10
    else:
        factor = 1.12

    monto_nuevo = round(monto_anterior * factor, 2)

    contrato["monto"] = monto_nuevo
    contrato["ultimo_pago"] = str(date.today())

    contrato["historial"].append({
        "fecha": str(date.today()),
        "indice": contrato["indice"],
        "monto_anterior": monto_anterior,
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

@app.route("/aumentar/<int:id>")
def aumentar(id):
    contratos = cargar_contratos()

    if id < 0 or id >= len(contratos):
        return "Contrato no encontrado", 404

    aplicar_aumento(contratos[id])
    guardar_contratos(contratos)

    return redirect(url_for("index"))

# =====================
# HOME
# =====================

@app.route("/")
def index():
    contratos = cargar_contratos()

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <title>Gestión de Alquileres</title>
</head>
<body style="font-family:Arial; background:#f5f5f5; padding:20px;">

<h1>📄 Gestión de Alquileres</h1>
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

    <form action="/aumentar/{{ loop.index0 }}" method="get" style="display:inline;">
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
            "inquilino": request.form["inquilino"],
            "monto": float(request.form["monto"]),
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
    contratos = cargar_contratos()

    if id < 0 or id >= len(contratos):
        return "Contrato no encontrado", 404

    contrato = contratos[id]

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