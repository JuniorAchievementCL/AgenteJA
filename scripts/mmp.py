import os
import time
import json
import sqlite3
import datetime
import requests
import smtplib
import unicodedata
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google import genai
from google.genai import types

# ==========================================
# 1. CONFIGURACIÓN Y CREDENCIALES
# ==========================================
DB_PATH = "data/historial_licitaciones.db"

TICKET_MERCADO_PUBLICO = os.environ.get("TICKET_MERCADO_PUBLICO", "")  
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "") 
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")  
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")  
EMAIL_RECIPIENTS = os.environ.get("EMAIL_RECIPIENTS", "")

print(f"[DEBUG] Destinatarios cargados: '{EMAIL_RECIPIENTS}'")

# 1A. Términos amplios para abrir el cuello de botella (basados en perfil JA Chile)
KEYWORDS_AMPLIAS = [
    # Emprendimiento e innovación
    "emprendimiento", "emprendedor", "innovacion", "negocio", "canvas", "design thinking", "pitch", "feria",
    # Educación financiera
    "financiera", "finanzas", "ahorro", "bancarizacion", "credito", "economica",
    # Empleabilidad y orientación
    "empleabilidad", "laboral", "vocacional", "primer empleo", "orientacion", "carrera", "curriculum",
    # Juventud, educación y liderazgo
    "joven", "juventud", "injuv", "liceo", "escolar", "estudiante", "educacion", "educativo", "liderazgo", "mentoria",
    # Sostenibilidad y medioambiente (Programas AEMA / Emprendedores Climáticos)
    "ambiental", "climatico", "sustentable", "sostenibilidad", "economia circular", "reciclaje", "residuos",
    # Género y participación
    "mujer", "mujeres", "genero", "stem",
    # Formatos habituales de ejecución
    "taller", "talleres", "capacitacion", "formacion", "jornada", "campamento", "competencia", "simulacion"
]

# 1B. Keywords de alto valor para otorgar bono de puntuación adicional a la evaluación de la IA
KEYWORDS_ALTO_VALOR = [
    "educacion financiera", "emprendimiento juvenil", "emprendimiento escolar",
    "empleabilidad juvenil", "preparacion laboral", "orientacion vocacional",
    "injuv", "liceo", "estudiantes de ensenanza media", "economia circular",
    "emprendimiento mujeres", "mujeres emprendedoras", "liderazgo juvenil",
    "desarrollo de negocios", "innovacion escolar", "mentoria"
]

# 1C. Filtro negativo para descartar ruido evidente antes de llamar a la API de detalle
KEYWORDS_EXCLUSION = [
    "adquisicion de", "compra de", "suministro de", "arriendo de", "construccion",
    "reparacion", "mantencion", "aseo", "vigilancia", "seguridad privada",
    "insumos medicos", "medicamentos", "combustible", "alimentacion", "colaciones",
    "mobiliario", "vehiculo", "ferreteria", "licencias de software"
]

# Organismo compradores afines donde conviene revisar si piden servicios/programas
COMPRADORES_CLAVE = [
    "educacion", "juventud", "injuv", "fomento", "liceo", "slep",
    "servicio local", "municipalidad", "gobierno regional", "sercotec", "corfo", "fosis"
]

client = genai.Client(api_key=GEMINI_API_KEY)

# ==========================================
# 2. BASE DE DATOS SQLITE (ANTI-DUPLICADOS)
# ==========================================
def _conectar():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)

def inicializar_db():
    with _conectar() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS licitaciones_procesadas (
                codigo_externo TEXT PRIMARY KEY,
                titulo TEXT NOT NULL,
                organismo TEXT,
                fecha_detectada TEXT,
                fecha_cierre TEXT,
                url TEXT,
                notificada INTEGER DEFAULT 0
            )
        """)

def es_primera_ejecucion() -> bool:
    """Verifica si la base de datos está vacía para lanzar el barrido de 30 días."""
    with _conectar() as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM licitaciones_procesadas")
        return cursor.fetchone()[0] == 0

def ya_existe_licitacion(codigo_externo: str) -> bool:
    with _conectar() as conn:
        cursor = conn.execute(
            "SELECT 1 FROM licitaciones_procesadas WHERE codigo_externo = ?",
            (codigo_externo,)
        )
        return cursor.fetchone() is not None

def registrar_licitacion(lic: dict) -> bool:
    codigo = lic.get("CodigoExterno", "S/I")
    with _conectar() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO licitaciones_procesadas 
            (codigo_externo, titulo, organismo, fecha_detectada, fecha_cierre, url, notificada)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (
                codigo,
                lic.get("Nombre", "Sin título"),
                lic.get("Organismo", "Mercado Público"),
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                lic.get("FechaCierre", ""),
                f"https://www.mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?qs={codigo}",
            ),
        )
        return cursor.rowcount > 0

def marcar_como_notificada(codigo_externo: str):
    with _conectar() as conn:
        conn.execute(
            "UPDATE licitaciones_procesadas SET notificada = 1 WHERE codigo_externo = ?",
            (codigo_externo,),
        )

# ==========================================
# 3. CONSULTA API Y FILTRADO FLEXIBLE
# ==========================================
def limpiar_texto(texto: str) -> str:
    if not texto:
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFD", texto.lower())
        if unicodedata.category(c) != "Mn"
    )

def esta_vigente(fecha_cierre_str: str) -> bool:
    """Evita gastar tokens de IA en licitaciones vencidas durante el barrido histórico."""
    if not fecha_cierre_str:
        return True
    try:
        # Formato habitual API Mercado Público: YYYY-MM-DDTHH:MM:SS
        fecha_cierre = datetime.datetime.fromisoformat(fecha_cierre_str.replace("Z", ""))
        return fecha_cierre > datetime.datetime.now()
    except Exception:
        return True

def pasa_prefiltro_flexible(lic: dict) -> bool:
    """
    Filtro flexible:
    1. Descarta compras evidentes de bienes/obras/aseo.
    2. Aprueba si contiene alguna keyword amplia OR si proviene de un comprador clave pidiendo un servicio/programa.
    """
    nombre_norm = limpiar_texto(lic.get("Nombre", ""))
    if not nombre_norm:
        return False

    # Descartar ruido evidente
    if any(excl in nombre_norm for excl in KEYWORDS_EXCLUSION):
        return False

    # Coincidencia amplia en título
    if any(kw in nombre_norm for kw in KEYWORDS_AMPLIAS):
        return True

    # Paso por tipo de servicio/programa (la descripción completa se evaluará con IA)
    palabras_servicio = ["servicio de", "programa", "proyecto", "ejecucion de", "implementacion"]
    if any(ps in nombre_norm for ps in palabras_servicio) and any(
        comp in nombre_norm for comp in COMPRADORES_CLAVE
    ):
        return True

    return False

def consultar_api_por_fecha(fecha_obj: datetime.datetime) -> list:
    fecha_str = fecha_obj.strftime("%d%m%Y")
    url = "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"
    params = {"fecha": fecha_str, "ticket": TICKET_MERCADO_PUBLICO}
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get("Listado", [])
    except Exception as e:
        print(f"Error consultando Mercado Público para fecha {fecha_str}: {e}")
        return []

def enriquecer_con_detalle(licitacion: dict) -> dict:
    """Obtiene el organismo real y la descripción completa desde el endpoint por código."""
    codigo = licitacion.get("CodigoExterno")
    if not codigo:
        return licitacion

    url = "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"
    params = {"codigo": codigo, "ticket": TICKET_MERCADO_PUBLICO}
    try:
        res = requests.get(url, params=params, timeout=20)
        res.raise_for_status()
        listado = res.json().get("Listado", [])
        if listado:
            detalle = listado[0]
            licitacion["Organismo"] = detalle.get("Comprador", {}).get("NombreOrganismo", "Mercado Público")
            licitacion["Descripcion"] = detalle.get("Descripcion", licitacion.get("Nombre", ""))
    except Exception as e:
        print(f"No se pudo obtener detalle de {codigo}: {e}")
    return licitacion

def obtener_licitaciones(dias_atras: int = 0) -> list:
    hoy = datetime.datetime.now()
    licitaciones_por_codigo = {}

    for offset in range(dias_atras, -1, -1):
        fecha_consulta = hoy - datetime.timedelta(days=offset)
        print(f"Consultando API para el día: {fecha_consulta.strftime('%Y-%m-%d')}...")
        
        listado = consultar_api_por_fecha(fecha_consulta)
        for lic in listado:
            codigo = lic.get("CodigoExterno")
            if codigo:
                licitaciones_por_codigo[codigo] = lic
        
        if dias_atras > 0 and offset > 0:
            time.sleep(1.5)

    return list(licitaciones_por_codigo.values())

# ==========================================
# 4. EVALUACIÓN SEMÁNTICA CON GEMINI + BONO KEYWORDS
# ==========================================
def calcular_puntaje_final(licitacion: dict, evaluacion_ia: dict) -> dict:
    """
    Da prioridad principal a la interpretación de la IA (hasta 80 pts)
    y suma un bono de hasta 20 pts si incluye keywords estratégicas de JA Chile.
    """
    puntaje_ia = min(max(int(evaluacion_ia.get("puntaje_ia", 0)), 0), 80)
    texto_completo = limpiar_texto(
        f"{licitacion.get('Nombre', '')} {licitacion.get('Descripcion', '')}"
    )

    coincidencias = [kw for kw in KEYWORDS_ALTO_VALOR if kw in texto_completo]
    bono_keywords = min(len(coincidencias) * 5, 20)

    evaluacion_ia["puntaje_final"] = min(puntaje_ia + bono_keywords, 100)
    evaluacion_ia["bono_keywords"] = bono_keywords
    evaluacion_ia["keywords_detectadas"] = coincidencias
    return evaluacion_ia

def evaluar_con_gemini(licitacion: dict) -> dict:
    codigo = licitacion.get("CodigoExterno", "S/I")
    nombre = licitacion.get("Nombre", "")
    organismo = licitacion.get("Organismo", "Mercado Público")
    descripcion = licitacion.get("Descripcion", "Sin descripción adicional")
    
    prompt = f"""
    Eres un analista estratégico de licitaciones y desarrollo de negocios para Junior Achievement Chile (jachile.org).

    PERFIL INSTITUCIONAL DE JUNIOR ACHIEVEMENT CHILE:
    - Institución sin fines de lucro (fundada en Chile en 1994) dedicada a inspirar y preparar a jóvenes (principalmente estudiantes de liceos y enseñanza media) para el mundo laboral mediante aprendizaje activo ("aprender haciendo") y participación de voluntarios empresariales.
    - También realiza talleres de desarrollo de negocios para microempresarios adultos, actividades con mujeres líderes y proyectos escolares medioambientales.
    - ÁREAS Y PROGRAMAS DE REFERENCIA:
      1. Educación Financiera ("Impulso mis Finanzas"): ahorro, bancarización, presupuesto, crédito, inversión, seguridad financiera.
      2. Emprendimiento e Innovación ("La Compañía", "Innovation Camp", "JA TITAN"): creación de empresas escolares, Design Thinking, modelo Canvas, pitch, simulaciones empresariales, ferias de emprendimiento.
      3. Preparación para el Trabajo ("Planifico mi Futuro", "Socios por un Día"): orientación vocacional, proyecto de vida, exploración de carreras, CV, LinkedIn, visitas a empresas, vinculación escuela-empresa.
      4. Sostenibilidad y Medioambiente ("Emprendedores Climáticos", "AEMA"): cambio climático, economía circular, gestión de agua y residuos, energías renovables, ferias ecológicas comunitarias.
      5. Participación de Mujeres y Liderazgo ("Mujeres que la Rompen"): referentes femeninos, inspiración vocacional y liderazgo juvenil.

    CRITERIOS DE EVALUACIÓN FLEXIBLE (PRIORIDAD AL OBJETO REAL):
    - No te limites a buscar palabras exactas: evalúa si la metodología de talleres prácticos, mentorías, ferias, desafíos de innovación o capacitación de JA Chile puede resolver la necesidad del organismo comprador.
    - Niveles de pertinencia:
      * "Alta": Calza directamente con las temáticas, metodología activa y público juvenil/escolar de JA Chile.
      * "Condicionada": El objeto es afín (ej. emprendimiento para microempresarios adultos, programas de género/STEM, capacitación a docentes o medición/evaluación educativa), pero requiere confirmar capacidad interna o alcance.
      * "No relevante": Compra de bienes/equipamiento, obras, servicios clínicos/psicológicos individuales, reforzamiento escolar tradicional o desarrollo de software.
    - REGLA CRÍTICA DE VERIFICACIÓN: Nunca asumas que JA Chile posee acreditación OTEC, registro ATE, certificaciones específicas o cobertura regional garantizada. Si la licitación menciona requisitos habilitantes o técnicos, lístalos en "por_verificar" para revisión humana sin descartar la oportunidad si el objeto formativo encaja.

    Responde ÚNICAMENTE en JSON estricto con estos campos:
    - "es_relevante": (boolean) true si nivel_pertinencia es "Alta" o "Condicionada"; false si es "No relevante".
    - "nivel_pertinencia": (string) "Alta", "Condicionada" o "No relevante".
    - "puntaje_ia": (integer de 0 a 80) puntaje basado exclusivamente en qué tan bien se adapta el objeto y metodología de JA Chile (0-35: No relevante, 36-59: Condicionada, 60-80: Alta).
    - "programa_ja_sugerido": (string) nombre del programa de JA Chile más afín (o "Taller de Negocios Adultos" / "Diseño a medida").
    - "publico_objetivo": (string) público detectado en la licitación.
    - "justificacion": (string) explicación clara de cómo la propuesta de valor de JA Chile se adapta a esta oportunidad.
    - "por_verificar": (array de strings) requisitos como OTEC, ATE, experiencia acreditable, región o garantías que deben confirmarse antes de postular.

    LICITACIÓN A EVALUAR:
    - ID: {codigo}
    - Nombre: {nombre}
    - Organismo: {organismo}
    - Descripción: {descripcion}
    """
    
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        resultado = json.loads(response.text)
        return calcular_puntaje_final(licitacion, resultado)
    except Exception as e:
        print(f"Error evaluando {codigo} con Gemini: {e}")
        return {
            "es_relevante": False,
            "nivel_pertinencia": "No relevante",
            "puntaje_ia": 0,
            "puntaje_final": 0,
            "bono_keywords": 0,
            "keywords_detectadas": [],
            "programa_ja_sugerido": "N/A",
            "justificacion": "Error en evaluación",
            "publico_objetivo": "N/A",
            "por_verificar": []
        }

# ==========================================
# 5. ENVÍO DE CORREO HTML
# ==========================================
def enviar_notificacion_email(oportunidades, es_barrido_mensual=False) -> bool:
    """Envía un correo ordenado por puntaje híbrido destacando el programa sugerido y puntos a verificar."""
    destinatarios = [r.strip() for r in EMAIL_RECIPIENTS.split(",") if r.strip()]
    if not destinatarios:
        print("No hay destinatarios configurados.")
        return False

    fecha_hoy = datetime.date.today()
    etiqueta_periodo = " (Barrido Inicial 30 días)" if es_barrido_mensual else ""

    if not oportunidades:
        asunto = f"ℹ️ [JA Chile] Sin nuevas ofertas hoy{etiqueta_periodo} - {fecha_hoy}"
        cuerpo_html = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family: Arial, sans-serif; background-color: #f8fafc; padding: 20px;">
            <div style="max-width: 650px; margin: 0 auto; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px;">
                <h2 style="color: #0f172a; margin-top: 0;">ℹ️ Reporte Diario: Sin Novedades{etiqueta_periodo}</h2>
                <p style="color: #475569; font-size: 14px;">
                    El monitoreo de Mercado Público del <strong>{fecha_hoy}</strong> finalizó correctamente.
                </p>
                <p style="color: #475569; font-size: 14px;">
                    No se encontraron nuevas licitaciones pertinentes para Junior Achievement Chile.
                </p>
            </div>
        </body>
        </html>
        """
    else:
        asunto = f"🚨 [JA Chile] {len(oportunidades)} Nuevas Licitaciones Detectadas{etiqueta_periodo} - {fecha_hoy}"
        filas_html = ""
        for op in oportunidades:
            codigo = op.get('CodigoExterno', 'S/I')
            nivel = op.get('nivel_pertinencia', 'Alta')
            puntaje = op.get('puntaje_final', 0)
            bono = op.get('bono_keywords', 0)
            programa = op.get('programa_ja_sugerido', 'Diseño a medida')
            por_verificar = op.get('por_verificar', [])
            kws = op.get('keywords_detectadas', [])

            badge_color = "#16a34a" if nivel == "Alta" else "#d97706"
            verificacion_html = ""
            if por_verificar:
                items_verif = "".join(f"<li>{item}</li>" for item in por_verificar)
                verificacion_html = f"""
                <div style="background-color: #fffbeb; border-left: 4px solid #f59e0b; padding: 8px 12px; margin: 8px 0 14px 0; font-size: 12px; color: #92400e;">
                    <strong>⚠️ Por verificar antes de postular:</strong>
                    <ul style="margin: 4px 0 0 16px; padding: 0;">{items_verif}</ul>
                </div>
                """

            kws_html = (
                f"<p style='margin: 4px 0 0 0; font-size: 11px; color: #047857;'><strong>Keywords bono (+{bono} pts):</strong> {', '.join(kws)}</p>"
                if kws else ""
            )
            
            filas_html += f"""
            <div style="border: 1px solid #e2e8f0; padding: 18px; margin-bottom: 16px; border-radius: 8px; background-color: #ffffff;">
                <div style="margin-bottom: 8px;">
                    <span style="background-color: {badge_color}; color: #ffffff; font-size: 11px; font-weight: bold; padding: 3px 8px; border-radius: 4px; text-transform: uppercase;">
                        Pertinencia {nivel} · {puntaje}/100 pts
                    </span>
                    <span style="background-color: #e0e7ff; color: #3730a3; font-size: 11px; font-weight: bold; padding: 3px 8px; border-radius: 4px; margin-left: 6px;">
                        Programa afín: {programa}
                    </span>
                </div>
                <h3 style="margin: 6px 0 8px 0; color: #1d4ed8;">{op.get('Nombre', 'Sin título')}</h3>
                <p style="margin: 0 0 4px 0; font-size: 14px;"><strong>Organismo:</strong> {op.get('Organismo', 'Mercado Público')}</p>
                <p style="margin: 0 0 10px 0; font-size: 14px; color: #dc2626;"><strong>Cierre:</strong> {op.get('FechaCierre', 'Sin fecha informada')}</p>
                <p style="margin: 0 0 12px 0; font-size: 13px; color: #475569;">{op.get('Descripcion', '')}</p>
                
                <div style="background-color: #f0fdf4; border-left: 4px solid #16a34a; padding: 10px; margin: 10px 0;">
                    <strong style="color: #15803d; font-size: 13px;">Análisis Gemini AI:</strong>
                    <p style="margin: 4px 0 0 0; font-size: 13px; color: #166534;">{op.get('justificacion', '')}</p>
                    <p style="margin: 4px 0 0 0; font-size: 12px; color: #374151;"><strong>Público objetivo:</strong> {op.get('publico_objetivo', '')}</p>
                    {kws_html}
                </div>

                {verificacion_html}

                <!-- Bloque destacado para copiar el código -->
                <div style="background-color: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px; padding: 12px; text-align: center;">
                    <span style="display: block; font-size: 12px; color: #1e40af; margin-bottom: 6px;">
                        Copia y pega este código en el buscador de <strong>Mercado Público</strong>:
                    </span>
                    <div style="font-family: 'Courier New', Courier, monospace; font-size: 18px; font-weight: bold; color: #0f172a; background-color: #ffffff; border: 1px dashed #60a5fa; padding: 8px 14px; border-radius: 4px; display: inline-block; letter-spacing: 0.5px; user-select: all; -webkit-user-select: all;">
                        {codigo}
                    </div>
                </div>
            </div>
            """

        cuerpo_html = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family: Arial, sans-serif; background-color: #f8fafc; padding: 20px;">
            <div style="max-width: 650px; margin: 0 auto;">
                <h2 style="color: #0f172a;">Resumen de Oportunidades Detectadas - Mercado Público{etiqueta_periodo}</h2>
                <p style="color: #475569;">Se han encontrado <strong>{len(oportunidades)}</strong> licitaciones ordenadas por afinidad con Junior Achievement Chile:</p>
                {filas_html}
            </div>
        </body>
        </html>
        """

    msg = MIMEMultipart("alternative")
    msg['From'] = EMAIL_SENDER
    msg['To'] = ", ".join(destinatarios)
    msg['Subject'] = asunto
    msg.attach(MIMEText(cuerpo_html, 'html'))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, destinatarios, msg.as_string())
        print(f"Notificación enviada con éxito a: {', '.join(destinatarios)}")
        return True
    except Exception as e:
        print(f"Error enviando el correo de notificación: {e}")
        return False

# ==========================================
# 6. EJECUCIÓN PRINCIPAL
# ==========================================
def main():
    print("Iniciando escaneo y análisis de Mercado Público...")
    inicializar_db()
    
    primera_vez = es_primera_ejecucion()
    if primera_vez:
        print("Base de datos vacía detectada. Ejecutando barrido histórico de los últimos 30 días...")
        licitaciones_raw = obtener_licitaciones(dias_atras=30)
    else:
        print("Base de datos existente. Ejecutando monitoreo diario (solo hoy)...")
        licitaciones_raw = obtener_licitaciones(dias_atras=0)
    
    print(f"Total licitaciones únicas descargadas: {len(licitaciones_raw)}")

    # 1. Pre-filtro flexible, verificación de vigencia y anti-duplicados SQLite
    candidatas_nuevas = [
        lic for lic in licitaciones_raw 
        if pasa_prefiltro_flexible(lic)
        and esta_vigente(lic.get("FechaCierre", ""))
        and not ya_existe_licitacion(lic.get("CodigoExterno", ""))
    ]
    print(f"Licitaciones nuevas que pasan el filtro flexible hacia Gemini AI: {len(candidatas_nuevas)}")

    # 2. Enriquecer con detalle, evaluar con Gemini AI y registrar en DB
    relevantes = []
    for lic in candidatas_nuevas:
        lic = enriquecer_con_detalle(lic)
        time.sleep(0.5)
        
        evaluacion = evaluar_con_gemini(lic)
        registrar_licitacion(lic)
        
        if evaluacion.get("es_relevante") and evaluacion.get("nivel_pertinencia") in ["Alta", "Condicionada"]:
            lic.update(evaluacion)
            relevantes.append(lic)

    # Ordenar resultados por puntaje híbrido (IA + bono keywords) de mayor a menor
    relevantes.sort(key=lambda x: x.get("puntaje_final", 0), reverse=True)
    print(f"Confirmadas relevantes por Gemini AI: {len(relevantes)}")
    
    # 3. Envío automatizado por email
    if enviar_notificacion_email(relevantes, es_barrido_mensual=primera_vez):
        for lic in relevantes:
            marcar_como_notificada(lic.get("CodigoExterno", ""))

if __name__ == "__main__":

    main()
