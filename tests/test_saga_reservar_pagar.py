"""Reservar primero y pagar después (con servicios falsos, sin red ni DynamoDB)."""
import pytest

from app.application.saga.orquestador import SagaOrchestrator


class Mundo:
    """Los tres microservicios y DynamoDB, en memoria."""

    def __init__(self, beca=None, stripe=False, falla_confirmar=False):
        self.reservas, self.pagos, self.cupo, self.idem, self.llamadas = {}, {}, {"m1/p1": 0}, {}, []
        self.beca_resp, self.stripe, self.falla_confirmar = beca or {}, stripe, falla_confirmar

    # comensales
    def beca(self, _): return self.beca_resp
    def crear_reserva(self, d):
        rid = f"r{len(self.reservas) + 1}"
        self.reservas[rid] = {"id": rid, "estudianteId": d["estudianteId"], "menuId": d["menuId"], "platoId": d["platoId"],
                              "fecha": d["fecha"], "turno": d["turno"], "estado": "pendiente", "qr": None}
        return rid
    def obtener_reserva(self, rid):
        if rid not in self.reservas: raise ValueError("La reserva no existe")
        return dict(self.reservas[rid])
    def confirmar_reserva(self, rid):
        if self.falla_confirmar: return False, {}
        self.reservas[rid]["estado"] = "confirmada"
        return True, {"qr": f"QR-{rid}"}
    def cancelar_reserva(self, rid): self.reservas[rid]["estado"] = "cancelada"
    # menú
    def apartar_porcion(self, m, p): self.cupo[f"{m}/{p}"] += 1
    def liberar_porcion(self, m, p): self.cupo[f"{m}/{p}"] -= 1
    # pagos
    def cobrar(self, d):
        pid = f"p{len(self.pagos) + 1}"
        self.pagos[pid] = {**d, "estado": "cobrado"}
        return {"pagoId": pid, "ticketId": f"t{pid}", "stripe": {"paymentUrl": "https://stripe", "gatewayRef": "cs_1"} if self.stripe and d["metodo"] == "qr_bancario" else None}
    def devolver_pago(self, pid): self.pagos[pid]["estado"] = "devuelto"


class AlmacenEnMemoria:
    """Puerto AlmacenSagas (DynamoDB) en memoria: la idempotencia vive en el mundo."""

    def __init__(self, m: Mundo):
        self.m = m

    def asegurar_tablas(self): pass
    def bloquear_idempotencia(self, clave, respuesta=None):
        if clave in self.m.idem: return self.m.idem[clave]
        self.m.idem[clave] = {}
        return None
    def guardar_respuesta_idempotencia(self, clave, respuesta): self.m.idem[clave] = respuesta
    def guardar_saga(self, *a, **k): pass
    def obtener_saga(self, saga_id): return None


class Orq:
    """Arma un orquestador nuevo por llamada (como el router), con el mundo como menú, reservas y pagos."""
    m: Mundo = None

    @classmethod
    def SagaOrchestrator(cls):
        return SagaOrchestrator(cls.m, cls.m, cls.m, AlmacenEnMemoria(cls.m))


orq = Orq


@pytest.fixture
def mundo(monkeypatch):
    def armar(**kw):
        m = Mundo(**kw)
        monkeypatch.setattr(Orq, "m", m)
        return m
    return armar


def pedido(**kw):
    return {"estudiante_id": "ana", "menu_id": "m1", "plato_id": "p1", "fecha": "2026-11-09", "turno": "ALMUERZO", "idempotency_key": "k1", **kw}


def test_reservar_no_cobra_deja_la_reserva_pendiente_y_aparta_la_porcion(mundo):
    m = mundo()
    r = orq.SagaOrchestrator().reservar(pedido())
    assert r["status"] == "RESERVED" and r["requierePago"] is True and r["qr"] is None
    assert m.pagos == {} and m.reservas[r["reservaId"]]["estado"] == "pendiente" and m.cupo["m1/p1"] == 1


def test_reservar_varias_veces_el_mismo_dia_quien_paga(mundo):
    m = mundo()
    ids = {orq.SagaOrchestrator().reservar(pedido(idempotency_key=f"k{i}"))["reservaId"] for i in range(3)}
    assert len(ids) == 3 and m.cupo["m1/p1"] == 3


def test_reservar_con_la_misma_clave_no_duplica(mundo):
    m = mundo()
    a, b = orq.SagaOrchestrator().reservar(pedido()), orq.SagaOrchestrator().reservar(pedido())
    assert a["sagaId"] == b["sagaId"] and len(m.reservas) == 1 and m.cupo["m1/p1"] == 1


def test_con_beca_que_cubre_se_completa_todo_sin_pagar(mundo):
    m = mundo(beca={"tieneBeca": True, "cubreHoy": True})
    r = orq.SagaOrchestrator().reservar(pedido())
    assert r["status"] == "COMPLETED" and r["qr"] and m.reservas[r["reservaId"]]["estado"] == "confirmada"
    assert next(iter(m.pagos.values()))["metodo"] == "beca" and next(iter(m.pagos.values()))["monto"] == 0


def test_beca_sin_cupo_paga_como_cualquiera(mundo):
    m = mundo(beca={"tieneBeca": True, "cubreHoy": False})
    assert orq.SagaOrchestrator().reservar(pedido())["status"] == "RESERVED" and m.pagos == {}


def test_si_apartar_falla_se_cancela_la_reserva(mundo, monkeypatch):
    m = mundo()
    def mal(*a): raise RuntimeError("sin cupo")
    monkeypatch.setattr(m, "apartar_porcion", mal)
    with pytest.raises(RuntimeError):
        orq.SagaOrchestrator().reservar(pedido())
    assert [r["estado"] for r in m.reservas.values()] == ["cancelada"]


def test_pagar_con_qr_queda_pendiente_de_verificar_y_la_reserva_sigue_pendiente(mundo):
    m = mundo(stripe=True)
    r = orq.SagaOrchestrator().reservar(pedido())
    p = orq.SagaOrchestrator().pagar({"reserva_id": r["reservaId"], "estudiante_id": "ana", "metodo_pago": "qr_bancario", "monto": 12, "idempotency_key": "p1"})
    assert p["status"] == "PENDING_PAYMENT" and p["stripe"]["gatewayRef"] == "cs_1"
    assert m.reservas[r["reservaId"]]["estado"] == "pendiente"


def test_pagar_en_efectivo_confirma_con_qr(mundo):
    m = mundo()
    r = orq.SagaOrchestrator().reservar(pedido())
    p = orq.SagaOrchestrator().pagar({"reserva_id": r["reservaId"], "estudiante_id": "ana", "metodo_pago": "efectivo", "monto": 12, "idempotency_key": "p1"})
    assert p["status"] == "COMPLETED" and p["qr"] == f"QR-{r['reservaId']}" and m.reservas[r["reservaId"]]["estado"] == "confirmada"


def test_pagar_dos_veces_no_cobra_dos_veces(mundo):
    m = mundo()
    r = orq.SagaOrchestrator().reservar(pedido())
    cuerpo = {"reserva_id": r["reservaId"], "estudiante_id": "ana", "metodo_pago": "efectivo", "monto": 12, "idempotency_key": "p1"}
    a, b = orq.SagaOrchestrator().pagar(cuerpo), orq.SagaOrchestrator().pagar(cuerpo)
    assert a["sagaId"] == b["sagaId"] and len(m.pagos) == 1
    with pytest.raises(ValueError, match="solo se paga una reserva pendiente"):
        orq.SagaOrchestrator().pagar({**cuerpo, "idempotency_key": "otra"})          # ya confirmada: no se cobra de nuevo
    assert len(m.pagos) == 1


def test_si_confirmar_falla_se_devuelve_el_cobro(mundo):
    m = mundo(falla_confirmar=True)
    r = orq.SagaOrchestrator().reservar(pedido())
    with pytest.raises(RuntimeError):
        orq.SagaOrchestrator().pagar({"reserva_id": r["reservaId"], "estudiante_id": "ana", "metodo_pago": "efectivo", "monto": 12, "idempotency_key": "p1"})
    assert next(iter(m.pagos.values()))["estado"] == "devuelto" and m.reservas[r["reservaId"]]["estado"] == "pendiente"


def test_pagar_valida_metodo_y_que_la_reserva_exista(mundo):
    mundo()
    with pytest.raises(ValueError):
        orq.SagaOrchestrator().pagar({"reserva_id": "nada", "estudiante_id": "ana", "metodo_pago": "efectivo", "monto": 1, "idempotency_key": "x"})
    with pytest.raises(ValueError, match="metodo_pago"):
        orq.SagaOrchestrator().pagar({"reserva_id": "r1", "estudiante_id": "ana", "metodo_pago": "bitcoin", "monto": 1, "idempotency_key": "y"})


def test_cancelar_sin_pago_libera_la_porcion_y_solo_si_esta_pendiente(mundo):
    m = mundo()
    r = orq.SagaOrchestrator().reservar(pedido())
    assert orq.SagaOrchestrator().cancelar_sin_pago(r["reservaId"])["status"] == "COMPLETED"
    assert m.reservas[r["reservaId"]]["estado"] == "cancelada" and m.cupo["m1/p1"] == 0
    with pytest.raises(ValueError, match="pendiente"):
        orq.SagaOrchestrator().cancelar_sin_pago(r["reservaId"])
    assert m.cupo["m1/p1"] == 0
