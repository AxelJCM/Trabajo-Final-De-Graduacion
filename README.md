# Trabajo-Final-De-Graduacion
Espejo Interactivo de Bienestar y Ejercicio Personalizado con Inteligencia Artificial (Interactive Mirror for Personalized Wellness and Exercise Using Artificial Intelligence)

Repositorio para el backend embebido (FastAPI/Python) que corre en el espejo inteligente.

Nota: La app móvil fue descopiada del alcance actual, por lo que este repositorio se centra únicamente en el backend embebido.

## Estructura
- embedded/: backend Python (FastAPI, visión, biometría, voz, GUI)
- docs/: documentos del TFG

## Endpoints REST (JSON)
- GET /health
- POST /posture
- POST /biometrics
- GET /biometrics/last
- POST /config
- POST /voice/test

Todas las respuestas: { success, data, error }.

## Requisitos
- Raspberry Pi 4, cámara compatible, pantalla espejo
- Python 3.x, OpenCV, MediaPipe, TFLite, Vosk/Google Speech
- Fitbit Web API (OAuth2)

## Desarrollo rápido
- Backend: ver embedded/README.md. Las variables de entorno se configuran en `embedded/.env` (plantilla en `embedded/.env.example`).

## Licencia
MIT
