# Privacy & Security

- API key: Set API_KEY in .env to require X-API-Key for sensitive writes (e.g., /config).
- Guard other writes like /routine similarly when API_KEY is set.
- CORS: Restrict EXPOSED_ORIGINS to your mobile app origins only.
- Tokens: OAuth tokens are stored in SQLite (embedded/app/data/smartmirror.db). Protect filesystem and device.
- Logging: Avoid logging PII; current logs are minimal. Increase log level cautiously.
- Network: Prefer LAN-only access or VPN. Do not expose the API publicly without auth.
- Data retention: Session metrics stored locally; provide a process to purge on request.
