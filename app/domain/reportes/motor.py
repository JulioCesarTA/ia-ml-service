"""Motor de consultas de los reportes: ejecuta la consulta estructurada que arma el lenguaje natural.

Es la implementación de referencia: el navegador (motor.js) y el teléfono (motor.dart) la repiten para funcionar
sin internet, y el archivo de paridad generado con esta versión comprueba que los tres dan lo mismo.

Consulta (spec):
    dataset   reservas | pagos | estudiantes | becas | menus | insumos | desperdicio
    columnas  columnas a mostrar (si no se agrupa)
    fecha     {col?, desde, hasta, etiqueta}
    filtros   [{col, op, valor, post?}]   op: = != > >= < <= entre contiene en no_en dia_semana
    agrupar   [{col, por?}]               por (fechas): dia | semana | mes | trimestre | anio | dia_semana
    medidas   [{fn, col?}]                fn: count | sum | avg | max | min | nunique
    orden     [{col, dir}]                dir: asc | desc
    limite    entero
"""
import math
import unicodedata
from datetime import date, datetime, timedelta

from app.domain.reportes import catalogo

MESES_N = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS_N = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES3 = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
POR_ETIQUETA = {"dia": "Día", "semana": "Semana", "mes": "Mes", "trimestre": "Trimestre", "anio": "Año", "dia_semana": "Día de la semana"}
FN_ETIQUETA = {"sum": "Total de", "avg": "Promedio de", "max": "Máximo de", "min": "Mínimo de", "nunique": "Distintos de"}
FN_BASE = {"sum": "total", "avg": "promedio", "max": "maximo", "min": "minimo", "nunique": "distintos"}
SIMB = {"=": "=", "!=": "≠", ">": ">", ">=": "≥", "<": "<", "<=": "≤"}


class ConsultaInvalida(ValueError):
    pass


# ----------------------------- utilidades -----------------------------

def sin_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm_simple(v) -> str:
    return sin_acentos(str(v).lower().strip())


def num(v) -> float:
    """El valor como número; NaN si no lo es (para que los vacíos no cuenten en las medidas)."""
    if v is None or v == "":
        return math.nan
    try:
        return float(v)
    except (TypeError, ValueError):
        return math.nan


def redondear(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)) and math.isfinite(v):
        r = round(float(v), 2)
        return int(r) if isinstance(v, int) or r == int(r) and abs(r) < 1e15 and isinstance(v, int) else r
    return v


def _dia_iso(v) -> str | None:
    return str(v)[:10] if v not in (None, "") else None


def _fecha(s) -> date:
    return date.fromisoformat(str(s)[:10])


def dmy(d: date) -> str:
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def fmt_valor(v, fmt: str | None) -> str:
    """Mismo formato que ven los clientes (es-BO: miles con punto, decimales con coma)."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        def n(x, d):
            return f"{x:,.{d}f}".replace(",", "\u0001").replace(".", ",").replace("\u0001", ".")
        if fmt == "moneda":
            return f"Bs {n(v, 2)}"
        if fmt == "porcentaje":
            return f"{n(v, 1)}%"
        return n(v, 0) if float(v).is_integer() else n(v, 2)
    return str(v)


# ----------------------------- filtros -----------------------------

def _aplicar_filtro(rows: list[dict], f: dict, dataset: str) -> list[dict]:
    cat = next((c for c in catalogo.DATASETS[dataset]["columnas"] if c["nombre"] == f["col"]), None)
    if not cat:
        raise ConsultaInvalida(f"La columna «{f['col']}» no existe en {catalogo.DATASETS[dataset]['etiqueta']}")
    lista = f["valor"] if isinstance(f["valor"], list) else [f["valor"]]

    if f["op"] == "dia_semana":
        return [r for r in rows if r.get(f["col"]) and _fecha(r[f["col"]]).weekday() in lista]

    if cat["tipo"] == "fecha":
        leer, vals = _dia_iso, [str(x)[:10] for x in lista]
    elif cat["tipo"] == "numero":
        leer, vals = num, [num(x) for x in lista]
    else:
        leer = lambda v: None if v is None else norm_simple(v)      # noqa: E731
        vals = [norm_simple(x) for x in lista]

    def ok(v) -> bool:
        op = f["op"]
        try:
            if op == "=":
                return v == vals[0]
            if op == "!=":
                return v != vals[0]
            if op == ">":
                return v > vals[0]
            if op == ">=":
                return v >= vals[0]
            if op == "<":
                return v < vals[0]
            if op == "<=":
                return v <= vals[0]
            if op == "entre":
                return min(vals) <= v <= max(vals)
            if op == "contiene":
                return str(vals[0]) in str(v)
            if op == "en":
                return v in vals
            if op == "no_en":
                return v not in vals
        except TypeError:
            return False
        raise ConsultaInvalida(f"Operador desconocido: {op}")

    # los «distintos de» (!=, no_en) conservan también los vacíos, como esperaría una persona
    neg = f["op"] in ("!=", "no_en")
    out = []
    for r in rows:
        v = leer(r.get(f["col"]))
        vacio = v is None or (isinstance(v, float) and math.isnan(v))
        if neg if vacio else ok(v):
            out.append(r)
    return out


def _rango_fecha(rows: list[dict], f: dict, dataset: str) -> list[dict]:
    c = f.get("col") or catalogo.DATASETS[dataset].get("fecha")
    if not c:
        return rows
    desde, hasta = f.get("desde"), f.get("hasta")
    out = []
    for r in rows:
        v = _dia_iso(r.get(c))
        if v is not None and (not desde or v >= desde) and (not hasta or v <= hasta):
            out.append(r)
    return out


# ----------------------------- agrupación y medidas -----------------------------

def _clave_fecha(v, por: str) -> tuple[str, str]:
    d = _fecha(v)
    if por == "dia":
        return d.isoformat(), dmy(d)
    if por == "semana":
        lunes = d - timedelta(days=d.weekday())
        return lunes.isoformat(), f"Sem. {dmy(lunes)[:5]}"
    if por == "mes":
        return f"{d.year}-{d.month:02d}", f"{MESES3[d.month - 1]} {d.year}"
    if por == "trimestre":
        q = (d.month + 2) // 3
        return f"{d.year}-T{q}", f"T{q} {d.year}"
    if por == "anio":
        return str(d.year), str(d.year)
    if por == "dia_semana":
        return str(d.weekday()), DIAS_N[d.weekday()].capitalize()
    raise ConsultaInvalida(f"No sé agrupar por «{por}»")


def medida_info(dataset: str, m: dict) -> dict:
    if m["fn"] == "count":
        return {"key": "cantidad", "label": "Cantidad", "fmt": "entero"}
    cat = catalogo.columna(dataset, m["col"])
    fmt = "entero" if m["fn"] == "nunique" else cat["fmt"]
    if m["fn"] == "avg" and fmt == "entero":
        fmt = "decimal"
    return {"key": f"{FN_BASE[m['fn']]}_{m['col']}", "label": f"{FN_ETIQUETA[m['fn']]} {cat['etiqueta'].lower()}", "fmt": fmt}


def _calcular(rows: list[dict], m: dict):
    if m["fn"] == "count":
        return len(rows)
    if m["fn"] == "nunique":
        return len({r.get(m["col"]) for r in rows})
    v = [x for x in (num(r.get(m["col"])) for r in rows) if not math.isnan(x)]
    if not v:
        return None
    if m["fn"] == "sum":
        return sum(v)
    if m["fn"] == "avg":
        return sum(v) / len(v)
    if m["fn"] == "max":
        return max(v)
    return min(v)


def _agrupar(rows: list[dict], spec: dict, dataset: str) -> tuple[list[dict], list[dict]]:
    meta, claves = [], []
    for g in spec["agrupar"]:
        cat = catalogo.columna(dataset, g["col"])
        if cat["tipo"] == "fecha":
            por = g.get("por") or "mes"
            meta.append({"key": por, "label": POR_ETIQUETA[por], "tipo": "texto", "fmt": None})
            claves.append((por, lambda r, c=g["col"], p=por: _clave_fecha(r[c], p) if r.get(c) else None))
        else:
            meta.append({"key": g["col"], "label": cat["etiqueta"], "tipo": "texto", "fmt": None})
            claves.append((g["col"], lambda r, c=g["col"]: ((str(r[c]) if r.get(c) is not None else "(sin dato)"),) * 2))

    grupos: dict[str, dict] = {}
    for r in rows:
        ks = [leer(r) for _, leer in claves]
        if any(k is None for k in ks):
            continue
        ident = "\u0001".join(k[0] for k in ks)
        grupos.setdefault(ident, {"ks": ks, "rows": []})["rows"].append(r)

    infos = [medida_info(dataset, m) for m in spec["medidas"]]
    out = []
    for g in grupos.values():
        fila = {}
        for i, (nombre, _) in enumerate(claves):
            fila[nombre] = g["ks"][i][1]
            fila[f"__k{i}"] = g["ks"][i][0]
        for i, m in enumerate(spec["medidas"]):
            fila[infos[i]["key"]] = _calcular(g["rows"], m)
        out.append(fila)
    meta += [{"key": i["key"], "label": i["label"], "tipo": "numero", "fmt": i["fmt"]} for i in infos]
    return out, meta


def _total_general(rows: list[dict], spec: dict, dataset: str) -> tuple[list[dict], list[dict]]:
    fila = {"concepto": "Total general"}
    meta = [{"key": "concepto", "label": "Concepto", "tipo": "texto", "fmt": None}]
    for m in spec["medidas"]:
        i = medida_info(dataset, m)
        fila[i["key"]] = _calcular(rows, m) if rows or m["fn"] == "count" else 0
        meta.append({"key": i["key"], "label": i["label"], "tipo": "numero", "fmt": i["fmt"]})
    return [fila], meta


# ----------------------------- orden -----------------------------

class _Clave:
    """Ordena poniendo los vacíos siempre al final, suba o baje el orden."""

    __slots__ = ("v", "asc")

    def __init__(self, v, asc: bool):
        self.v, self.asc = v, asc

    def _vacio(self) -> bool:
        return self.v is None or (isinstance(self.v, float) and math.isnan(self.v))

    def __lt__(self, otro) -> bool:
        a, b = self._vacio(), otro._vacio()
        if a or b:
            return not a and b                       # el vacío va después
        x, y = self.v, otro.v
        if isinstance(x, (int, float)) and isinstance(y, (int, float)) and not isinstance(x, bool) and not isinstance(y, bool):
            return x < y if self.asc else y < x
        x, y = str(x), str(y)
        return x < y if self.asc else y < x

    def __eq__(self, otro) -> bool:
        return not self < otro and not otro < self


def _ordenar(rows: list[dict], claves: list[tuple]) -> list[dict]:
    return sorted(rows, key=lambda r: [_Clave(leer(r), asc) for leer, asc in claves])


def _resolver_salida(col: str, spec: dict, meta: list[dict], dataset: str) -> str | None:
    claves = [m["key"] for m in meta]
    if col in claves:
        return col
    for med in spec.get("medidas") or []:
        if med.get("col") == col:
            return medida_info(dataset, med)["key"]
    for g in spec.get("agrupar") or []:
        if g["col"] == col and (g.get("por") or "mes") in claves:
            return g.get("por") or "mes"
    if col in ("cantidad", "count"):
        return "cantidad" if "cantidad" in claves else None
    return None


# ----------------------------- textos -----------------------------

def describir(spec: dict) -> list[str]:
    out = []
    if spec.get("fecha"):
        f = spec["fecha"]
        out.append("Período: " + (f.get("etiqueta") or f"{f.get('desde')} a {f.get('hasta')}"))
    for f in spec.get("filtros") or []:
        et = catalogo.etiqueta(spec["dataset"], f["col"])
        v = f["valor"]
        if f["op"] == "entre":
            out.append(f"{et} entre {v[0]} y {v[1]}")
        elif f["op"] == "dia_semana":
            out.append("Solo " + ", ".join(DIAS_N[d] for d in v))
        elif f["op"] in ("en", "no_en"):
            out.append(f"{et} {'es' if f['op'] == 'en' else 'no es'} " + " o ".join(str(x) for x in v))
        elif f["op"] == "contiene":
            out.append(f"{et} contiene «{v}»")
        else:
            out.append(f"{et} {SIMB.get(f['op'], f['op'])} {v}")
    for g in spec.get("agrupar") or []:
        nombre = POR_ETIQUETA[g["por"]].lower() if g.get("por") else catalogo.etiqueta(spec["dataset"], g["col"]).lower()
        out.append("Agrupado por " + nombre)
    for o in spec.get("orden") or []:
        med = next((m for m in (spec.get("medidas") or []) if medida_info(spec["dataset"], m)["key"] == o["col"]), None)
        nombre = medida_info(spec["dataset"], med)["label"].lower() if med else catalogo.etiqueta(spec["dataset"], o["col"]).lower()
        out.append(f"Orden: {nombre} {'de mayor a menor' if o['dir'] == 'desc' else 'de menor a mayor'}")
    if spec.get("limite"):
        out.append(f"Primeros {spec['limite']} resultados")
    return out


def titulo_auto(spec: dict) -> str:
    ds = catalogo.DATASETS[spec["dataset"]]
    base = ds["etiqueta"]
    if spec.get("medidas") and not spec.get("agrupar"):
        base = f"Resumen de {ds['etiqueta'].lower()}"
    elif spec.get("agrupar"):
        g = spec["agrupar"][0]
        nombre = POR_ETIQUETA[g["por"]].lower() if g.get("por") else catalogo.etiqueta(spec["dataset"], g["col"]).lower()
        base = f"{ds['etiqueta']} por {nombre}"
    if spec.get("fecha") and spec["fecha"].get("etiqueta"):
        base += f" · {spec['fecha']['etiqueta']}"
    return base


def _grafico(modo: str, meta: list[dict], agr: list[dict], filas: list[dict], medidas: list[dict]) -> dict | None:
    if modo != "agrupado" or not filas:
        return None
    ncl = len(agr)
    x = meta[0]["key"]
    serie = meta[ncl:ncl + 2]
    ys = [m["key"] for m in serie]
    temporal = ncl == 1 and agr[0].get("por") in ("dia", "semana", "mes", "trimestre", "anio")
    if temporal:
        tipo = "lineas" if len(filas) > 2 else "barras"
    elif ncl == 1 and len(filas) <= 6 and len(ys) == 1 and medidas and medidas[0]["fn"] in ("sum", "count"):
        tipo = "torta"
    else:
        tipo = "barras"
    if ncl > 1:
        x = "__etiqueta"
        for f in filas:
            f[x] = " · ".join(str(f[m["key"]]) for m in meta[:ncl])
    return {"tipo": tipo, "x": x, "y": ys, "etiquetas": {m["key"]: m["label"] for m in serie}}


def _miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _resumen_texto(modo, dataset, n_filtrado, total_filas, meta, filas, totales, agr) -> list[str]:
    ds = catalogo.DATASETS[dataset]["etiqueta"].lower()
    if n_filtrado == 0:
        return ["No hay datos que cumplan estas condiciones."]
    out = [f"Se analizaron {_miles(n_filtrado)} registros de {ds}."]
    if modo == "agrupado" and filas and len(meta) > len(agr):
        m = meta[len(agr)]
        vals = [r for r in filas if r.get(m["key"]) is not None]
        if vals:
            def etiq(r):
                return " · ".join(str(r[x["key"]]) for x in meta[:len(agr)])
            mayor = max(vals, key=lambda r: num(r[m["key"]]))
            menor = min(vals, key=lambda r: num(r[m["key"]]))
            out.append(f"{len(filas)} grupos. Mayor {m['label'].lower()}: {etiq(mayor)} ({fmt_valor(mayor[m['key']], m['fmt'])}); "
                       f"menor: {etiq(menor)} ({fmt_valor(menor[m['key']], m['fmt'])}).")
    if totales:
        por = {m["key"]: m for m in meta}
        out.append("Totales: " + "; ".join(f"{por[k]['label']} {fmt_valor(v, por[k]['fmt'])}" for k, v in totales.items()) + ".")
    if total_filas > len(filas):
        out.append(f"Mostrando {len(filas)} de {total_filas} resultados.")
    return out


# ----------------------------- ejecución -----------------------------

def ejecutar(spec: dict, registros: dict[str, list[dict]]) -> dict:
    dataset = spec.get("dataset")
    if dataset not in catalogo.DATASETS:
        raise ConsultaInvalida("No sé qué datos consultar.")
    ds = catalogo.DATASETS[dataset]
    if dataset not in registros:
        raise ConsultaInvalida(f"No tienes acceso a {ds['etiqueta'].lower()} (tu rol no lo permite o el servicio no respondió).")

    rows = registros[dataset]
    if spec.get("fecha"):
        rows = _rango_fecha(rows, spec["fecha"], dataset)
    for f in spec.get("filtros") or []:
        if not f.get("post"):
            rows = _aplicar_filtro(rows, f, dataset)
    n_filtrado = len(rows)

    medidas = list(spec.get("medidas") or [])
    agr = spec.get("agrupar") or []
    notas: list[str] = []
    sp = spec
    if agr and not medidas:
        medidas = [{"fn": fn, "col": col} if col else {"fn": fn} for fn, col in ds["medida"]] or [{"fn": "count"}]
        sp = {**spec, "medidas": medidas}

    if agr:
        out, meta = _agrupar(rows, sp, dataset)
        modo = "agrupado"
    elif medidas:
        out, meta = _total_general(rows, sp, dataset)
        modo = "total"
    else:
        cols = [c for c in (spec.get("columnas") or ds["defecto"])
                if any(x["nombre"] == c for x in ds["columnas"])] or ds["defecto"]
        meta = []
        for c in cols:
            cat = catalogo.columna(dataset, c)
            meta.append({"key": c, "label": cat["etiqueta"],
                         "tipo": {"fecha": "fecha", "numero": "numero"}.get(cat["tipo"], "texto"), "fmt": cat["fmt"]})
        out, modo = rows, "detalle"

    if modo != "detalle":
        for f in spec.get("filtros") or []:
            if not f.get("post"):
                continue
            k = _resolver_salida(f["col"], sp, meta, dataset)
            if not k:
                continue
            op, val = f["op"], f["valor"]

            def pasa(r, k=k, op=op, val=val):
                v = r.get(k)
                if v is None:
                    return False
                if op == "entre":
                    a, b = num(val[0]), num(val[1])
                    return min(a, b) <= v <= max(a, b)
                x = num(val)
                return {"=": v == x, "!=": v != x, ">": v > x, ">=": v >= x, "<": v < x, "<=": v <= x}.get(op, True)
            out = [r for r in out if pasa(r)]

    claves = []
    for o in spec.get("orden") or []:
        if modo == "detalle":
            if any(c["nombre"] == o["col"] for c in ds["columnas"]):
                claves.append((lambda r, c=o["col"]: r.get(c), o["dir"] == "asc"))
            else:
                notas.append(f"No pude ordenar por «{o['col']}».")
            continue
        k = _resolver_salida(o["col"], sp, meta, dataset)
        if not k:
            notas.append(f"No pude ordenar por «{o['col']}» porque no está en el resultado.")
            continue
        idx = next((i for i, m in enumerate(meta) if m["key"] == k), -1) if modo == "agrupado" else -1
        real = f"__k{idx}" if 0 <= idx < len(agr) else k        # fechas: orden cronológico, no alfabético
        claves.append((lambda r, c=real: r.get(c), o["dir"] == "asc"))

    if claves:
        out = _ordenar(out, claves)
    elif modo == "agrupado":
        out = _ordenar(out, [(lambda r, i=i: r.get(f"__k{i}"), True) for i in range(len(agr))])
    elif modo == "detalle" and ds.get("fecha"):
        out = _ordenar(out, [(lambda r, c=ds["fecha"]: r.get(c), True)])

    total_filas = len(out)
    if spec.get("limite"):
        out = out[: int(spec["limite"])]
    filas = [{m["key"]: redondear(r.get(m["key"])) for m in meta} for r in out]

    totales = None
    if modo == "agrupado":
        t = {}
        for i, m in enumerate(meta[len(agr):]):
            if i < len(medidas) and medidas[i]["fn"] in ("sum", "count"):
                t[m["key"]] = redondear(sum(x for x in (num(r.get(m["key"])) for r in filas) if not math.isnan(x)))
        totales = t or None
    elif modo == "detalle":
        t = {m["key"]: redondear(sum(x for x in (num(r.get(m["key"])) for r in filas) if not math.isnan(x)))
             for m in meta if m["fmt"] == "moneda"}
        totales = t or None

    return {
        "titulo": spec.get("titulo") or titulo_auto(spec),
        "dataset": dataset,
        "datasetEtiqueta": ds["etiqueta"],
        "modo": modo,
        "columnas": meta,
        "filas": filas,
        "totales": totales,
        "grafico": _grafico(modo, meta, agr, filas, medidas),
        "resumen": _resumen_texto(modo, dataset, n_filtrado, total_filas, meta, filas, totales, agr),
        "condiciones": describir(spec),
        "notas": notas,
        "registrosAnalizados": n_filtrado,
        "totalFilas": total_filas,
        "mostradas": len(filas),
        "generado": datetime.now().strftime("%d/%m/%Y %H:%M"),
    }
