# Trabajo-Final-De-Graduacion
Espejo Interactivo de Bienestar y Ejercicio Personalizado con Inteligencia Artificial (Interactive Mirror for Personalized Wellness and Exercise Using Artificial Intelligence)

Monorepo con backend embebido (FastAPI/Python) y app móvil (Expo/React Native).

## Estructura
- embedded/: backend Python (FastAPI, visión, biometría, voz, entrenador, GUI)
- mobile/: app móvil Expo/React Native (ProgressTracking, Achievements)
- docs/: documentos del TFG

## Endpoints REST (JSON)
- POST /posture
- POST /biometrics
- POST /routine
- POST /config

Todas las respuestas: { success, data, error }.

## Requisitos
- Raspberry Pi 4, cámara compatible, pantalla espejo
- Python 3.x, OpenCV, MediaPipe, TFLite, Vosk/Google Speech
- Fitbit Web API (OAuth2)

## Desarrollo rápido
- Backend: ver embedded/README.md
- Móvil: ver mobile/README.md

## Licencia
MIT
