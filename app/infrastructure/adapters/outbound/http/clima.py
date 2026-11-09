"""Cliente de Open-Meteo (puerto ApiClima): temperatura diaria media (histórico reciente + pronóstico)."""
import httpx


class ClienteOpenMeteo:
    def temperatura_historica(self, lat: float, lon: float, desde: str, hasta: str) -> dict[str, float]:
        """Temperatura diaria media entre dos fechas pasadas (archivo de Open-Meteo). Lanza excepción si no hay red."""
        r = httpx.get("https://archive-api.open-meteo.com/v1/archive", timeout=20, params={
            "latitude": lat, "longitude": lon, "daily": "temperature_2m_mean", "start_date": desde, "end_date": hasta,
            "timezone": "America/La_Paz"})
        d = r.json()["daily"]
        return {f: t for f, t in zip(d["time"], d["temperature_2m_mean"]) if t is not None}

    def temperatura_diaria(self, lat: float, lon: float) -> dict[str, float]:
        """{'2026-11-06': 27.4, ...}. Lanza excepción si no hay red."""
        r = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=6, params={
            "latitude": lat, "longitude": lon, "daily": "temperature_2m_mean", "past_days": 92,
            "forecast_days": 16, "timezone": "America/La_Paz"})
        d = r.json()["daily"]
        return {f: t for f, t in zip(d["time"], d["temperature_2m_mean"]) if t is not None}
