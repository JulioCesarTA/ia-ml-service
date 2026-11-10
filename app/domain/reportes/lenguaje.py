"""Lenguaje natural (español) -> consulta estructurada. Única implementación: la usan el portal, el BI y la app móvil.

Entiende: qué datos (reservas, pagos, estudiantes, becas, menús, insumos, desperdicio), qué columnas ver, filtros
("mayores a 5", "turno almuerzo", "sin beca"), fechas ("noviembre", "del 1 al 15 de octubre", "últimos 30 días", "2025",
"primer trimestre"), agrupaciones ("por mes", "por turno"), medidas ("total", "promedio", "cuántos"), rankings
("los 10 mayores", "los 5 más pedidos"), orden ("ascendente", "de mayor a menor") y la salida ("en pantalla", "PDF",
"Excel"). También sigue la conversación ("ahora por mes", "solo de almuerzo") y corrige errores de tipeo.

No escribe SQL ni consultas libres: solo rellena esta estructura, que el motor valida contra el catálogo (SPEC §10).
"""
import math
import re
from datetime import date, timedelta

from app.domain.reportes import catalogo, motor
from app.domain.reportes.motor import MESES_N, dmy, sin_acentos


class NoEntendido(ValueError):
    pass


MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
         "septiembre": 9, "setiembre": 9, "sept": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
MES_ALT = "|".join(sorted(MESES, key=len, reverse=True))
NUMEROS = {"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
           "once": 11, "doce": 12, "quince": 15, "veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50,
           "cien": 100, "ciento": 100}
DIAS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}
TIEMPO = {"dia": "dia", "dias": "dia", "diario": "dia", "diaria": "dia", "diariamente": "dia",
          "semana": "semana", "semanas": "semana", "semanal": "semana", "semanalmente": "semana",
          "mes": "mes", "meses": "mes", "mensual": "mes", "mensualmente": "mes",
          "trimestre": "trimestre", "trimestres": "trimestre", "trimestral": "trimestre",
          "anio": "anio", "anios": "anio", "ano": "anio", "anos": "anio", "anual": "anio", "anualmente": "anio",
          "dia de la semana": "dia_semana", "dias de la semana": "dia_semana"}
COL_NUM = {"pagos": "monto", "estudiantes": "reservas", "becas": "uso", "menus": "apartadas",
           "insumos": "stock", "desperdicio": "restante", "reservas": None}
FORMATOS = [("pdf", r"\bpdf\b"), ("excel", r"\b(excel|xlsx|xls|hoja de calculo|planilla|spreadsheet)\b"),
            ("pantalla", r"\b(en pantalla|por pantalla|en la pantalla|aqui)\b")]
SIN_PALABRA = {"media": "beca"}          # valores ambiguos: solo cuentan junto a esta palabra


# ----------------------------- texto -----------------------------

def norm(texto) -> str:
    t = sin_acentos(str(texto).lower())
    t = re.sub(r"[^a-z0-9/\-.,%$ ]", " ", t)
    # el punto y la coma solo se conservan entre dígitos (1.500 / 2,5)
    t = re.sub(r"[.,]", lambda m: m.group(0) if _entre_digitos(t, m.start()) else " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return " ".join(str(NUMEROS[w]) if w in NUMEROS else w for w in t.split(" "))


def _entre_digitos(t: str, i: int) -> bool:
    return i > 0 and t[i - 1].isdigit() and i + 1 < len(t) and t[i + 1].isdigit()


def escapar(s: str) -> str:
    return re.escape(s)


def blank(t: str, a: int, b: int) -> str:
    return t[:a] + " " * (b - a) + t[b:]


def _split_camel(n: str) -> str:
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", n)


def _re_frase(f: str) -> re.Pattern:
    return re.compile(rf"\b{escapar(f)}(?:s|es)?\b")


def frases(c: dict) -> list[str]:
    fs = {norm(_split_camel(c["nombre"])), norm(re.sub(r"\(.*?\)", "", c["etiqueta"]))}
    fs |= {norm(s) for s in c["sinonimos"]}
    return sorted((f for f in fs if f), key=len, reverse=True)


# ----------------------------- corrección de tipeos -----------------------------

def _distancia(a: str, b: str) -> int:
    """Errores entre dos palabras; cambiar de lugar dos letras seguidas ("ocutbre") cuenta como UN error."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            costo = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + costo)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len(a)][len(b)]


PARECIDO_MINIMO = 0.85        # una palabra de 7 letras con un error (0.857) ya se corrige


def _vocabulario() -> list[str]:
    v = set(MESES) | set(NUMEROS) | set(TIEMPO) | set(DIAS) | {
        "ascendente", "descendente", "promedio", "mayores", "menores", "ordenado", "ordenados", "agrupado",
        "desperdicio", "cuantos", "cuantas", "cantidad", "reporte", "mostrar", "ultimos", "ultimas", "trimestre",
        "semestre", "bolivianos", "estudiantes", "reservas", "raciones", "pagos", "becas", "menus", "insumos",
        "total", "maximo", "minimo", "ayer",
        # valores que la gente escribe (estados, métodos, turnos, tipos): sin ellos "canseladas" no se corrige
        "cancelada", "canceladas", "confirmada", "confirmadas", "consumida", "consumidas", "pendiente", "pendientes",
        "cobrado", "cobrados", "devuelto", "devueltos", "fallido", "fallidos", "efectivo", "tarjeta",
        "almuerzo", "desayuno", "completa", "parcial"}
    for ds in catalogo.DATASETS.values():
        for s in ds["sinonimos"]:
            v |= set(norm(s).split(" "))
        for c in ds["columnas"]:
            for f in frases(c):
                v |= set(f.split(" "))
    return sorted(w for w in v if len(w) >= 4)           # orden fijo: un set de Python cambia de orden entre ejecuciones


VOCAB = _vocabulario()


def corregir_tipeos(t: str) -> str:
    out = []
    for w in t.split(" "):
        if len(w) < 6 or not re.fullmatch(r"[a-z]+", w) or w in VOCAB:
            out.append(w)
            continue
        mejor, mejor_r = None, PARECIDO_MINIMO
        for v in VOCAB:
            if abs(len(v) - len(w)) > 2:
                continue
            pre = 0
            while pre < min(len(v), len(w)) and v[pre] == w[pre]:
                pre += 1
            if pre >= min(len(v), len(w)) - 2:
                continue        # solo cambia el final (reservados/reservadas): es otra palabra válida, no un error
            r = 1 - _distancia(w, v) / max(len(w), len(v))
            if r >= mejor_r:
                mejor, mejor_r = v, r
        out.append(mejor or w)
    return " ".join(out)


# ----------------------------- fechas -----------------------------

def _numero(s: str) -> float | int:
    """El número tal como lo escribió la persona: «1.500» son mil quinientos y «2,5» son dos y medio."""
    s = s.replace(" ", "")
    v = float(s.replace(".", "")) if re.fullmatch(r"\d{1,3}(\.\d{3})+", s) else float(s.replace(",", "."))
    return int(v) if v.is_integer() else v


def _rango(desde: date | None, hasta: date | None, etiqueta: str) -> dict:
    return {"desde": desde.isoformat() if desde else None, "hasta": hasta.isoformat() if hasta else None, "etiqueta": etiqueta}


def _dias_en_mes(y: int, m: int) -> int:
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day


def _fin_mes(y: int, m: int) -> date:
    return date(y, m, _dias_en_mes(y, m))


def _anio_de(mes: int, anio: int | None, hoy: date) -> int:
    if anio:
        return anio
    return hoy.year if date(hoy.year, mes, 1) <= hoy else hoy.year - 1


def _fecha_texto(d: str, m: str, y: str | None, hoy: date) -> date:
    mes = MESES[m]
    anio = _anio_de(mes, int(y) if y else None, hoy)
    return date(anio, mes, min(int(d), _dias_en_mes(anio, mes)))


def _ultimos(n: int, unidad: str, hoy: date) -> dict:
    por = 1 if unidad.startswith("dia") else 7 if unidad.startswith("semana") else 30 if unidad.startswith("mes") else 365
    dias = n * por
    etiqueta = f"los últimos {n} {unidad if n != 1 else unidad.rstrip('s')}"
    return _rango(hoy - timedelta(days=dias - 1) if dias > 1 else hoy, hoy, etiqueta)


def _proximos(n: int, unidad: str, hoy: date) -> dict:
    por = 1 if unidad.startswith("dia") else 7 if unidad.startswith("semana") else 30
    return _rango(hoy, hoy + timedelta(days=n * por), f"los próximos {n} {unidad}")


def parse_fechas(t: str, hoy: date) -> tuple[dict | None, str]:
    m = re.search(rf"\b(?:del?|entre)(?: el)? (\d{{1,2}}) (?:al?|y)(?: el)? (\d{{1,2}}) (?:de )?({MES_ALT})(?: (?:de|del) (\d{{4}}))?\b", t)
    if m:
        a, b = _fecha_texto(m[1], m[3], m[4], hoy), _fecha_texto(m[2], m[3], m[4], hoy)
        if a > b:
            a, b = b, a
        return _rango(a, b, f"del {dmy(a)} al {dmy(b)}"), blank(t, *m.span())

    # fechas explícitas
    cand: list[tuple[int, int, date]] = []
    for x in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t):
        try:
            cand.append((x.start(), x.end(), date(int(x[1]), int(x[2]), int(x[3]))))
        except ValueError:
            pass
    for x in re.finditer(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4}|\d{2})\b", t):
        y = int(x[3]) + (2000 if len(x[3]) == 2 else 0)
        try:
            cand.append((x.start(), x.end(), date(y, int(x[2]), int(x[1]))))
        except ValueError:
            pass
    for x in re.finditer(rf"\b(\d{{1,2}}) (?:de )?({MES_ALT})(?: (?:de|del) (\d{{4}}))?\b", t):
        cand.append((x.start(), x.end(), _fecha_texto(x[1], x[2], x[3], hoy)))
    if cand:
        cand.sort(key=lambda c: c[0])
        restos = t
        for a, b, _ in cand:
            restos = blank(restos, a, b)
        ds = [c[2] for c in cand]
        if len(ds) >= 2:
            return _rango(min(ds), max(ds), f"del {dmy(min(ds))} al {dmy(max(ds))}"), restos
        antes = t[max(0, cand[0][0] - 22):cand[0][0]]
        if re.search(r"(desde|a partir de|despues de)(?: el)? $", antes):
            return _rango(ds[0], hoy, f"desde el {dmy(ds[0])}"), restos
        if re.search(r"(hasta|antes de)(?: el)? $", antes):
            return _rango(None, ds[0], f"hasta el {dmy(ds[0])}"), restos
        return _rango(ds[0], ds[0], f"el {dmy(ds[0])}"), restos

    # relativas
    lunes = hoy - timedelta(days=hoy.weekday())
    mp = (hoy.year - 1, 12) if hoy.month == 1 else (hoy.year, hoy.month - 1)
    reglas = [
        (r"\bhoy\b", lambda x: _rango(hoy, hoy, f"hoy ({dmy(hoy)})")),
        (r"\banteayer\b", lambda x: _rango(hoy - timedelta(days=2), hoy - timedelta(days=2), "anteayer")),
        (r"\bayer\b", lambda x: _rango(hoy - timedelta(days=1), hoy - timedelta(days=1), f"ayer ({dmy(hoy - timedelta(days=1))})")),
        (r"\b(?:semana pasada|semana anterior)\b", lambda x: _rango(lunes - timedelta(days=7), lunes - timedelta(days=1), "la semana pasada")),
        (r"\b(?:esta semana|semana actual|en lo que va de la semana)\b", lambda x: _rango(lunes, hoy, "esta semana")),
        (r"\b(?:de la semana|la semana)\b", lambda x: None if re.search(r"dias? de la semana", t) else _rango(lunes, hoy, "esta semana")),
        (r"\b(?:mes pasado|mes anterior)\b", lambda x: _rango(date(mp[0], mp[1], 1), _fin_mes(*mp), f"el mes pasado ({MESES_N[mp[1] - 1]})")),
        (r"\b(?:este mes|mes actual|en lo que va del mes)\b", lambda x: _rango(date(hoy.year, hoy.month, 1), hoy, f"este mes ({MESES_N[hoy.month - 1]})")),
        (r"\b(?:anio pasado|ano pasado|anio anterior|ano anterior)\b", lambda x: _rango(date(hoy.year - 1, 1, 1), date(hoy.year - 1, 12, 31), f"el año {hoy.year - 1}")),
        (r"\b(?:este anio|este ano|anio actual|ano actual|en lo que va del anio|en lo que va del ano)\b", lambda x: _rango(date(hoy.year, 1, 1), hoy, f"este año ({hoy.year})")),
        (r"\bultim[oa]s? (\d+) (dias?|semanas?|meses|mes|anios?|anos?)\b", lambda x: _ultimos(int(x[1]), x[2], hoy)),
        (r"\bultima semana\b", lambda x: _ultimos(7, "dias", hoy)),
        (r"\bultimo mes\b", lambda x: _ultimos(30, "dias", hoy)),
        (r"\b(?:ultimo anio|ultimo ano)\b", lambda x: _ultimos(365, "dias", hoy)),
        (r"\bproxim[oa]s? (\d+) (dias?|semanas?|meses|mes)\b", lambda x: _proximos(int(x[1]), x[2], hoy)),
        (r"\bproxima semana\b", lambda x: _proximos(7, "dias", hoy)),
        (r"\bproximo mes\b", lambda x: _proximos(30, "dias", hoy)),
    ]
    for patron, f in reglas:
        x = re.search(patron, t)
        r = f(x) if x else None
        if r:
            return r, blank(t, *x.span())

    m = re.search(r"\b(primer|1er|segundo|2do|tercer|3er|cuarto|4to|ultimo) (trimestre|semestre)(?: (?:de|del) (\d{4}))?\b", t)
    if m:
        n = {"primer": 1, "1er": 1, "segundo": 2, "2do": 2, "tercer": 3, "3er": 3, "cuarto": 4, "4to": 4, "ultimo": 4}[m[1]]
        y = int(m[3]) if m[3] else hoy.year
        if m[2] == "trimestre":
            a, b = date(y, 3 * n - 2, 1), _fin_mes(y, 3 * n)
        else:
            n = min(n, 2)
            a, b = date(y, 6 * n - 5, 1), _fin_mes(y, 6 * n)
        return _rango(a, b, f"{m[1]} {m[2]} de {y}"), blank(t, *m.span())

    m = re.search(r"\b(?:este trimestre|trimestre actual)\b", t)
    if m:
        q = (hoy.month - 1) // 3
        return _rango(date(hoy.year, 3 * q + 1, 1), hoy, "este trimestre"), blank(t, *m.span())

    # meses
    ms = list(re.finditer(rf"\b({MES_ALT})\b(?: (?:de|del) (\d{{4}})| (\d{{4}})\b)?", t))
    if ms:
        rs, restos = [], t
        for x in ms:
            mes = MESES[x[1]]
            y = _anio_de(mes, int(x[2] or x[3]) if (x[2] or x[3]) else None, hoy)
            rs.append((date(y, mes, 1), _fin_mes(y, mes)))
            restos = blank(restos, *x.span())
        a, b = min(r[0] for r in rs), max(r[1] for r in rs)
        et = (f"{MESES_N[a.month - 1]} de {a.year}" if (a.year, a.month) == (b.year, b.month)
              else f"{MESES_N[a.month - 1]} {a.year} a {MESES_N[b.month - 1]} {b.year}")
        return _rango(a, b, et), restos

    # años
    anios = []
    for x in re.finditer(r"\b(20\d{2})\b", t):
        antes = t[max(0, x.start() - 16):x.start()]
        if re.search(r"(anios?|anos?|en|del|de|durante|desde|hasta|entre|y|al|a)\s+(el\s+)?(anio\s+|ano\s+)?$", antes):
            anios.append((x.start(), x.end(), int(x[1])))
    if anios:
        restos = t
        for a, b, _ in anios:
            restos = blank(restos, a, b)
        ys = [a[2] for a in anios]
        antes = t[max(0, anios[0][0] - 16):anios[0][0]]
        if len(ys) >= 2:
            return _rango(date(min(ys), 1, 1), date(max(ys), 12, 31), f"{min(ys)} a {max(ys)}"), restos
        if re.search(r"desde(?: el)?(?: anio| ano)? $", antes):
            return _rango(date(ys[0], 1, 1), hoy, f"desde {ys[0]}"), restos
        if re.search(r"hasta(?: el)?(?: anio| ano)? $", antes):
            return _rango(None, date(ys[0], 12, 31), f"hasta {ys[0]}"), restos
        return _rango(date(ys[0], 1, 1), date(ys[0], 12, 31), f"el año {ys[0]}"), restos
    return None, t


# ----------------------------- columnas y valores -----------------------------

def menciones(t: str, ds_id: str, tipos: list[str] | None = None) -> list[tuple[int, int, str]]:
    pares = []
    for c in catalogo.DATASETS[ds_id]["columnas"]:
        if tipos and c["tipo"] not in tipos:
            continue
        for f in frases(c):
            pares.append((f, c["nombre"]))
    pares.sort(key=lambda p: len(p[0]), reverse=True)
    work, out = t, []
    for f, nombre in pares:
        for m in list(re.finditer(rf"\b{escapar(f)}(?:s|es)?\b", work)):
            out.append((m.start(), m.end(), nombre))
            work = blank(work, m.start(), m.end())
    return sorted(out, key=lambda x: x[0])


def _col_por_raiz(ds_id: str, palabra: str) -> str | None:
    sin = re.sub(r"(es|s)$", "", palabra)
    raiz = sin[:5] if len(sin) >= 5 else sin
    if len(raiz) < 4:
        return None
    for c in catalogo.DATASETS[ds_id]["columnas"]:
        for f in frases(c):
            if f.startswith(raiz) or any(w.startswith(raiz) for w in f.split(" ")):
                return c["nombre"]
    return None


def _num_cols(ds_id: str) -> list[str]:
    return [c["nombre"] for c in catalogo.DATASETS[ds_id]["columnas"] if c["tipo"] == "numero"]


def _cercana(pos: int, ments: list[tuple], validas: list[str]) -> str | None:
    c = sorted(((abs(m[0] - pos), m[2]) for m in ments if m[2] in validas), key=lambda x: x[0])
    return c[0][1] if c else None


def _re_valor(v: str) -> re.Pattern:
    if re.search(r"[oa]$", v) and len(v) > 3:
        return re.compile(rf"\b{escapar(v[:-1])}(?:o|a|os|as)\b")
    return re.compile(rf"\b{escapar(v)}(?:s|es)?\b")


def _tiene_token(t: str, tk: str) -> bool:
    return re.search(rf"\b{escapar(tk)}\b", t) is not None


def valores(t: str, ds_id: str, rows: list[dict] | None, modo: str = "resto") -> dict:
    """Filtros por valores que existen en los datos: "almuerzo", "cobrado", "beca completa", nombres de estudiantes."""
    filtros, spans = [], []
    if rows is None:
        return {"filtros": filtros, "spans": spans}
    for c in catalogo.DATASETS[ds_id]["columnas"]:
        if c["tipo"] not in ("categoria", "texto"):
            continue
        es_nombre = c["tipo"] == "texto" and c["nombre"] != "insumo"
        if (modo == "nombres") != es_nombre:
            continue
        unicos = list({str(r[c["nombre"]]) for r in rows if r.get(c["nombre"]) is not None})
        if not unicos or len(unicos) > 600:
            continue
        hallados = []
        for v in unicos:
            nv = norm(v)
            if es_nombre:                                        # nombres de personas
                toks = [x for x in nv.split(" ") if len(x) >= 3]
                def marcar(tks):
                    for tk in tks:
                        for x in re.finditer(rf"\b{escapar(tk)}\b", t):
                            spans.append((x.start(), x.end()))
                if len(toks) >= 2:
                    usados = [tk for tk in toks if _tiene_token(t, tk)]
                    if len(usados) >= 2:
                        hallados.append((t.find(toks[0]), v, False))
                        marcar(usados)
                elif len(toks) == 1 and len(toks[0]) >= 4 and toks[0] not in VOCAB and _tiene_token(t, toks[0]):
                    hallados.append((t.find(toks[0]), v, False))
                    marcar(toks)
                continue
            variantes = {nv}
            if "/" in nv:                                        # "QR / tarjeta": también vale "qr" o "tarjeta" sola
                variantes |= {x.strip() for x in nv.split("/") if len(x.strip()) >= 2}
            for va in variantes:
                if len(va) < (3 if va == nv else 2) or (va in SIN_PALABRA and SIN_PALABRA[va] not in t):
                    continue
                m = _re_valor(va).search(t)
                if m:
                    antes = t[max(0, m.start() - 14):m.start()]
                    negado = re.search(r"\b(sin|excepto|salvo|menos|no|excluyendo)\s+(?:los |las |el |la )?$", antes) is not None
                    hallados.append((m.start(), v, negado))
                    break
        pos = [h[1] for h in hallados if not h[2]]
        neg = [h[1] for h in hallados if h[2]]
        if pos:
            filtros.append({"col": c["nombre"], "op": "=" if len(pos) == 1 else "en", "valor": pos[0] if len(pos) == 1 else pos})
        if neg:
            filtros.append({"col": c["nombre"], "op": "!=" if len(neg) == 1 else "no_en", "valor": neg[0] if len(neg) == 1 else neg})
    return {"filtros": filtros, "spans": spans}


def _frases_especiales(t: str, ds_id: str) -> dict:
    """Expresiones del negocio que equivalen a filtros: "stock bajo", "sin beca", "por vencer", "inactivos"..."""
    filtros, orden = [], []
    if ds_id == "insumos":
        if re.search(r"\b(stock bajo|bajo stock|agotad\w+|por reponer|escasos?|faltan?|faltantes)\b", t):
            filtros.append({"col": "estado", "op": "=", "valor": "Bajo"})
        if re.search(r"\bvencid\w+\b", t):
            filtros.append({"col": "diasParaVencer", "op": "<", "valor": 0})
        elif re.search(r"\b(por vencer|proximos? a vencer|a punto de vencer)\b", t) and not re.search(r"\bdias\b", t):
            filtros.append({"col": "diasParaVencer", "op": "entre", "valor": [0, 7]})
            orden.append({"col": "vence", "dir": "asc"})
    if ds_id == "estudiantes":
        if re.search(r"\bsin beca\b", t):
            filtros.append({"col": "beca", "op": "=", "valor": "Sin beca"})
        elif re.search(r"\b(con beca|becad[oa]s?|becari[oa]s?)\b", t):
            filtros.append({"col": "beca", "op": "!=", "valor": "Sin beca"})
        if re.search(r"\b(sin reservas|no reservaron|nunca reservaron)\b", t):
            filtros.append({"col": "reservas", "op": "=", "valor": 0})
    if ds_id == "becas":
        if re.search(r"\b(inactiv\w+|sin usar|sin uso|no (?:la )?(?:usan|usaron|usa)|desaprovechad\w+)\b", t):
            filtros.append({"col": "usadas", "op": "=", "valor": 0})
        if re.search(r"\b(no vigentes?|vencidas?|expiradas?)\b", t):
            filtros.append({"col": "vigente", "op": "=", "valor": "No"})
        elif re.search(r"\b(vigentes?|activas?|activos?)\b", t):
            filtros.append({"col": "vigente", "op": "=", "valor": "Sí"})
    return {"filtros": filtros, "orden": orden}


# ----------------------------- detección del conjunto de datos -----------------------------

def detectar_dataset(t: str) -> dict:
    compartidas: dict[str, int] = {}
    for ds in catalogo.DATASETS.values():
        for c in ds["columnas"]:
            compartidas[c["nombre"]] = compartidas.get(c["nombre"], 0) + 1
    puntaje = {}
    for ident, ds in catalogo.DATASETS.items():
        s, usadas = 0.0, set()
        for i, syn in enumerate(ds["sinonimos"]):
            fam = re.sub(r"(es|s)$", "", norm(syn))
            if fam not in usadas and _re_frase(norm(syn)).search(t):
                s += 3 if i < 3 else 2
                usadas.add(fam)
                if re.search(rf"\b(?:de|del)(?: los| las| el| la)? {escapar(norm(syn))}", t):
                    s += 2                       # "de los pagos": ahí está el tema
        for r in ds.get("raices") or []:
            if re.search(rf"\b{r}\w*", t):
                s += 3
        for c in ds["columnas"]:
            if any(_re_frase(f).search(t) for f in frases(c)):
                s += 0.5 if compartidas[c["nombre"]] > 1 else 1.5
        puntaje[ident] = s
    orden = sorted(puntaje.items(), key=lambda kv: kv[1], reverse=True)
    mejor, s = orden[0]
    if s >= 1.5:
        return {"id": mejor, "score": s, "ranking": orden[:3]}

    # respaldo: parecido de palabras (TF-IDF simplificado)
    ids = list(catalogo.DATASETS)
    docs = [norm(f"{d['etiqueta']} {d['descripcion']} {d['palabras_clave']}").split(" ") for d in catalogo.DATASETS.values()]
    df: dict[str, int] = {}
    for d in docs:
        for w in set(d):
            df[w] = df.get(w, 0) + 1

    def idf(w):
        return math.log((1 + len(docs)) / (1 + df.get(w, 0))) + 1

    def vec(ws):
        v: dict[str, float] = {}
        for w in ws:
            v[w] = v.get(w, 0) + idf(w)
        return v

    def coseno(a, b):
        p = sum(va * b[k] for k, va in a.items() if k in b)
        na = math.sqrt(sum(x * x for x in a.values()))
        nb = math.sqrt(sum(x * x for x in b.values()))
        return p / (na * nb) if na and nb else 0.0

    q = vec([w for w in t.split(" ") if len(w) > 2])
    sims = [coseno(q, vec(d)) for d in docs]
    i = sims.index(max(sims)) if sims else 0
    if sims and sims[i] >= 0.12:
        return {"id": ids[i], "score": sims[i] * 10, "ranking": orden[:3]}
    return {"id": None, "score": s, "ranking": orden[:3]}


# ----------------------------- lectura de una petición -----------------------------

PATRONES_COMP = [
    (r"\b(?:mayor(?:es)?|superior(?:es)?|mas|por encima|superen|supera|excedan?)\s+(?:de|a|que|del)?\s*(?:bs\.? ?|\$)?(\d+(?:[.,]\d+)?)\b(?! (?:mayores|menores))", ">"),
    (r"\b(?:al menos|como minimo|minimo de|no menos de|a partir de)\s+(?:bs\.? ?)?(\d+(?:[.,]\d+)?)\b", ">="),
    (r"\b(?:menor(?:es)?|inferior(?:es)?|menos|por debajo)\s+(?:de|a|que|del)\s*(?:bs\.? ?|\$)?(\d+(?:[.,]\d+)?)\b", "<"),
    (r"\b(?:como maximo|maximo de|a lo sumo|no mas de)\s+(?:bs\.? ?)?(\d+(?:[.,]\d+)?)\b", "<="),
    (r"\b(?:igual a|exactamente|justo)\s+(?:bs\.? ?)?(\d+(?:[.,]\d+)?)\b", "="),
    (r"\bde (\d+(?:[.,]\d+)?) (?:bs|bolivianos)\b", "="),
]


def _leer(t0: str, ds_id: str, rows: list[dict] | None, hoy: date) -> dict:
    ds = catalogo.DATASETS[ds_id]
    t = t0
    p: dict = {}
    for nombre, patron in FORMATOS:
        m = re.search(patron, t)
        if m:
            p["salida"] = nombre
            t = blank(t, *m.span())
            break

    nombres = valores(t, ds_id, rows, "nombres")        # "admin julio" es una persona, no el mes de julio
    for a, b in nombres["spans"]:
        t = blank(t, a, b)
    f, t = parse_fechas(t, hoy)
    if f:
        p["fecha"] = f
    if re.search(r"\b(todas las fechas|sin fecha|todo el historial|todo el tiempo|historico)\b", t):
        p["quitar_fecha"] = True

    direccion = None
    for patron, d in [(r"\bde mayor a menor\b", "desc"), (r"\bde menor a mayor\b", "asc"),
                      (r"\b(descendente|descendentemente|decreciente|de z a a)\b", "desc"),
                      (r"\b(ascendente|ascendentemente|creciente|de a a z)\b", "asc")]:
        m = re.search(patron, t)
        if m:
            direccion = d
            t = blank(t, *m.span())
            break

    # comparaciones numéricas ("mayores a 5" no es "los mayores")
    ments_num = menciones(t, ds_id, ["numero"])
    filtros: list[dict] = []
    consumidos: list[tuple] = []
    m = re.search(r"\bentre (?:bs\.? ?)?(\d+(?:[.,]\d+)?) y (?:bs\.? ?)?(\d+(?:[.,]\d+)?)\b", t)
    if m:
        consumidos.append((m.span(), "entre", [_numero(m[1]), _numero(m[2])]))
    for patron, op in PATRONES_COMP:
        for x in re.finditer(patron, t):
            if any(s <= x.start() < e for (s, e), _, _ in consumidos):
                continue
            consumidos.append((x.span(), op, _numero(x[1])))
    consumidos.sort(key=lambda c: c[0][0])
    for (a, b), op, val in consumidos:
        col = _cercana(a, ments_num, _num_cols(ds_id)) or COL_NUM.get(ds_id) or (_num_cols(ds_id) or [None])[0]
        antes = t[max(0, a - 30):a]
        post = bool(re.search(r"\b(con|que tengan|que sumen|que superen|cuyo|cuyos|donde el|total|promedio|cantidad)\b", antes)) and col is not None
        if col:
            filtros.append({"col": col, "op": op, "valor": val, **({"post": True} if post else {})})
        t = blank(t, a, b)

    esp = _frases_especiales(t, ds_id)
    filtros += esp["filtros"] + nombres["filtros"] + valores(t, ds_id, rows)["filtros"]
    dias = sorted({i for d, i in DIAS.items() if re.search(rf"\b(?:los |solo los |solo )?{d}s?\b", t)})
    if dias and ds.get("fecha"):
        filtros.append({"col": ds["fecha"], "op": "dia_semana", "valor": dias})

    # orden explícito: "ordenado por X ascendente"
    orden: list[dict] = []
    limite = None
    m = re.search(r"\b(?:ordenad[oa]s?|ordena(?:r|lo|los|las)?|orden|clasificad[oa]s?)\s+(?:de forma |en forma )?(?:por|segun)\s+(.+)", t)
    if m:
        cols = [x[2] for x in menciones(m[1], ds_id)]
        if re.search(r"\b(total|cantidad|suma|promedio)\b", m[1]) and not cols:
            cols.append("__medida__")
        orden = [{"col": c, "dir": direccion or "asc"} for c in cols[:3]]
        t = blank(t, *m.span())
    else:
        m = re.search(r"\bpor\s+(.+?)\s+(?:de forma\s+)?(asc|desc)\w*", t)
        if m:
            cols = [x[2] for x in menciones(m[1], ds_id)]
            if cols:
                orden = [{"col": cols[0], "dir": "desc" if m[2] == "desc" else "asc"}]
                t = blank(t, *m.span())
    if not orden:
        orden = list(esp["orden"])

    # rankings: "los 10 mayores", "los 5 más pedidos", "el mayor"
    t_ent = t                   # antes de borrar el ranking: ahí aparece la entidad ("los 5 platos más...")
    rank_col, hubo = None, False
    ranking = [
        (r"\b(?:los |las )?(?:top |ranking )?(\d+)(?: \w+){0,2}? (?:mayor(?:es)?|mejor(?:es)?|principal(?:es)?|mas altos?|mas caros?|maximos?)\b", "desc", 0),
        (r"\b(?:los |las )?(\d+)(?: \w+){0,2}? (?:menor(?:es)?|peor(?:es)?|mas bajos?|mas baratos?|minimos?)\b", "asc", 0),
        (r"\b(?:los |las )?(\d+)(?: \w+){0,2}? (?:con |que )?mas (\w+)", "desc", 2),
        (r"\b(?:los |las )?(\d+)(?: \w+){0,2}? (?:con |que )?menos (\w+)", "asc", 2),
        (r"\b(?:los |las )?(?:top|ranking) (\d+)\b", "desc", 0),
        (r"\b(?:los |las )?(\d+) primer[oa]s\b|\bprimer[oa]s (\d+)\b", "first", 0),
        (r"\b(?:los |las )?(\d+) ultim[oa]s\b", "last", 0),
    ]
    for patron, d, g in ranking:
        m = re.search(patron, t)
        if not m:
            continue
        limite = int(next(x for x in m.groups() if x and x.isdigit()))
        hubo = True
        if d in ("desc", "asc"):
            direccion = direccion or d
            if g:
                rank_col = _col_por_raiz(ds_id, m[g])
        elif d == "last" and ds.get("fecha") and not orden:
            orden = [{"col": ds["fecha"], "dir": "desc"}]
        t = blank(t, *m.span())
        break

    if not hubo:
        m = re.search(r"\bel (mayor|mejor|maximo|mas alto|mas caro|menor|peor|minimo|mas bajo|mas barato)\b", t)
        if m:
            limite, hubo = 1, True
            direccion = direccion or ("desc" if m[1] in ("mayor", "mejor", "maximo", "mas alto", "mas caro") else "asc")
            t = blank(t, *m.span())
    if not hubo:
        for patron, d in [(r"\b(?:los |las )?(?:mayor(?:es)?|mas altos?|mas caros?|mejores)\b", "desc"),
                          (r"\b(?:los |las )?(?:menor(?:es)?|mas bajos?|mas baratos?|peores)\b", "asc")]:
            m = re.search(patron, t)
            if m:
                direccion = direccion or d
                t = blank(t, *m.span())
                break
        m = re.search(r"\b(?:con )?(mas|menos) (\w+)(?: (\w+))?\b", t)
        cr = ((_col_por_raiz(ds_id, m[3]) if m and m[3] else None) or (_col_por_raiz(ds_id, m[2]) if m else None)) if m else None
        if cr:
            rank_col = cr
            direccion = direccion or ("desc" if m[1] == "mas" else "asc")
            t = blank(t, *m.span())
    if limite is None:
        m = re.search(r"\b(?:solo |maximo |hasta |limitar a |limite de )?(\d+) (?:registros|filas|resultados|renglones)\b|\b(?:limite|limitar a) (\d+)\b", t)
        if m:
            limite = int(m[1] or m[2])
            t = blank(t, *m.span())

    # agrupación
    agrupar: list[dict] = []
    m = re.search(r"\b(?:agrupad[oa]s?|agrupa(?:r|do)?|desglosad[oa]s?|separad[oa]s?|segmentad[oa]s?)?\s*(?:por|segun|cada)\s+(?:cada\s+)?"
                  r"(dia de la semana|dias de la semana|dia|dias|semana|semanas|mes|meses|trimestre|trimestres|anio|anios|ano|anos)\b", t)
    if m and ds.get("fecha"):
        agrupar.append({"col": ds["fecha"], "por": TIEMPO[m[1]]})
        t = blank(t, *m.span())
    for x in list(re.finditer(r"\b(mensual(?:mente)?|diari[oa](?:mente)?|semanal(?:mente)?|anual(?:mente)?|trimestral)\b", t)):
        base = re.sub(r"(mente)$", "", x[1])
        clave = {"mensual": "mes", "diario": "dia", "diaria": "dia", "semanal": "semana", "anual": "anio", "trimestral": "trimestre"}.get(base)
        if not agrupar and ds.get("fecha") and clave:
            agrupar.append({"col": ds["fecha"], "por": clave})
        t = blank(t, *x.span())
    for x in list(re.finditer(r"\b(?:de |para )?cada\s+(\w+)", t)):
        if x[1] in TIEMPO and not agrupar and ds.get("fecha"):
            agrupar.append({"col": ds["fecha"], "por": TIEMPO[x[1]]})
            t = blank(t, *x.span())
    for x in list(re.finditer(r"\b(?:agrupad[oa]s?\s+por|desglosad[oa]s?\s+por|por|para cada|de cada|segun|cada)\s+(?:cada\s+)?([a-z ]{3,40})", t)):
        mm = menciones(x[1], ds_id)
        if not mm:
            continue
        c = catalogo.columna(ds_id, mm[0][2])
        if c["tipo"] in ("categoria", "texto") and not any(g["col"] == mm[0][2] for g in agrupar):
            agrupar.append({"col": mm[0][2]})
        elif c["tipo"] == "fecha" and not agrupar:
            agrupar.append({"col": mm[0][2], "por": "dia"})

    # medidas
    medidas: list[dict] = []
    cuantos = bool(re.search(r"\b(cuant[oa]s?|cantidad|numero de|conteo|contar|cuenta)\b", t))
    for patron, fn in [(r"\b(promedio|media|promedi\w+)\b", "avg"), (r"\b(maximo|pico|valor mas alto)\b", "max"),
                       (r"\b(minimo|valor mas bajo)\b", "min"),
                       (r"\b(suma|sumatoria|sumar|total|totales|acumulado|recaud\w+|ingres\w+|cobrad\w+ en total|gastad\w+)\b", "sum")]:
        m = re.search(patron, t)
        if not m:
            continue
        col = _cercana(m.start(), menciones(t, ds_id, ["numero"]), _num_cols(ds_id)) or COL_NUM.get(ds_id)
        if fn == "sum" and not col:
            medidas.append({"fn": "count"})
        elif col:
            medidas.append({"fn": fn, "col": col})
        break
    if cuantos and not any(x["fn"] == "count" for x in medidas):
        if not medidas or re.search(r"\b(cuant[oa]s?|cantidad de|numero de)\b", t):
            medidas.append({"fn": "count"})
    if re.search(r"\b(distint[oa]s|diferentes|unic[oa]s)\b", t) and cuantos:
        ms = menciones(t, ds_id, ["texto", "categoria"])
        if ms:
            medidas = [{"fn": "nunique", "col": ms[0][2]}]

    # ranking sobre una entidad: "los 5 platos más reservados" => agrupar por plato
    if (hubo or rank_col) and not agrupar:
        subj = {norm(s) for s in ds["sinonimos"]}
        for _, _, n in menciones(t_ent, ds_id, ["categoria", "texto"]):
            fr = frases(catalogo.columna(ds_id, n))
            es_sujeto = any(x in subj for x in fr) and ds_id not in ("reservas", "pagos", "menus", "desperdicio")
            if not es_sujeto and not (ds_id == "estudiantes" and n in ("nombre", "matricula", "email", "telefono")):
                agrupar.append({"col": n})
                break
    if agrupar and not medidas and rank_col and catalogo.columna(ds_id, rank_col)["tipo"] == "numero":
        fn = "avg" if catalogo.columna(ds_id, rank_col)["fmt"] == "porcentaje" else "sum"
        medidas = [{"fn": fn, "col": rank_col}]

    # orden por defecto de un ranking
    if direccion and not orden:
        if agrupar or medidas:
            orden = [{"col": "__medida__", "dir": direccion}]
        else:
            col = rank_col or COL_NUM.get(ds_id)
            if col:
                orden = [{"col": col, "dir": direccion}]
    elif direccion and orden:
        for o in orden:
            if o["dir"] == "asc" and direccion != "asc":
                o["dir"] = direccion

    # columnas visibles (solo si no se agrupa)
    pide = bool(re.search(r"\b(ver|mostrar|muestra|muestrame|mostrame|dame|listar|lista|listame|columnas|campos|atributos|incluye|incluir)\b", t0))
    def base(w):
        return re.sub(r"(es|s)$", "", w)
    tema = {base(norm(x)) for x in ds["sinonimos"]}
    cols = list(dict.fromkeys(x[2] for x in menciones(t, ds_id) if base(t[x[0]:x[1]]) not in tema))
    if pide and cols and not agrupar and not medidas:
        solo = bool(re.search(r"\b(solo|solamente|unicamente)\b", t0))
        if len(cols) >= 2 or solo:
            p["columnas"] = cols
        else:
            p["columnas"] = ds["defecto"] if cols[0] in ds["defecto"] else [*ds["defecto"], *cols]

    p.update({"filtros": filtros, "agrupar": agrupar, "medidas": medidas, "orden": orden, "limite": limite, "direccion": direccion})
    return p


# ----------------------------- interpretación completa -----------------------------

def _resolver_medida_orden(spec: dict) -> dict:
    if not any(o["col"] == "__medida__" for o in spec.get("orden") or []):
        return spec
    med = (spec.get("medidas") or [None])[0]
    if not med and spec.get("agrupar"):
        d = catalogo.DATASETS[spec["dataset"]]["medida"]
        med = ({"fn": d[0][0], "col": d[0][1]} if d[0][1] else {"fn": d[0][0]}) if d else {"fn": "count"}
    if med:
        key = motor.medida_info(spec["dataset"], med)["key"]
        for o in spec["orden"]:
            if o["col"] == "__medida__":
                o["col"] = key
    else:
        spec["orden"] = [o for o in spec["orden"] if o["col"] != "__medida__"]
    return spec


def _es_refinamiento(t: str) -> bool:
    return bool(re.match(r"^(ahora|ademas|tambien|y |pero|mejor|solo|solamente|quitale|quita|agregale|agrega|ponle|pon |"
                         r"cambialo|cambia|ordenalo|ordena|filtralo|filtra|agrupalo|agrupa|muestrame tambien|que sea|en vez|en lugar)", t))


def _misma_clase(op: str) -> bool:
    return op in ("=", "en", "!=", "no_en")


def entendido(spec: dict) -> str:
    ds = catalogo.DATASETS[spec["dataset"]]
    partes = [f"Quieres ver {ds['etiqueta'].lower()}"]
    if spec.get("medidas"):
        partes.append("calculando " + " y ".join(motor.medida_info(spec["dataset"], m)["label"].lower() for m in spec["medidas"]))
    elif spec.get("columnas"):
        partes.append("con " + ", ".join(catalogo.columna(spec["dataset"], c)["etiqueta"].lower() for c in spec["columnas"]))
    cond = motor.describir(spec)
    if cond:
        partes.append("(" + "; ".join(cond) + ")")
    salida = {"pantalla": "en pantalla", "pdf": "en PDF", "excel": "en Excel"}.get(spec.get("salida") or "pantalla", "en pantalla")
    return f"{' '.join(partes)}, {salida}."


def interpretar(texto: str, previa: dict | None = None, hoy: date | None = None,
                registros: dict[str, list[dict]] | None = None) -> dict:
    """texto -> {spec, entendi, notas, confianza}. `previa` es la consulta anterior, para continuar la conversación."""
    hoy = hoy or date.today()
    t0 = corregir_tipeos(norm(texto))
    if not t0:
        raise NoEntendido("Escribe o di qué reporte quieres.")
    if re.search(r"\b(nuevo reporte|otro reporte|desde cero|empezar de nuevo|reiniciar)\b", t0):
        previa = None
    det = detectar_dataset(t0)
    ds_id, refina = det["id"], False
    if previa and previa.get("dataset") in catalogo.DATASETS and (
            ds_id is None or det["score"] < 1.5 or (ds_id == previa["dataset"] and _es_refinamiento(t0))):
        ds_id, refina = previa["dataset"], True
    if ds_id is None:
        raise NoEntendido("No entendí qué datos quieres ver. Prueba con: «pagos de noviembre por mes», "
                          "«estudiantes con beca» o «insumos con stock bajo».")
    rows = (registros or {}).get(ds_id)
    p = _leer(t0, ds_id, rows, hoy)

    import copy
    spec = copy.deepcopy(previa) if refina else {"dataset": ds_id, "columnas": None, "fecha": None, "filtros": [],
                                                 "agrupar": [], "medidas": [], "orden": [], "limite": None, "salida": "pantalla"}
    spec["dataset"] = ds_id
    if re.search(r"\b(sin filtros|quita(?:le)? los filtros|borra los filtros)\b", t0):
        spec["filtros"] = []
    if re.search(r"\b(sin agrupar|quita(?:le)? la agrupacion|en detalle|sin agrupacion)\b", t0):
        spec["agrupar"], spec["medidas"] = [], []
    if re.search(r"\bsin limite\b|\btodos los registros\b", t0):
        spec["limite"] = None
    if p.get("quitar_fecha"):
        spec["fecha"] = None
    if p.get("fecha"):
        spec["fecha"] = p["fecha"]
    for f in p["filtros"]:                       # un filtro nuevo reemplaza al anterior de esa columna
        spec["filtros"] = [x for x in spec["filtros"] if not (x["col"] == f["col"] and _misma_clase(x["op"]) == _misma_clase(f["op"]))]
        spec["filtros"].append(f)
    if p["agrupar"]:
        spec["agrupar"] = p["agrupar"]
    if p["medidas"]:
        spec["medidas"] = p["medidas"]
    if p["orden"]:
        spec["orden"] = p["orden"]
    elif p.get("direccion") and (spec["agrupar"] or spec["medidas"]):
        spec["orden"] = [{"col": "__medida__", "dir": p["direccion"]}]
    if p.get("limite"):
        spec["limite"] = p["limite"]
    if p.get("salida"):
        spec["salida"] = p["salida"]
    elif not refina:
        spec["salida"] = "pantalla"
    if p.get("columnas"):
        spec["columnas"] = p["columnas"]
    if spec["agrupar"] or spec["medidas"]:
        spec["columnas"] = None
    _resolver_medida_orden(spec)

    notas = []
    if not spec.get("fecha") and catalogo.DATASETS[ds_id].get("fecha"):
        notas.append("No indicaste un período: se consideran todos los registros.")
    if any(g.get("por") for g in p["agrupar"]) and not catalogo.DATASETS[ds_id].get("fecha"):
        notas.append("Estos datos no tienen fechas para agrupar por tiempo.")
    return {
        "spec": spec,
        "entendi": entendido(spec),
        "notas": notas,
        "confianza": round(min(1.0, (3 if refina else det["score"]) / 4) * 100) / 100,
        "continuacion": refina,
        "alternativas": [d for d, s in det["ranking"][1:] if s >= 1.5],
    }
