# Contexto — imagen de DESARROLLO/PRUEBAS LOCALES, no de producción.
# Producción sigue siendo GitHub Actions (agente.yml / moderacion.yml),
# gratis y sin depender de que esta máquina esté prendida — ver README,
# sección "Docker para desarrollo local". Esta imagen sirve para correr un
# ciclo completo del pipeline en tu compu antes de subir un cambio.

FROM python:3.12-slim

WORKDIR /app

# Dependencias con versiones FIJADAS (requirements.txt) antes de copiar el
# código: aprovecha la caché de capas y da reproducibilidad.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Usuario no-root (revisión de seguridad 10 jul 2026): aunque esta imagen es
# solo para desarrollo local, correr como root es riesgo innecesario — si un
# feed malicioso o un envío hostil lograra ejecución dentro del contenedor,
# root facilita el escape al host (más con la carpeta del proyecto montada
# como volumen). El usuario 'contexto' basta para leer el código y escribir
# los .json de salida en el volumen montado.
RUN useradd --create-home --uid 10001 contexto \
    && chown -R contexto:contexto /app
USER contexto

CMD ["python", "agent/agent.py"]
