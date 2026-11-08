"""Fotos de bandejas y respaldos en un bucket S3 de AWS (los datos no dependen del disco de un solo servidor).

El bucket es privado y tiene versionado: aunque se suba dos veces la misma clave, la versión anterior se conserva.
Las credenciales (S3_*) son de un usuario IAM que solo puede leer, escribir y listar ESE bucket; no puede borrar.
Si S3 no está configurado (desarrollo local) todo sigue funcionando con el disco local.
"""
import os
import re

_CLIENTE = {"c": None}
CLAVE_VALIDA = re.compile(r"^(bandejas|referencias|respaldos)/(?!.*\.\.)[A-Za-z0-9._/\-]{1,200}$")


def bucket() -> str:
    return os.getenv("S3_BANDEJAS_BUCKET", "")


def configurado() -> bool:
    return bool(bucket() and os.getenv("S3_ACCESS_KEY_ID") and os.getenv("S3_SECRET_ACCESS_KEY"))


def _s3():
    if _CLIENTE["c"] is None:
        import boto3
        from botocore.config import Config
        region = os.getenv("S3_REGION", "us-west-2")
        _CLIENTE["c"] = boto3.client(
            "s3", region_name=region,
            endpoint_url=f"https://s3.{region}.amazonaws.com",     # explícito: AWS_ENDPOINT_URL del servicio apunta a localstack
            aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}))
    return _CLIENTE["c"]


def clave_foto(carpeta: str, fid: str, fecha_iso: str | None = None) -> str:
    """bandejas/2026/11/<id>.jpg  (el id es único, así que ninguna foto pisa a otra)."""
    from datetime import date
    f = date.fromisoformat(fecha_iso[:10]) if fecha_iso else date.today()
    return f"{'referencias' if carpeta == 'ref' else 'bandejas'}/{f.year}/{f.month:02d}/{fid}.jpg"


def subir(clave: str, datos: bytes, content_type: str = "image/jpeg") -> bool:
    """Sube un objeto. Devuelve False (sin lanzar) si S3 no está configurado o falla: el disco local sigue siendo respaldo."""
    if not configurado() or not CLAVE_VALIDA.match(clave):
        return False
    try:
        _s3().put_object(Bucket=bucket(), Key=clave, Body=datos, ContentType=content_type, ServerSideEncryption="AES256")
        return True
    except Exception:
        return False


def existe(clave: str) -> bool:
    if not configurado() or not CLAVE_VALIDA.match(clave):
        return False
    try:
        _s3().head_object(Bucket=bucket(), Key=clave)
        return True
    except Exception:
        return False


def url_subida(clave: str, content_type: str = "image/jpeg", segundos: int = 600) -> str:
    """URL temporal para que el celular suba la foto directo a S3 (sin llevar claves de AWS)."""
    if not configurado():
        raise RuntimeError("S3 no está configurado en el servidor")
    if not CLAVE_VALIDA.match(clave):
        raise ValueError("Clave de foto inválida")
    return _s3().generate_presigned_url("put_object", ExpiresIn=segundos, HttpMethod="PUT",
                                        Params={"Bucket": bucket(), "Key": clave, "ContentType": content_type, "ServerSideEncryption": "AES256"})


def url_lectura(clave: str, segundos: int = 900) -> str | None:
    if not configurado() or not CLAVE_VALIDA.match(clave):
        return None
    return _s3().generate_presigned_url("get_object", ExpiresIn=segundos, Params={"Bucket": bucket(), "Key": clave})
