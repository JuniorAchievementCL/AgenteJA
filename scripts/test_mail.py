import os
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# 1. CREDENCIALES Y DESTINATARIOS
# ==========================================
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "suazotaku@gmail.com")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "gawl fggg xdyi jgeh")
EMAIL_RECIPIENTS = os.environ.get("EMAIL_RECIPIENTS", "suazotaku@gmail.com")


def generar_html_reporte(oportunidades: list, es_barrido_mensual: bool = False) -> tuple[str, str]:
    """Genera exactamente la misma plantilla HTML del sistema principal."""
    fecha_hoy = datetime.date.today()
    etiqueta_periodo = " (Barrido Inicial 30 días)" if es_barrido_mensual else ""

    asunto = f"🚨 [TEST - JA Chile] {len(oportunidades)} Nuevas Licitaciones Detectadas{etiqueta_periodo} - {fecha_hoy}"
    filas_html = ""

    for op in oportunidades:
        codigo = op.get("CodigoExterno", "S/I")
        nivel = op.get("nivel_pertinencia", "Alta")
        puntaje = op.get("puntaje_final", 0)
        bono = op.get("bono_keywords", 0)
        programa = op.get("programa_ja_sugerido", "Diseño a medida")
        por_verificar = op.get("por_verificar", [])
        kws = op.get("keywords_detectadas", [])

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
    <html lang="es">
    <body style="font-family: Arial, sans-serif; background-color: #f8fafc; padding: 20px;">
        <div style="max-width: 650px; margin: 0 auto;">
            <div style="background-color: #fef3c7; border: 1px solid #fcd34d; color: #92400e; padding: 8px 12px; border-radius: 6px; font-size: 12px; margin-bottom: 14px;">
                🧪 <strong>MODO PRUEBA:</strong> Vista previa del nuevo formato de alertas para Junior Achievement Chile.
            </div>
            <h2 style="color: #0f172a;">Resumen de Oportunidades Detectadas - Mercado Público{etiqueta_periodo}</h2>
            <p style="color: #475569;">Se han encontrado <strong>{len(oportunidades)}</strong> licitaciones ordenadas por afinidad con Junior Achievement Chile:</p>
            {filas_html}
        </div>
    </body>
    </html>
    """
    return asunto, cuerpo_html


def enviar_correo_prueba():
    destinatarios = [r.strip() for r in EMAIL_RECIPIENTS.split(",") if r.strip()]
    if not destinatarios:
        print("No hay destinatarios configurados.")
        return

    # 2. Datos simulados que reflejan la salida exacta de evaluar_con_gemini() + calcular_puntaje_final()
    oportunidades_prueba = [
        {
            "CodigoExterno": "738801-12-LQ26",
            "Nombre": "Programa de Formación en Educación Financiera y Cultura Emprendedora para Liceos Técnico-Profesionales",
            "Organismo": "Servicio Local de Educación Pública (SLEP) Gabriela Mistral",
            "FechaCierre": "2026-12-05T15:00:00",
            "Descripcion": "Contratación de talleres prácticos de ahorro, presupuesto personal, desarrollo de modelos de negocio y feria escolar de emprendimiento para 400 estudiantes de enseñanza media.",
            "es_relevante": True,
            "nivel_pertinencia": "Alta",
            "puntaje_ia": 78,
            "bono_keywords": 15,
            "puntaje_final": 93,
            "keywords_detectadas": ["educacion financiera", "emprendimiento escolar", "liceo"],
            "programa_ja_sugerido": "Impulso mis Finanzas + La Compañía",
            "publico_objetivo": "Estudiantes de enseñanza media técnico-profesional (400 alumnos)",
            "justificacion": "Calza directamente con la metodología de aprender haciendo de JA Chile. Combina módulos prácticos de finanzas personales, creación de emprendimientos estudiantiles y cierre con feria de proyectos.",
            "por_verificar": [
                "Confirmar si las bases exigen inscripción vigente en registro ATE.",
                "Validar disponibilidad de facilitadores presenciales en comunas del SLEP."
            ]
        },
        {
            "CodigoExterno": "2450-88-LE26",
            "Nombre": "Servicio de Talleres de Desarrollo de Negocios y Pitch para Mujeres Emprendedoras Locales",
            "Organismo": "Ilustre Municipalidad de Providencia - Departamento de Fomento Productivo",
            "FechaCierre": "2026-12-02T17:30:00",
            "Descripcion": "Ejecución de 6 jornadas formativas en modelo Canvas, costos básicos, marketing digital y presentación tipo pitch para mujeres con microemprendimientos en etapa inicial.",
            "es_relevante": True,
            "nivel_pertinencia": "Condicionada",
            "puntaje_ia": 54,
            "bono_keywords": 10,
            "puntaje_final": 64,
            "keywords_detectadas": ["mujeres emprendedoras", "desarrollo de negocios"],
            "programa_ja_sugerido": "Taller de Negocios Adultos / Mujeres que la Rompen",
            "publico_objetivo": "Mujeres microempresarias adultas de la comuna",
            "justificacion": "Aunque el público principal de JA Chile es juvenil, la organización cuenta con experiencia en talleres de desarrollo de negocios para microempresarios y actividades con referentes femeninos usando Canvas y pitch.",
            "por_verificar": [
                "Confirmar capacidad interna y disponibilidad de currículo vigente para público adulto.",
                "Revisar si se solicita acreditación OTEC."
            ]
        }
    ]

    asunto, cuerpo_html = generar_html_reporte(oportunidades_prueba)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"] = EMAIL_SENDER
    msg["To"] = ", ".join(destinatarios)
    msg.attach(MIMEText(cuerpo_html, "html"))

    # 3. Envío SMTP
    try:
        print(f"Enviando correo de prueba a: {destinatarios}...")
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, destinatarios, msg.as_string())
        print("✅ Correo de prueba enviado con éxito.")
    except Exception as e:
        print(f"❌ Error al enviar correo de prueba: {e}")


if __name__ == "__main__":
    enviar_correo_prueba()