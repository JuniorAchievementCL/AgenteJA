# AgenteJA
Proyecto de monitoreo para fuentes de financiamiento de programas JA en Mercadopublico.cl

Cada lunes hace envío de los proyectos de licitación que se adecúen a los requerimientos de Junior Achievement y les asigna un puntaje para el mismo. La funcionalidad completa del sistema/agente, se encuentra en la archivo python llamado mmp (monitor mercado público) dentro de la carpeta scripts.

El esquema de los envíos de correos se encuentra dentro de la carpeta .github/workflow en el archivo llamado automatesystem. Para modificar el correo que los envía, se ajusta en Settings (barra superior) -> Secrets and Variables (columna de configuración abajo a la izquierda) -> Actions


EMAIL_SENDER correo principal que hará el envío de los emails.
EMAIL_PASSWORD contraseña del correo principal que requiere de verificación de dos pasos que permita obtener la clave de 16 carácteres (preguntar a la IA cómo hacerlo en caso de no saber)
EMAIL_RECIPIENTS es el correo de quien los recibirá, se recomienda no cambiarlo al de alguien que no haya solicitado estos correos.
GEMINI_API_KEY es la API que se obtiene en GEMINI para desarrollar herramientas automatizadas, puede cambiarse el modelo o incluso de proveedor de servicios de IA (como Claude AI o ChatGPT)
MERCADO_PUBLICO_API se solicita en la página oficial de mercado público con una clave única (es requisito tener nacionalidad chilena y poseer un rut)
