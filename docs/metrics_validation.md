# Plan de validación y métricas

## Visión / postura
- **Conteo de repeticiones:** comparar `rep_totals` vs conteo manual para squat, push-up y crunch (≥ 30 repeticiones por ejercicio). Meta ≤ 1 error cada 10 repeticiones. Registrar resultados y condiciones de iluminación.
- **Latencia p50/p95:** loguear `latency_ms_p50` y `latency_ms_p95` de `POST /posture` durante una sesión de 5 minutos. Objetivo: p50 \< 120 ms, p95 \< 180 ms.
- **FPS:** observar el campo `fps` (y log `PoseEstimator`) para confirmar 12–15 FPS en la Raspberry Pi.

## Biometría
- **Freshness Fitbit:** monitorear `staleness_sec` en `/biometrics/last` con el reloj activo. Debe permanecer \< `FITBIT_POLL_INTERVAL * 2`. Registrar cualquier cambio a amarillo/rojo (`fitbit_status_level`).
- **Zona cardíaca:** verificar que `zone_name` y `zone_color` cambien de acuerdo a intensidades (reposo → cardio → pico) durante intervalos controlados.

## Sesiones
- **Persistencia:** tras ejecutar `start → pause → resume → stop`, comprobar que `/session/last` contiene `duration_active_sec`, `avg_hr`, `avg_quality` y `total_reps` consistentes con los datos en vivo.
- **Historial:** validar que `/session/history` pagine correctamente (`limit=5`) y que los valores se graben en `session_metrics` (SQLite).

## Voz
- **Tasa de aciertos:** usar `scripts/run_voice_listener.py --base-url <API>` y ejecutar 20 comandos por intent (`start`, `pause`, `stop`, `next`). Medir porcentaje de aciertos y registrar la frase utilizada.
- **Confirmación visual:** confirmar que el HUD refleje `last_command` (con marca temporal) dentro de 1 segundo tras cada comando exitoso.

## HUD / CLI
- **Layout:** comprobar en HUD y CLI que los bloques muestren la información acordada (sesión, biometría, postura, feedback, cronómetro).
- **Errores:** simular pérdida de Fitbit (desactivar Wi-Fi) y verificar transición a `fitbit_status_level="red"` en el HUD.
