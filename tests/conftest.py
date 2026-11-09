"""Cada corrida de pruebas usa su PROPIA base de datos local (SQLite) en una carpeta temporal nueva.

Sin esto, las pruebas comparten un archivo que sobrevive entre ejecuciones y una prueba puede ver datos de otra
corrida (por ejemplo, un dispositivo registrado ayer). Debe fijarse antes de importar `app`.
"""
import atexit
import os
import shutil
import tempfile

_carpeta = tempfile.mkdtemp(prefix="comedor-pruebas-")
os.environ["AGENTES_DATA_DIR"] = _carpeta
atexit.register(shutil.rmtree, _carpeta, ignore_errors=True)
