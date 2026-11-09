"""Reglas de las claves de las fotos y respaldos en el bucket: dónde va cada archivo y qué claves son válidas."""
import re
from datetime import date

CLAVE_VALIDA = re.compile(r"^(bandejas|referencias|respaldos)/(?!.*\.\.)[A-Za-z0-9._/\-]{1,200}$")


def clave_foto(carpeta: str, fid: str, fecha_iso: str | None = None) -> str:
    """bandejas/2026/11/<id>.jpg  (el id es único, así que ninguna foto pisa a otra)."""
    f = date.fromisoformat(fecha_iso[:10]) if fecha_iso else date.today()
    return f"{'referencias' if carpeta == 'ref' else 'bandejas'}/{f.year}/{f.month:02d}/{fid}.jpg"
