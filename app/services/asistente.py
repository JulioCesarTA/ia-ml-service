"""Asistente de Telegram del comedor (reemplaza al de WhatsApp).

1) Pide el correo institucional y averigua tu usuario y rol. Administrador, cocinero, caja y nutricionista
   confirman además su contraseña (con ella se aprueban cosas), y el mensaje con la contraseña se borra.
2) Menú de botones: Menú, Quién soy, Reservar (estudiantes) y Pendientes (administradores).
3) Reservar: con beca vigente se reserva sin pagar; sin beca se entrega un QR para pagar con Stripe y,
   cuando el pago se acredita, llega la confirmación con su QR de ingreso y la factura de Stripe.
"""
import base64
import os
import time
from datetime import date

from app.data import comedor_http, repo_telegram
from app.services import identidad, propuestas, telegram_bot as tg
from app.services.reportes.motor import norm_simple as _norm      # minúsculas y sin acentos
from app.services.saga.orchestrator import SagaOrchestrator

TURNOS = {"D": "DESAYUNO", "A": "ALMUERZO", "C": "CENA"}
ETIQ_TURNO = {"DESAYUNO": "Desayuno", "ALMUERZO": "Almuerzo", "CENA": "Cena"}
ETIQ_ROL = {"administrador": "Administrador", "cocinero": "Cocinero", "caja": "Caja",
            "nutricionista": "Nutricionista", "estudiante": "Estudiante"}
MONTO_RACION = 10
VENCE_PAGO_S = 30 * 60


def _png(data_uri: str) -> bytes:
    return base64.b64decode(data_uri.split(",", 1)[1])


# ----------------------------- teclados -----------------------------

# Quién puede reservar por Telegram: los estudiantes y también el administrador (que paga su ración con QR, sin beca).
PUEDEN_RESERVAR = {"estudiante", "administrador"}


def _puede_reservar(roles: list[str]) -> bool:
    return bool(set(roles) & PUEDEN_RESERVAR)


def _teclado(roles: list[str]) -> list[list[dict]]:
    filas = [[tg.boton("📋 Menú", "m:menu"), tg.boton("🙋 Quién soy", "m:quien")]]
    if _puede_reservar(roles):
        filas.append([tg.boton("🍽️ Reservar", "m:res")])
    if "administrador" in roles:
        filas.append([tg.boton("⏳ Pendientes", "m:pend")])
    filas.append([tg.boton("🔁 Cambiar de cuenta", "m:cambiar")])
    return filas


def _menu_principal(cid: str, ch: dict, intro: str) -> None:
    tg.enviar(cid, intro, _teclado(ch["roles"]))


# ----------------------------- datos del comedor -----------------------------

def _dias(turno: str) -> list[tuple[str, dict]]:
    """Un bloque por día futuro (fusiona menús repetidos): [(fecha, {plato: {menuId, cupo, disponibles}})]."""
    menus = comedor_http.menus_semana(turno)
    hoy = date.today().isoformat()
    dias: dict[str, dict] = {}
    for m in menus:
        if m.get("fecha", "") < hoy:
            continue
        platos = dias.setdefault(m["fecha"], {})
        for pid, p in (m.get("porciones") or {}).items():
            previo = platos.get(pid)
            if not previo or p["disponibles"] > previo["disponibles"]:
                platos[pid] = {"menuId": m["id"], "cupo": p["cupo"], "disponibles": p["disponibles"]}
    return sorted(dias.items())


# ----------------------------- identificación -----------------------------

def _pedir_correo(cid: str, texto: str | None = None) -> None:
    identidad.guardar_chat(cid, estado="pide_email", intentos=0)
    tg.enviar(cid, texto or "Hola 👋 Soy el asistente del Comedor Universitario UAGRM.\n\nPara saber quién eres, escribe tu correo institucional (por ejemplo nombre@uagrm.edu.bo).")


def _vincular(cid: str, u: dict) -> None:
    ch = identidad.guardar_chat(cid, estado="listo", email=u["email"], username=u["username"], nombre=u["nombre"],
                                roles=u["roles"], intentos=0)
    _menu_principal(cid, ch, f"✅ Listo, {u['nombre']}. Tu rol es {ETIQ_ROL.get(u['rol'], u['rol'])}.\n\n¿Qué quieres hacer?")


def _recibir_correo(cid: str, texto: str) -> None:
    try:
        u = identidad.buscar_por_email(texto)
    except Exception:
        tg.enviar(cid, "No puedo verificar tu identidad en este momento (sin conexión con el sistema). Inténtalo en unos minutos.")
        return
    if not u:
        tg.enviar(cid, "No encuentro ese correo en el sistema. Revísalo y escríbelo de nuevo.")
        return
    if set(u["roles"]) & identidad.PRIVILEGIADOS:
        identidad.guardar_chat(cid, estado="pide_password", email=u["email"], username=u["username"], nombre=u["nombre"],
                               roles=u["roles"], intentos=0)
        tg.enviar(cid, f"Hola {u['nombre']}. Tu rol es {ETIQ_ROL.get(u['rol'], u['rol'])}.\n\nPor seguridad confirma tu contraseña del panel de gestión. Borraré tu mensaje apenas lo lea.")
        return
    _vincular(cid, u)


def _recibir_password(cid: str, ch: dict, m: dict) -> None:
    tg.borrar(cid, m["message_id"])
    try:
        ok = identidad.verificar_password(ch["username"], (m.get("text") or "").strip())
    except Exception:
        tg.enviar(cid, "No puedo verificar tu contraseña ahora (sin conexión con el sistema). Inténtalo en unos minutos.")
        return
    if ok:
        _vincular(cid, {"email": ch["email"], "username": ch["username"], "nombre": ch["nombre"], "roles": ch["roles"],
                        "rol": identidad.rol_principal(ch["roles"])})
        return
    intentos = ch["intentos"] + 1
    if intentos >= 3:
        _pedir_correo(cid)
        tg.enviar(cid, "Demasiados intentos fallidos. Empecemos de nuevo.")
        return
    identidad.guardar_chat(cid, intentos=intentos)
    tg.enviar(cid, f"Contraseña incorrecta. Te quedan {3 - intentos} intento(s).")


# ----------------------------- opciones del menú -----------------------------

def _cambiar_cuenta(cid: str) -> None:
    """Cierra la sesión de este chat y pide el correo de otra cuenta."""
    identidad.borrar_chat(cid)
    _pedir_correo(cid, "Sesión cerrada ✅ Ya puedes entrar con otra cuenta.\n\nEscribe el correo institucional de la cuenta que quieres usar (por ejemplo nombre@uagrm.edu.bo).")


def _quien_soy(cid: str, ch: dict) -> None:
    lineas = [f"👤 {ch['nombre']}", f"Usuario: {ch['username']}", f"Correo: {ch['email']}",
              "Rol: " + ", ".join(ETIQ_ROL.get(r, r) for r in ch["roles"])]
    if _puede_reservar(ch["roles"]):
        b = comedor_http.beca(ch["username"])
        if b.get("tieneBeca"):
            lineas.append(f"🎓 Beca {b.get('tipo')}: {b.get('racionesUsadasMes', 0)}/{b.get('cupoRacionesMes', 0)} raciones este mes"
                          + (" — hoy te cubre." if b.get("cubreHoy") else " — hoy se paga (cupo agotado)."))
        else:
            lineas.append(f"Sin beca activa: cada ración cuesta {MONTO_RACION} y se paga con QR.")
    lineas.append("\nPara entrar con otra cuenta pulsa «Cambiar de cuenta» o escribe /cambiar.")
    _menu_principal(cid, ch, "\n".join(lineas))


def _ver_menu(cid: str, turno: str = "ALMUERZO") -> None:
    dias = _dias(turno)
    botones = [[tg.boton(("• " if k == turno else "") + ETIQ_TURNO[k], f"t:{c}") for c, k in TURNOS.items()]]
    if not dias:
        tg.enviar(cid, f"No hay menú publicado para {ETIQ_TURNO[turno].lower()}.", botones)
        return
    lineas = [f"📋 Menú de {ETIQ_TURNO[turno].lower()}"]
    for fecha, platos in dias[:7]:
        lineas.append(f"\n📅 {fecha}")
        lineas += [f"  • {pid.replace('plato-', '')}: {p['disponibles']}/{p['cupo']} disponibles" for pid, p in platos.items()]
    tg.enviar(cid, "\n".join(lineas), botones)


def _elegir_turno(cid: str, ch: dict) -> None:
    if not _puede_reservar(ch["roles"]):
        tg.enviar(cid, "Las reservas son solo para estudiantes y administradores.")
        return
    tg.enviar(cid, "¿Para qué turno quieres reservar?",
              [[tg.boton(ETIQ_TURNO[k], f"r:T:{c}") for c, k in TURNOS.items()]])


def _elegir_dia(cid: str, c: str) -> None:
    dias = [(f, p) for f, p in _dias(TURNOS[c]) if any(x["disponibles"] > 0 for x in p.values())][:7]
    if not dias:
        tg.enviar(cid, "No hay días con cupo para ese turno.")
        return
    tg.enviar(cid, f"¿Qué día? ({ETIQ_TURNO[TURNOS[c]].lower()})", [[tg.boton(f, f"r:D:{c}:{f}")] for f, _ in dias])


def _elegir_plato(cid: str, c: str, fecha: str) -> None:
    platos = dict(_dias(TURNOS[c])).get(fecha, {})
    filas = [[tg.boton(f"{pid.replace('plato-', '')} ({p['disponibles']} disp.)", f"r:P:{c}:{fecha}:{pid}")]
             for pid, p in platos.items() if p["disponibles"] > 0]
    if not filas:
        tg.enviar(cid, "Ese día ya no tiene cupos.")
        return
    tg.enviar(cid, f"¿Qué plato para el {fecha}?", filas)


def _reservar(cid: str, ch: dict, c: str, fecha: str, plato: str) -> None:
    turno = TURNOS[c]
    p = dict(_dias(turno)).get(fecha, {}).get(plato)
    if not p or p["disponibles"] <= 0:
        tg.enviar(cid, "Ese plato ya no tiene cupo.")
        return
    user = ch["username"]
    beca = comedor_http.beca(user)
    con_beca = bool(beca.get("tieneBeca") and beca.get("cubreHoy"))
    try:
        r = SagaOrchestrator().reservar_y_pagar({
            "estudiante_id": user, "menu_id": p["menuId"], "plato_id": plato, "fecha": fecha, "turno": turno,
            "metodo_pago": "beca" if con_beca else "qr_bancario", "monto": 0 if con_beca else MONTO_RACION,
            "idempotency_key": f"tg-{user}-{fecha}-{plato}"})
    except Exception as e:
        msg = str(e)
        tg.enviar(cid, "Ya tienes una reserva para ese día." if ("ya ten" in msg.lower() or "duplic" in msg.lower()) else f"No pude reservar: {msg[:150]}")
        return

    nombre = plato.replace("plato-", "")
    if r.get("status") == "PENDING_PAYMENT" and r.get("stripe"):
        s = r["stripe"]
        repo_telegram.guardar_pago(r["reservaId"], cid, s.get("gatewayRef"), nombre, fecha, turno)
        prueba = "\n\nTarjeta de prueba: 4242 4242 4242 4242 (cualquier fecha futura y CVC)." if os.getenv("STRIPE_SECRET_KEY", "").startswith("sk_test") else ""
        tg.enviar(cid, f"🧾 Reserva creada: {nombre}, {fecha} ({ETIQ_TURNO[turno].lower()}).\n"
                       f"Falta el pago de {MONTO_RACION}. Escanea el QR o abre el enlace:\n{s['paymentUrl']}{prueba}\n\n"
                       "Apenas se acredite el pago te aviso aquí y te envío tu factura de Stripe.",
                  [[tg.boton("🔄 Ya pagué, verificar", f"v:{r['reservaId']}")]])
        if s.get("qrDataUri"):
            tg.enviar_foto(cid, _png(s["qrDataUri"]), "QR de pago")
        return
    cabecera = "✅ Reserva confirmada con tu beca (sin pago)." if con_beca else "✅ Reserva confirmada."
    tg.enviar(cid, f"{cabecera}\n{nombre}, {fecha} ({ETIQ_TURNO[turno].lower()}).\nMuestra este QR al ingresar:")
    _enviar_qr_ingreso(cid, r.get("qr"))


def _enviar_qr_ingreso(cid: str, qr: str | None) -> None:
    if qr and "::" in qr:
        tg.enviar_foto(cid, _png(qr.split("::", 1)[1]), "QR de ingreso")


def _pendientes(cid: str) -> None:
    if not identidad.es_admin(cid):
        tg.enviar(cid, "Solo un administrador puede ver esto.")
        return
    pend = propuestas.listar("PENDIENTE")
    if not pend:
        tg.enviar(cid, "No hay propuestas pendientes. 👌")
        return
    for p in pend[:5]:
        tg.enviar(cid, f"{p['titulo']}\n\n{p['resumen']}", tg.botones_propuesta(p["id"]))


# ----------------------------- entrada de mensajes y botones -----------------------------

def mensaje(m: dict) -> None:
    cid = str(m["chat"]["id"])
    texto = (m.get("text") or "").strip()
    if not texto:
        return
    t = _norm(texto)
    ch = identidad.chat(cid)

    if t in ("/cambiar", "/cuenta", "cambiar", "cambiar de cuenta", "cambiar cuenta", "/salir", "salir", "cerrar sesion", "logout", "/logout"):
        _cambiar_cuenta(cid)
        return
    if ch is None:
        _pedir_correo(cid)
        if "@" in texto and not texto.startswith("/"):
            _recibir_correo(cid, texto)
        return
    if ch["estado"] == "pide_password":
        _recibir_password(cid, ch, m)
        return
    if ch["estado"] == "pide_email":
        if "@" in texto and not texto.startswith("/"):
            _recibir_correo(cid, texto)
        else:
            tg.enviar(cid, "Escribe tu correo institucional para identificarte (por ejemplo nombre@uagrm.edu.bo).")
        return

    if t.startswith("/start") or t in ("hola", "ayuda", "/ayuda"):
        try:                                   # si cambiaron tus roles en el sistema, se actualizan aquí
            u = identidad.buscar_por_email(ch["email"])
            if u:
                ch = identidad.guardar_chat(cid, roles=u["roles"], nombre=u["nombre"])
        except Exception:
            pass
        _menu_principal(cid, ch, f"Hola {ch['nombre']} 👋 ¿Qué quieres hacer?")
    elif t in ("menu", "/menu"):
        _ver_menu(cid)
    elif t in ("quien soy", "/quiensoy", "/quien", "/yo", "yo"):
        _quien_soy(cid, ch)
    elif t.startswith("reservar") or t == "/reservar":
        _elegir_turno(cid, ch)
    elif t in ("pendientes", "/pendientes"):
        _pendientes(cid)
    else:
        _menu_principal(cid, ch, "No entendí. Elige una opción:")


def boton(cb: dict) -> None:
    cid = str(cb["message"]["chat"]["id"])
    ch = identidad.chat(cid)
    if not ch or ch["estado"] != "listo":
        tg._api("answerCallbackQuery", callback_query_id=cb["id"], text="Escribe /start para identificarte")
        return
    d = cb["data"].split(":")
    if d[0] == "v":
        ok = _verificar_pago(d[1])
        tg._api("answerCallbackQuery", callback_query_id=cb["id"],
                text="Pago acreditado" if ok else "Todavía no figura el pago. Complétalo y vuelve a verificar.")
        return
    tg._api("answerCallbackQuery", callback_query_id=cb["id"])
    if d[0] == "m":
        {"menu": lambda: _ver_menu(cid), "quien": lambda: _quien_soy(cid, ch), "res": lambda: _elegir_turno(cid, ch),
         "pend": lambda: _pendientes(cid), "cambiar": lambda: _cambiar_cuenta(cid)}.get(d[1], lambda: None)()
    elif d[0] == "t":
        _ver_menu(cid, TURNOS.get(d[1], "ALMUERZO"))
    elif d[0] == "r" and _puede_reservar(ch["roles"]):
        if d[1] == "T":
            _elegir_dia(cid, d[2])
        elif d[1] == "D":
            _elegir_plato(cid, d[2], d[3])
        elif d[1] == "P":
            _reservar(cid, ch, d[2], d[3], ":".join(d[4:]))


# ----------------------------- pagos pendientes y factura -----------------------------

def _verificar_pago(reserva_id: str) -> bool:
    f = repo_telegram.pago(reserva_id)
    if not f or f["estado"] not in ("esperando_pago", "vencido"):
        return bool(f and f["estado"] in ("esperando_factura", "completado"))
    try:
        r = SagaOrchestrator().confirmar_pago(reserva_id, f["referencia"])
    except Exception:
        return False
    if not r.get("confirmada"):
        return False
    repo_telegram.marcar_pago(reserva_id, "esperando_factura")
    tg.enviar(f["chat_id"], f"✅ Pago recibido. Tu reserva está confirmada: {f['plato']}, {f['fecha']} ({ETIQ_TURNO.get(f['turno'], '').lower()}).\nMuestra este QR al ingresar:")
    _enviar_qr_ingreso(f["chat_id"], r.get("qr"))
    _enviar_factura(repo_telegram.pago(reserva_id))
    return True


def _enviar_factura(f: dict) -> None:
    """La factura de Stripe tarda unos segundos en emitirse: se reintenta antes de conformarse con el recibo."""
    try:
        j = comedor_http.recibo(f["referencia"])
    except Exception:
        j = {}
    if j.get("url") and (j.get("tipo") == "factura" or f["intentos"] >= 6):
        etiqueta = "factura" if j.get("tipo") == "factura" else "recibo"
        tg.enviar(f["chat_id"], f"🧾 Tu {etiqueta} de Stripe:\n{j['url']}")
        if j.get("pdf"):
            try:
                tg.enviar_documento_url(f["chat_id"], j["pdf"], f"{etiqueta.capitalize()} en PDF")
            except Exception:
                pass
        repo_telegram.marcar_pago(f["reserva_id"], "completado")
        return
    n = f["intentos"] + 1
    if n >= 15:
        tg.enviar(f["chat_id"], "Tu pago está confirmado, pero Stripe todavía no emitió la factura. La podrás ver en tu portal.")
        repo_telegram.marcar_pago(f["reserva_id"], "completado")
    else:
        repo_telegram.marcar_pago(f["reserva_id"], "esperando_factura", n)


def _revisar_pagos() -> None:
    for f in repo_telegram.pagos_en_curso():
        if f["estado"] == "esperando_factura":
            _enviar_factura(f)
        elif time.time() - f["creado"] > VENCE_PAGO_S:
            repo_telegram.marcar_pago(f["reserva_id"], "vencido")
            tg.enviar(f["chat_id"], "No recibí tu pago en 30 minutos. Si ya pagaste, pulsa «Ya pagué, verificar» en el mensaje de la reserva.")
        else:
            _verificar_pago(f["reserva_id"])


def bucle_pagos() -> None:
    while True:
        try:
            if tg.configurado():
                _revisar_pagos()
        except Exception as e:
            print(f"[telegram-pagos] {e}", flush=True)
        time.sleep(8)
