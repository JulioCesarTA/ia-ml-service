"""Cliente de Open-Meteo: temperatura diaria media (histórico reciente + pronóstico)."""
import httpx


def temperatura_diaria(lat: float, lon: float) -> dict[str, float]:
    """{'2026-11-06': 27.4, ...}. Lanza excepción si no hay red."""
    r = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=6, params={
        "latitude": lat, "longitude": lon, "daily": "temperature_2m_mean", "past_days": 92,
        "forecast_days": 16, "timezone": "America/La_Paz"})
    d = r.json()["daily"]
    return {f: t for f, t in zip(d["time"], d["temperature_2m_mean"]) if t is not None}
