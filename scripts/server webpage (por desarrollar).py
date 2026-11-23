from flask import Flask, jsonify
from flask_cors import CORS
import datetime
import requests

app = Flask(__name__)
CORS(app)  # Permite que el navegador consulte la API sin bloqueos CORS

# --- Lógica de Mercado Público en Python ---
TICKET_MERCADO_PUBLICO = "0F5BF2E7-773F-47B0-BA93-42DA3EF534EF"
PALABRAS_CLAVE = ["capacitacion", "financiero", "finanzas", "emprendimiento",
                    "educacion financiera", "preparacion laboral", "empleabilidad"]

def obtener_mercado_publico():
    hoy = datetime.datetime.now().strftime("%d%m%Y")
    url = f"https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"
    params = {"fecha": hoy, "ticket": TICKET_MERCADO_PUBLICO}

    try:
        res = requests.get(url, params=params, timeout=15)
        licitaciones_raw = res.json().get("Listado", [])
    except Exception as e:
        print(f"Error: {e}")
        licitaciones_raw = []

    resultados = []
    for lic in licitaciones_raw:
        nombre = lic.get("Nombre", "")
        codigo = lic.get("CodigoExterno", "S/I")
        if any(kw in nombre.lower() for kw in PALABRAS_CLAVE):
            resultados.append({
                "id": f"mercado-publico-{codigo}".lower(),
                "titulo": nombre,
                "fuente": f"{lic.get('Organismo', 'Mercado Público')} / Mercado Público",
                "categoria": "Talleres y Emprendimiento",
                "estado": "nuevo",
                "fechaDetectada": datetime.datetime.now().strftime("%Y-%m-%d"),
                "fechaCierre": lic.get("FechaCierre", ""),
                "url": f"https://buscador.mercadopublico.cl/ficha?code={codigo}",
                "descripcion": f"Licitación pública: {nombre}",
                "origen": "Mercado Público API"
            })
    return resultados

# --- Rutas Endpoints de la API ---
@app.route('/api/fondos_gob')
def get_fondos_gob():
    # Aquí puedes llamar a tus funciones de fondos_gob.py
    return jsonify([])

@app.route('/api/corfo')
def get_corfo():
    # Aquí puedes llamar a tus funciones de corfo.py
    return jsonify([])

@app.route('/api/mercado_publico')
def get_mercado_publico():
    datos = obtener_mercado_publico()
    return jsonify(datos)

if __name__ == '__main__':
    app.run(port=5000, debug=True)