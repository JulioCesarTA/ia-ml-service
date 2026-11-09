"""Generador de reportes: el intérprete de español y el motor de consultas (sin red ni bases de datos)."""
from datetime import date

import pytest

from app.services.reportes import lenguaje, motor

HOY = date(2026, 11, 8)      # domingo

PAGOS = [
    {"fecha": "2026-11-02", "estudiante": "Ana Rojas", "monto": 12.0, "metodo": "Efectivo", "estado": "Cobrado", "reserva": "r1", "ticket": "t1"},
    {"fecha": "2026-11-03", "estudiante": "Beto Vaca", "monto": 6.0, "metodo": "QR / tarjeta", "estado": "Cobrado", "reserva": "r2", "ticket": "t2"},
    {"fecha": "2026-11-03", "estudiante": "Ana Rojas", "monto": 10.0, "metodo": "QR / tarjeta", "estado": "Devuelto", "reserva": "r3", "ticket": "t3"},
    {"fecha": "2026-10-20", "estudiante": "Carla Peña", "monto": 20.0, "metodo": "Efectivo", "estado": "Cobrado", "reserva": "r4", "ticket": "t4"},
    {"fecha": "2025-06-15", "estudiante": "Ana Rojas", "monto": 100.0, "metodo": "Beca", "estado": "Cobrado", "reserva": "r5", "ticket": "t5"},
]
MENUS = [
    {"fecha": "2026-11-02", "turno": "Almuerzo", "plato": "asado", "cupo": 50, "apartadas": 40, "disponibles": 10, "ocupacion": 80.0},
    {"fecha": "2026-11-03", "turno": "Almuerzo", "plato": "locro", "cupo": 50, "apartadas": 5, "disponibles": 45, "ocupacion": 10.0},
    {"fecha": "2026-11-03", "turno": "Cena", "plato": "asado", "cupo": 30, "apartadas": 25, "disponibles": 5, "ocupacion": 83.3},
]
INSUMOS = [
    {"insumo": "ARROZ", "unidad": "kg", "stock": 50.0, "minimo": 5.0, "estado": "Normal", "lotes": 1, "vence": "2026-11-09", "diasParaVencer": 1},
    {"insumo": "SAL", "unidad": "kg", "stock": 0.0, "minimo": 1.0, "estado": "Bajo", "lotes": 0, "vence": None, "diasParaVencer": None},
]
ESTUDIANTES = [
    {"matricula": "220567", "nombre": "Ana Rojas", "email": "a@uagrm.edu.bo", "telefono": "", "beca": "Completa", "reservas": 9, "pagado": 112.0},
    {"matricula": "220268", "nombre": "Beto Vaca", "email": "b@uagrm.edu.bo", "telefono": "", "beca": "Sin beca", "reservas": 2, "pagado": 6.0},
    {"matricula": "220999", "nombre": "Carla Peña", "email": "c@uagrm.edu.bo", "telefono": "", "beca": "Sin beca", "reservas": 0, "pagado": 20.0},
]
DATOS = {"pagos": PAGOS, "menus": MENUS, "insumos": INSUMOS, "estudiantes": ESTUDIANTES}


def pedir(texto, previa=None):
    r = lenguaje.interpretar(texto, previa=previa, hoy=HOY, registros=DATOS)
    return r, motor.ejecutar(r["spec"], DATOS)


# ----------------------------- qué datos quiere -----------------------------

@pytest.mark.parametrize("texto,esperado", [
    ("total cobrado por mes", "pagos"),
    ("cuántas raciones se reservaron", "reservas"),
    ("estudiantes con beca", "estudiantes"),
    ("insumos con stock bajo", "insumos"),
    ("platos más pedidos", "menus"),
    ("desperdicio promedio por plato", "desperdicio"),
    ("becas sin usar", "becas"),
])
def test_detecta_el_conjunto_de_datos(texto, esperado):
    assert lenguaje.detectar_dataset(lenguaje.norm(texto))["id"] == esperado


def test_un_texto_vacio_se_rechaza():
    with pytest.raises(lenguaje.NoEntendido):
        lenguaje.interpretar("   ", hoy=HOY, registros=DATOS)


def test_un_texto_sin_sentido_adivina_y_avisa_con_poca_confianza():
    """No lanza error: elige lo más parecido (respaldo TF-IDF) pero con confianza baja, para que la pantalla lo muestre."""
    r = lenguaje.interpretar("hola qué tal", hoy=HOY, registros=DATOS)
    assert r["spec"]["dataset"] in lenguaje.catalogo.DATASETS
    claro = lenguaje.interpretar("total cobrado por mes", hoy=HOY, registros=DATOS)
    assert r["confianza"] <= 0.5 < claro["confianza"]


# ----------------------------- fechas -----------------------------

@pytest.mark.parametrize("texto,desde,hasta", [
    ("pagos de hoy", "2026-11-08", "2026-11-08"),
    ("pagos de ayer", "2026-11-07", "2026-11-07"),
    ("pagos de noviembre", "2026-11-01", "2026-11-30"),
    ("pagos de este mes", "2026-11-01", "2026-11-08"),
    ("pagos del mes pasado", "2026-10-01", "2026-10-31"),
    ("pagos de 2025", "2025-01-01", "2025-12-31"),
    ("pagos de los últimos 7 días", "2026-11-02", "2026-11-08"),
    ("pagos del 1 al 15 de octubre", "2026-10-01", "2026-10-15"),
    ("pagos del primer trimestre de 2026", "2026-01-01", "2026-03-31"),
    ("pagos desde 2024", "2024-01-01", "2026-11-08"),
])
def test_entiende_los_periodos(texto, desde, hasta):
    r, _ = pedir(texto)
    assert (r["spec"]["fecha"]["desde"], r["spec"]["fecha"]["hasta"]) == (desde, hasta)


def test_el_periodo_filtra_de_verdad():
    _, res = pedir("pagos de 2025")
    assert res["registrosAnalizados"] == 1 and res["filas"][0]["monto"] == 100.0


# ----------------------------- filtros -----------------------------

def test_filtra_por_un_valor_que_existe_en_los_datos():
    r, res = pedir("pagos en efectivo")
    assert {"col": "metodo", "op": "=", "valor": "Efectivo"} in r["spec"]["filtros"]
    assert res["registrosAnalizados"] == 2


def test_filtra_por_comparacion_numerica():
    r, res = pedir("pagos mayores a 10 bolivianos")
    assert {"col": "monto", "op": ">", "valor": 10.0} in r["spec"]["filtros"]
    assert sorted(f["monto"] for f in res["filas"]) == [12.0, 20.0, 100.0]


def test_filtra_entre_dos_numeros():
    _, res = pedir("pagos entre 10 y 20 bolivianos")
    assert sorted(f["monto"] for f in res["filas"]) == [10.0, 12.0, 20.0]


def test_la_negacion_excluye():
    r, res = pedir("pagos sin efectivo")
    assert {"col": "metodo", "op": "!=", "valor": "Efectivo"} in r["spec"]["filtros"]
    assert res["registrosAnalizados"] == 3


def test_frases_del_negocio_valen_como_filtro():
    r, res = pedir("insumos con stock bajo")
    assert {"col": "estado", "op": "=", "valor": "Bajo"} in r["spec"]["filtros"]
    assert [f["insumo"] for f in res["filas"]] == ["SAL"]
    r2, res2 = pedir("estudiantes sin beca")
    assert {"col": "beca", "op": "=", "valor": "Sin beca"} in r2["spec"]["filtros"]
    assert res2["registrosAnalizados"] == 2


def test_busca_por_nombre_de_persona():
    _, res = pedir("pagos de Carla Peña")
    assert res["registrosAnalizados"] == 1 and res["filas"][0]["monto"] == 20.0


# ----------------------------- agrupación y medidas -----------------------------

def test_agrupa_por_mes_y_suma():
    r, res = pedir("total cobrado por mes")
    assert r["spec"]["agrupar"] == [{"col": "fecha", "por": "mes"}]
    assert {"fn": "sum", "col": "monto"} in r["spec"]["medidas"]
    porMes = {f["mes"]: f["total_monto"] for f in res["filas"]}
    assert porMes == {"Jun 2025": 100.0, "Oct 2026": 20.0, "Nov 2026": 18.0}      # «cobrado» excluye el devuelto
    assert res["totales"]["total_monto"] == 138.0
    assert res["grafico"]["tipo"] == "lineas"


def test_agrupa_por_categoria():
    _, res = pedir("pagos por método de pago")
    assert {f["metodo"] for f in res["filas"]} == {"Efectivo", "QR / tarjeta", "Beca"}


def test_cuantos_cuenta_registros():
    r, res = pedir("cuántos pagos hay por método")
    assert {"fn": "count"} in r["spec"]["medidas"]
    assert sum(f["cantidad"] for f in res["filas"]) == 5


def test_promedio():
    _, res = pedir("promedio de ocupación por plato")
    porPlato = {f["plato"]: f["promedio_ocupacion"] for f in res["filas"]}
    assert porPlato["asado"] == pytest.approx(81.65, abs=0.01)


def test_sin_agrupar_da_el_total_general():
    _, res = pedir("total recaudado")            # «recaudado» no filtra por estado: suma los 5 pagos
    assert res["modo"] == "total" and res["filas"][0]["total_monto"] == 148.0


# ----------------------------- rankings y orden -----------------------------

def test_ranking_de_los_mayores():
    r, res = pedir("los 2 pagos más altos")
    assert r["spec"]["limite"] == 2
    assert [f["monto"] for f in res["filas"]] == [100.0, 20.0]


def test_ranking_sobre_una_entidad_agrupa_por_ella():
    r, res = pedir("los 5 platos más pedidos")
    assert r["spec"]["agrupar"] == [{"col": "plato"}]
    assert res["filas"][0]["plato"] == "asado" and res["filas"][0]["total_apartadas"] == 65


def test_orden_explicito():
    _, res = pedir("pagos ordenados por monto descendente")
    assert [f["monto"] for f in res["filas"]] == [100.0, 20.0, 12.0, 10.0, 6.0]
    _, res2 = pedir("estudiantes ordenados por nombre")
    assert [f["nombre"] for f in res2["filas"]] == ["Ana Rojas", "Beto Vaca", "Carla Peña"]


def test_los_vacios_quedan_al_final_en_los_dos_sentidos():
    _, asc = pedir("insumos ordenados por días para vencer ascendente")
    _, desc = pedir("insumos ordenados por días para vencer descendente")
    assert asc["filas"][-1]["insumo"] == "SAL" and desc["filas"][-1]["insumo"] == "SAL"


# ----------------------------- columnas, salida y conversación -----------------------------

def test_elige_las_columnas_pedidas():
    r, res = pedir("muéstrame solo fecha y monto de los pagos")
    assert [c["key"] for c in res["columnas"]] == ["fecha", "monto"]


def test_reconoce_el_formato_de_salida():
    # solo pantalla, PDF y Excel: el CSV ya no es un formato y el reporte sale en pantalla
    for texto, salida in [("pagos en pdf", "pdf"), ("pagos en excel", "excel"), ("pagos en csv", "pantalla")]:
        r, _ = pedir(texto)
        assert r["spec"]["salida"] == salida


def test_sigue_la_conversacion():
    r1, _ = pedir("pagos de noviembre")
    r2, res2 = pedir("ahora por mes", previa=r1["spec"])
    assert r2["continuacion"] is True and r2["spec"]["dataset"] == "pagos"
    assert r2["spec"]["agrupar"] == [{"col": "fecha", "por": "mes"}]
    assert r2["spec"]["fecha"]["desde"] == "2026-11-01"           # conserva el período anterior
    r3, _ = pedir("quítale los filtros", previa=r2["spec"])
    assert r3["spec"]["filtros"] == []


def test_corrige_errores_de_tipeo():
    assert "noviembre" in lenguaje.corregir_tipeos(lenguaje.norm("pagos de nobiembre"))
    assert "estudiantes" in lenguaje.corregir_tipeos(lenguaje.norm("estudianres con beca"))
    # una palabra que solo cambia al final es otra palabra válida, no un error: no se toca
    assert lenguaje.corregir_tipeos("reservados") == "reservados"


# ----------------------------- resultado -----------------------------

def test_el_resultado_trae_todo_lo_que_la_pantalla_necesita():
    r, res = pedir("total cobrado por mes en 2026")
    assert res["titulo"] and res["datasetEtiqueta"] == "Pagos y recaudación"
    assert [c["key"] for c in res["columnas"]] == ["mes", "total_monto"]
    assert res["grafico"]["x"] == "mes" and res["grafico"]["y"] == ["total_monto"]
    assert any("Se analizaron" in x for x in res["resumen"])
    assert "Período" in res["condiciones"][0]
    assert res["registrosAnalizados"] == 3 and res["mostradas"] == len(res["filas"])
    assert r["entendi"].startswith("Quieres ver pagos y recaudación")


def test_un_dataset_sin_permiso_no_se_consulta():
    with pytest.raises(motor.ConsultaInvalida):
        motor.ejecutar({"dataset": "becas"}, DATOS)          # el rol no trae «becas» entre sus datos


def test_el_limite_no_cambia_el_total_analizado():
    _, res = pedir("los 2 pagos más altos")
    assert res["registrosAnalizados"] == 5 and res["totalFilas"] == 5 and res["mostradas"] == 2


def test_formato_de_los_numeros():
    assert motor.fmt_valor(1234.5, "moneda") == "Bs 1.234,50"
    assert motor.fmt_valor(80.0, "porcentaje") == "80,0%"
    assert motor.fmt_valor(None, "moneda") == "—"
