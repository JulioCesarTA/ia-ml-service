"""Archivos locales de visión (puerto ArchivosVision): fotos en <datos>/fotos y prototipos <id>.npz de cada referencia."""
import os

import numpy as np


class ArchivosVisionDisco:
    def __init__(self, directorio_datos: str):
        self._datos = directorio_datos

    def _dir(self) -> str:
        d = os.path.join(self._datos, "fotos")
        os.makedirs(d, exist_ok=True)
        return d

    def guardar_foto(self, carpeta: str, fid: str, jpeg: bytes) -> None:
        os.makedirs(os.path.join(self._dir(), carpeta), exist_ok=True)
        with open(os.path.join(self._dir(), carpeta, f"{fid}.jpg"), "wb") as f:
            f.write(jpeg)

    def ruta_foto(self, carpeta: str, fid: str) -> str | None:
        p = os.path.join(self._dir(), carpeta, f"{fid}.jpg")
        return p if os.path.exists(p) else None

    def guardar_prototipos(self, rid: str, comida, fondo) -> None:
        np.savez(os.path.join(self._dir(), f"{rid}.npz"), comida=comida, fondo=fondo)

    def cargar_prototipos(self, rid: str) -> dict:
        p = np.load(os.path.join(self._dir(), f"{rid}.npz"))
        return {"comida": p["comida"], "fondo": p["fondo"]}

    def hay_prototipos(self, rid: str) -> bool:
        return os.path.exists(os.path.join(self._dir(), f"{rid}.npz"))
