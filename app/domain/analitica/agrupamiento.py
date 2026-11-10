"""Aprendizaje no supervisado (clustering): agrupar platos para decidir cuáles mantener, ajustar o retirar.

Cada plato se describe con lo que realmente pasó en el comedor:
  - aceptación: porciones apartadas / cupo ofrecido
  - demanda media: porciones apartadas por vez que se sirvió
  - desperdicio medio: % que sobra en las bandejas (de las fotos analizadas), cuando hay suficientes fotos
K-Means agrupa los platos y se elige la cantidad de grupos con el índice de silueta.
(El costo por ración no está registrado en el sistema, por eso no entra al agrupamiento.)
"""
from collections import defaultdict
from typing import Callable

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

MIN_PLATOS = 4
MIN_REGISTROS = 2000        # registros (fecha × turno × plato) mínimos para agrupar
MIN_VECES_PLATO = 5         # un plato servido menos veces (pruebas, altas recientes) no tiene historial para juzgarlo


def calcular(filas_menus: list[dict], hoy: str, desperdicio: Callable[[], dict[str, float]], fuente_ok: Callable[[], bool],
             min_registros: int = MIN_REGISTROS, min_platos: int = MIN_PLATOS, min_veces: int = MIN_VECES_PLATO) -> dict:
    acum: dict[str, dict] = defaultdict(lambda: {"veces": 0, "cupo": 0, "apartadas": 0})
    registros = 0
    for x in filas_menus:
        if x["fecha"] <= hoy:
            registros += 1
            a = acum[x["platoId"]]
            a["veces"] += 1; a["cupo"] += x["cupo"]; a["apartadas"] += x["apartadas"]
    desp = desperdicio()
    todos = sorted(acum)
    platos = [p for p in todos if acum[p]["veces"] >= min_veces] or todos
    base = {"platos": len(platos), "minimo": min_platos, "fuenteOk": fuente_ok(),
            "registros": registros, "minimoRegistros": min_registros,
            "platosOmitidos": len(todos) - len(platos), "minimoVeces": min_veces}
    if registros < min_registros:
        return {**base, "suficiente": False,
                "mensaje": f"Se necesitan al menos {min_registros} registros de menús servidos para agrupar; hay {registros}."}
    if len(platos) < min_platos:
        return {**base, "suficiente": False,
                "mensaje": f"Se necesitan al menos {min_platos} platos servidos para agrupar; hay {len(platos)}."}

    filas = []
    for p in platos:
        a = acum[p]
        filas.append({"plato": p, "veces": a["veces"], "aceptacion": a["apartadas"] / a["cupo"] if a["cupo"] else 0.0,
                      "demandaMedia": a["apartadas"] / a["veces"], "desperdicio": desp.get(p)})
    usa_desperdicio = sum(f["desperdicio"] is not None for f in filas) >= max(min_platos, len(filas) * 0.3)
    cols = ["aceptacion", "demandaMedia"] + (["desperdicio"] if usa_desperdicio else [])
    medio_desp = float(np.mean([f["desperdicio"] for f in filas if f["desperdicio"] is not None])) if usa_desperdicio else 0.0
    X = np.array([[f["aceptacion"], f["demandaMedia"]] + ([f["desperdicio"] if f["desperdicio"] is not None else medio_desp] if usa_desperdicio else [])
                  for f in filas], dtype=float)

    unicos = len({tuple(np.round(r, 6)) for r in X})
    if unicos < 2:
        etiquetas = np.zeros(len(filas), dtype=int)
        k, sil = 1, None
    else:
        Z = StandardScaler().fit_transform(X)
        mejor = None
        for k_ in range(2, min(5, unicos, len(filas) - 1) + 1):   # k debe ser menor que el número de platos (silueta)
            lab = KMeans(n_clusters=k_, n_init=10, random_state=0).fit_predict(Z)
            if len(set(lab)) < 2:
                continue
            s = silhouette_score(Z, lab)
            if mejor is None or s > mejor[0]:
                mejor = (s, k_, lab)
        if mejor is None:
            sil, k, etiquetas = None, 1, np.zeros(len(filas), dtype=int)
        else:
            sil, k, etiquetas = mejor[0], mejor[1], mejor[2]

    grupos = []
    for c in sorted(set(etiquetas)):
        idx = [i for i, l in enumerate(etiquetas) if l == c]
        grupos.append({"id": int(c), "tam": len(idx), "aceptacion": float(np.mean(X[idx, 0])), "demandaMedia": float(np.mean(X[idx, 1])),
                       "desperdicio": float(np.mean(X[idx, 2])) if usa_desperdicio else None,
                       "puntaje": float(np.mean(X[idx, 0]) * 100 + np.mean(X[idx, 1]) - (np.mean(X[idx, 2]) if usa_desperdicio else 0))})
    orden = sorted(grupos, key=lambda g: -g["puntaje"])
    for i, g in enumerate(orden):
        if i == 0 and g["demandaMedia"] > 0:
            g["accion"], g["detalle"] = "Mantener", "Buena aceptación: conviene seguir ofreciéndolos."
        elif g["aceptacion"] < 0.05:
            g["accion"], g["detalle"] = "Retirar o rediseñar", "Casi nadie los aparta: revisar receta, horario o difusión."
        else:
            g["accion"], g["detalle"] = "Ajustar", "Aceptación media: probar otra porción, combinación o día."
    accion = {g["id"]: g["accion"] for g in grupos}
    puntos = [{**f, "cluster": int(l), "accion": accion[int(l)]} for f, l in zip(filas, etiquetas)]
    return {**base, "suficiente": True, "k": int(k), "silueta": None if sil is None else round(float(sil), 3),
            "variables": cols, "usaDesperdicio": usa_desperdicio, "grupos": grupos, "puntos": puntos,
            "nota": None if usa_desperdicio else
            "Aún no hay suficientes fotos de bandejas analizadas: el desperdicio se sumará al agrupamiento automáticamente."}
