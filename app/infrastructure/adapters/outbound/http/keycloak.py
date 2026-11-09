"""Cliente de Keycloak (puerto ProveedorIdentidad): busca usuarios y sus roles, y comprueba contraseñas."""
import os

import httpx


def _kc() -> str:
    return os.getenv("KEYCLOAK_URL", "http://keycloak:8080")


def _realm() -> str:
    return os.getenv("KEYCLOAK_REALM", "comedor-uagrm")


def _token_admin(http: httpx.Client) -> str:
    r = http.post(f"{_kc()}/realms/master/protocol/openid-connect/token", data={
        "grant_type": "password", "client_id": "admin-cli",
        "username": os.getenv("KEYCLOAK_ADMIN", "admin"), "password": os.getenv("KEYCLOAK_ADMIN_PASSWORD", "admin")})
    r.raise_for_status()
    return r.json()["access_token"]


class ClienteKeycloak:
    def usuario_por_email(self, email: str) -> dict | None:
        """{username, firstName, lastName, roles:[nombres de rol de Keycloak]} o None. Lanza excepción si Keycloak no responde."""
        with httpx.Client(timeout=10) as http:
            h = {"Authorization": f"Bearer {_token_admin(http)}"}
            us = http.get(f"{_kc()}/admin/realms/{_realm()}/users", params={"email": email, "exact": "true"}, headers=h).json()
            if not us:
                return None
            u = us[0]
            rr = http.get(f"{_kc()}/admin/realms/{_realm()}/users/{u['id']}/role-mappings/realm", headers=h).json()
            return {"username": u["username"], "firstName": u.get("firstName"), "lastName": u.get("lastName"),
                    "roles": [r["name"] for r in rr]}

    def verificar_password(self, username: str, password: str) -> bool:
        r = httpx.post(f"{_kc()}/realms/{_realm()}/protocol/openid-connect/token", timeout=10, data={
            "grant_type": "password", "client_id": "backoffice-gestion", "username": username, "password": password})
        return r.status_code == 200
