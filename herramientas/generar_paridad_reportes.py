"""Genera el archivo de referencia («golden») con el que se comprueba que el motor de reportes del navegador (JS) y el
del teléfono (Dart) dan EXACTAMENTE lo mismo que el del servidor (Python).

El motor corre en tres lugares para que los reportes funcionen sin internet (web, celular) y desde el servidor.
Este script ejecuta ~40 consultas con el motor de Python sobre una muestra fija de los datos reales y guarda las
respuestas. Los tests de JS y de Dart cargan ese archivo, repiten las consultas y comparan.

Uso (desde ia-ml-service, con internet para bajar los datos de la muestra):
    python herramientas/generar_paridad_reportes.py
    python herramientas/generar_paridad_reportes.py --reusar    # misma muestra de datos del archivo actual, sin red
Escribe ../comedor-clientes/pruebas-comunes/reportes-paridad.json
"""
import json
import os
import sys
from datetime import date

import httpx
import urllib3

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.domain.reportes import catalogo, lenguaje, motor  # noqa: E402

urllib3.disable_warnings()
SERVIDOR = os.getenv("COMEDOR_API", "https://44.228.1.64:8080")
HOY = date(2026, 11, 8)
SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "comedor-clientes", "pruebas-comunes",
                      "reportes-paridad.json")

# Cada caso: (texto, ¿continúa la consulta anterior?)
CASOS = [
    ("total cobrado por mes en 2025", False),
    ("los 5 platos más reservados de este mes", False),
    ("pagos mayores a 5 bolivianos de noviembre ordenados por monto descendente", False),
    ("reservas de almuerzo por semana de los últimos 30 días", False),
    ("estudiantes sin beca ordenados por nombre", False),
    ("insumos con stock bajo", False),
    ("promedio de desperdicio por plato", False),
    ("cuántas reservas por día de la semana", False),
    ("recaudación por método de pago", False),
    ("los 10 estudiantes que más reservaron", False),
    ("menús con menos cupos disponibles", False),
    ("becas sin usar", False),
    ("pagos del 1 al 15 de octubre", False),
    ("reservas canceladas por mes", False),
    ("total cobrado en efectivo este año", False),
    ("cuántos pagos distintos por estudiante", False),
    ("insumos que vencen en los próximos 7 días", False),
    ("ocupación promedio por turno", False),
    ("pagos de ana rojas", False),
    ("reservas por plato y turno", False),
    ("pagos de hoy", False),
    ("pagos de ayer", False),
    ("pagos del mes pasado", False),
    ("pagos del primer trimestre de 2026", False),
    ("pagos desde 2024", False),
    ("pagos entre 10 y 20 bolivianos", False),
    ("pagos sin efectivo", False),
    ("los 2 pagos más altos", False),
    ("muéstrame solo fecha y monto de los pagos", False),
    ("pagos en pdf", False),
    ("pagos de nobiembre", False),                       # tipeo
    ("asistencia del personal de este mes", False),
    ("cuántas marcas por persona", False),
    ("marcas fuera del comedor", False),
    ("entradas por día de la semana", False),
    ("hola qué tal", False),                             # sin sentido: baja confianza
    ("pagos de noviembre", False),                       # conversación: tres pasos encadenados
    ("ahora por mes", True),
    ("solo en efectivo", True),
    ("quítale los filtros", True),
    # como lo escribe o lo dicta la gente: sin tildes, con faltas, coloquial
    ("cuanta comida se tira", False),
    ("plato con mas sobras", False),
    ("eh mostrame los pagos de los ultimos 15 dias porfa", False),
    ("plata que entro en octubre", False),
    ("pagos de ocutbre ordenados del mayor al menor", False),
    ("reservas canseladas", False),
    ("que insumos faltan", False),
    ("pagos de este año", False),                        # conversación dictada
    ("ahora agrupalo por mes", True),
    ("solo los de qr", True),
    ("pasamelo a excel", True),
]

# Marcas de asistencia de ejemplo (en producción puede no haber ninguna el día que se genera)
ASISTENCIA = [
    ["2026-11-02", "07:05", "cocinero.demo", "cocina_almacen", "Entrada", 12, "En el comedor", "No"],
    ["2026-11-02", "15:10", "cocinero.demo", "cocina_almacen", "Salida", 18, "En el comedor", "No"],
    ["2026-11-03", "07:20", "cocinero.demo", "cocina_almacen", "Entrada", 25, "En el comedor", "No"],
    ["2026-11-03", "15:00", "cocinero.demo", "cocina_almacen", "Salida", 4121, "Fuera del comedor", "Sí"],
    ["2026-11-04", "06:55", "admin.comedor", "administrador", "Entrada", 3, "En el comedor", "No"],
    ["2026-11-04", "14:30", "admin.comedor", "administrador", "Salida", 9, "En el comedor", "No"],
    ["2026-11-05", "08:40", "admin.comedor", "administrador", "Entrada", 2150, "Fuera del comedor", "Sí"],
    ["2026-11-05", "13:00", "admin.comedor", "administrador", "Salida", 6, "En el comedor", "No"],
    ["2026-11-06", "07:00", "cocinero.demo", "cocina_almacen", "Entrada", 8, "En el comedor", "No"],
    ["2026-11-06", "15:05", "cocinero.demo", "cocina_almacen", "Salida", 11, "En el comedor", "No"],
]


def muestra(filas: list) -> list:
    """Muestra fija: las más recientes (para que «este mes» y «hoy» tengan datos) y una de las antiguas."""
    if len(filas) <= 400:
        return filas
    paso = max(1, len(filas) // 220)
    return filas[::paso][:220] + filas[-180:]


def main() -> None:
    if "--reusar" in sys.argv:                           # misma muestra de datos que el archivo actual (sin red)
        print("Reusando la muestra de datos del archivo actual…")
        datasets = json.load(open(SALIDA, encoding="utf-8"))["datasets"]
    else:
        print("Bajando una muestra de los datos reales…")
        snap = httpx.get(f"{SERVIDOR}/reportes/snapshot?rol=administrador", verify=False, timeout=180).json()
        datasets = {}
        for did, t in snap["datasets"].items():
            datasets[did] = {"columnas": t["columnas"], "filas": muestra(t["filas"])}
    if not datasets.get("asistencia", {}).get("filas"):
        datasets["asistencia"] = {"columnas": [c["nombre"] for c in catalogo.DATASETS["asistencia"]["columnas"]], "filas": ASISTENCIA}

    registros = {d: [dict(zip(t["columnas"], f)) for f in t["filas"]] for d, t in datasets.items()}
    cat = json.loads(json.dumps(catalogo.DATASETS))        # el catálogo tal como lo recibe el cliente (JSON)

    casos, previa = [], None
    for texto, continuar in CASOS:
        caso = {"texto": texto, "continuar": continuar}
        try:
            leido = lenguaje.interpretar(texto, previa=previa if continuar else None, hoy=HOY, registros=registros)
            r = motor.ejecutar(leido["spec"], registros)
            previa = leido["spec"]
            caso["esperado"] = {
                "dataset": r["dataset"], "modo": r["modo"], "titulo": r["titulo"], "entendi": leido["entendi"],
                "spec": leido["spec"], "confianza": leido["confianza"], "continuacion": leido["continuacion"],
                "columnas": r["columnas"], "filas": r["filas"], "totales": r["totales"], "grafico": r["grafico"],
                "resumen": r["resumen"], "condiciones": r["condiciones"], "notas": r["notas"] + leido["notas"],
                "registrosAnalizados": r["registrosAnalizados"], "totalFilas": r["totalFilas"], "mostradas": r["mostradas"],
            }
        except (lenguaje.NoEntendido, motor.ConsultaInvalida) as e:
            caso["esperado"] = {"error": str(e)}
            previa = None
        casos.append(caso)

    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    texto = json.dumps({"hoy": HOY.isoformat(), "catalogo": cat, "datasets": datasets, "casos": casos},
                       ensure_ascii=False, separators=(",", ":"))
    open(SALIDA, "w", encoding="utf-8").write(texto)
    con_datos = sum(1 for c in casos if "filas" in c["esperado"] and c["esperado"]["filas"])
    print(f"{len(casos)} consultas ({con_datos} con filas) · {os.path.getsize(SALIDA) / 1024:.0f} KB -> {os.path.normpath(SALIDA)}")


if __name__ == "__main__":
    main()
