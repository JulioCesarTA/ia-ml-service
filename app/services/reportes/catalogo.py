"""Catálogo de datos que el generador de reportes puede consultar: conjuntos, columnas y sinónimos en español.

Todo lo que el usuario puede pedir sale de aquí: el lenguaje natural se traduce a estos nombres.
"""


def col(nombre: str, etiqueta: str, tipo: str, sinonimos: list[str] | None = None, fmt: str | None = None) -> dict:
    """tipo: texto | categoria | numero | fecha. fmt: moneda | porcentaje | entero | decimal."""
    return {"nombre": nombre, "etiqueta": etiqueta, "tipo": tipo, "sinonimos": sinonimos or [], "fmt": fmt}


DATASETS: dict[str, dict] = {
    "reservas": {
        "raices": ['reserv', 'racion', 'servid'],
        "etiqueta": "Reservas de raciones",
        "descripcion": "Cada ración reservada: quién, qué plato, turno, día y estado.",
        "sinonimos": ["reserva", "reservas", "reservaciones", "racion", "raciones", "comidas", "pedidos", "servidas", "asistencia", "comensales"],
        "palabras_clave": "reservas raciones reservadas comidas servidas pedidos asistencia comensales cuántas raciones se sirvieron",
        "fecha": "fecha",
        "columnas": [
            col("fecha", "Fecha", "fecha", ["dia", "fecha de servicio", "fecha del servicio"]),
            col("turno", "Turno", "categoria", ["horario", "comida", "servicio"]),
            col("plato", "Plato", "categoria", ["menu", "platillo", "platos"]),
            col("estado", "Estado", "categoria", ["situacion", "estatus"]),
            col("estudiante", "Estudiante", "texto", ["alumno", "alumnos", "comensal", "nombre", "persona", "estudiantes"]),
            col("matricula", "Matrícula", "texto", ["registro", "codigo", "ru"]),
            col("creada", "Reservada el", "fecha", ["fecha de reserva", "creacion", "fecha de creacion"]),
        ],
        "defecto": ["fecha", "turno", "plato", "estudiante", "estado"],
        "medida": [],                     # sin columna numérica: se cuenta
        "ejemplos": ["cuántas raciones se reservaron por mes", "reservas de almuerzo de noviembre ordenadas por fecha en excel",
                     "los 5 platos más reservados"],
    },
    "pagos": {
        "raices": ['pag', 'cobr', 'recaud'],
        "etiqueta": "Pagos y recaudación",
        "descripcion": "Cada cobro: monto, método, estado, quién pagó y cuándo.",
        "sinonimos": ["pago", "pagos", "cobro", "cobros", "cobrado", "cobrados", "ingreso", "ingresos", "recaudacion", "recaudado",
                      "ventas", "facturacion", "dinero", "plata", "bolivianos", "transacciones", "tickets"],
        "palabras_clave": "pagos cobros ingresos recaudación dinero plata facturación monto total recaudado cuánto se cobró",
        "fecha": "fecha",
        "columnas": [
            col("fecha", "Fecha", "fecha", ["dia", "fecha de pago", "fecha del pago"]),
            col("estudiante", "Estudiante", "texto", ["alumno", "usuario", "quien pago", "persona", "pagador", "cliente", "matricula"]),
            col("monto", "Monto (Bs)", "numero", ["importe", "valor", "precio", "total", "plata", "dinero", "bs", "bolivianos", "cobro"], "moneda"),
            col("metodo", "Método de pago", "categoria", ["metodo", "forma de pago", "medio de pago", "tipo de pago", "modalidad"]),
            col("estado", "Estado", "categoria", ["situacion", "estatus"]),
            col("reserva", "Reserva", "texto", ["id de reserva"]),
            col("ticket", "Ticket", "texto", ["comprobante", "recibo"]),
        ],
        "defecto": ["fecha", "estudiante", "monto", "metodo", "estado"],
        "medida": [("sum", "monto"), ("count", None)],
        "ejemplos": ["total cobrado por mes", "pagos mayores a 5 bolivianos de este mes en pdf", "recaudación por método de pago en excel"],
    },
    "estudiantes": {
        "raices": ['estudiant', 'alumn'],
        "etiqueta": "Estudiantes",
        "descripcion": "Padrón de estudiantes con su beca, cuántas reservas hicieron y cuánto pagaron.",
        "sinonimos": ["estudiante", "estudiantes", "alumno", "alumnos", "padron", "usuarios", "registrados", "matriculados"],
        "palabras_clave": "estudiantes alumnos padrón registrados matrícula becarios con beca sin beca correo",
        "fecha": None,
        "columnas": [
            col("matricula", "Matrícula", "texto", ["registro", "codigo", "ru"]),
            col("nombre", "Nombre", "texto", ["estudiante", "alumno", "persona", "nombres"]),
            col("email", "Correo", "texto", ["correo", "mail", "email", "correo electronico", "e-mail"]),
            col("telefono", "Teléfono", "texto", ["celular", "numero", "whatsapp", "movil"]),
            col("beca", "Beca", "categoria", ["tipo de beca", "beneficio"]),
            col("reservas", "Reservas", "numero", ["cantidad de reservas", "raciones", "veces que reservo"], "entero"),
            col("pagado", "Pagado (Bs)", "numero", ["monto pagado", "total pagado", "gastado", "aportado", "pagos"], "moneda"),
        ],
        "defecto": ["matricula", "nombre", "email", "beca", "reservas", "pagado"],
        "medida": [("count", None)],
        "ejemplos": ["estudiantes con beca", "los 10 estudiantes que más reservaron", "estudiantes sin beca ordenados por nombre en excel"],
    },
    "becas": {
        "raices": ['becari', 'becad'],
        "etiqueta": "Becas",
        "descripcion": "Becas asignadas: tipo, cupo mensual, raciones usadas y vigencia.",
        "sinonimos": ["beca", "becas", "becario", "becarios", "becada", "becadas", "becado", "becados"],
        "palabras_clave": "becas becarios beca completa media parcial cupo mensual raciones usadas vigencia",
        "fecha": "desde",
        "columnas": [
            col("estudiante", "Estudiante", "texto", ["alumno", "becario", "nombre", "persona"]),
            col("matricula", "Matrícula", "texto", ["registro", "codigo", "ru"]),
            col("tipo", "Tipo de beca", "categoria", ["modalidad", "beca", "categoria"]),
            col("cupoMensual", "Cupo mensual", "numero", ["cupo", "raciones por mes", "cupo de raciones"], "entero"),
            col("usadas", "Raciones usadas", "numero", ["consumidas", "utilizadas", "usado", "consumo"], "entero"),
            col("disponibles", "Raciones disponibles", "numero", ["restantes", "saldo", "que quedan", "libres"], "entero"),
            col("uso", "Uso (%)", "numero", ["porcentaje de uso", "aprovechamiento", "porcentaje usado"], "porcentaje"),
            col("desde", "Vigente desde", "fecha", ["inicio", "fecha de inicio"]),
            col("hasta", "Vigente hasta", "fecha", ["fin", "vencimiento", "fecha de fin", "vence"]),
            col("vigente", "Vigente", "categoria", ["activa", "activo", "vigencia"]),
        ],
        "defecto": ["estudiante", "tipo", "cupoMensual", "usadas", "disponibles", "uso", "hasta"],
        "medida": [("count", None)],
        "ejemplos": ["becas con menos uso", "becarios inactivos", "becas por tipo"],
    },
    "menus": {
        "raices": ['menu', 'cupo', 'porcion'],
        "etiqueta": "Menús y cupos",
        "descripcion": "Platos publicados por día y turno con su cupo, porciones apartadas y disponibles.",
        "sinonimos": ["menu", "menus", "plato", "platos", "cupo", "cupos", "porciones", "disponibles", "publicados", "ocupacion"],
        "palabras_clave": "menús platos cupos porciones apartadas disponibles ocupación publicados",
        "fecha": "fecha",
        "columnas": [
            col("fecha", "Fecha", "fecha", ["dia"]),
            col("turno", "Turno", "categoria", ["horario", "comida"]),
            col("plato", "Plato", "categoria", ["platillo", "menu"]),
            col("cupo", "Cupo", "numero", ["cupo total", "capacidad", "porciones totales"], "entero"),
            col("apartadas", "Apartadas", "numero", ["reservadas", "reservas", "pedidas", "vendidas", "porciones apartadas", "demanda"], "entero"),
            col("disponibles", "Disponibles", "numero", ["libres", "restantes", "que quedan", "sobrantes"], "entero"),
            col("ocupacion", "Ocupación (%)", "numero", ["porcentaje de ocupacion", "llenado", "aceptacion", "porcentaje"], "porcentaje"),
        ],
        "defecto": ["fecha", "turno", "plato", "cupo", "apartadas", "disponibles", "ocupacion"],
        "medida": [("sum", "apartadas"), ("sum", "cupo")],
        "ejemplos": ["platos más pedidos de la semana", "menús con menos cupos disponibles", "ocupación promedio por plato en excel"],
    },
    "insumos": {
        "raices": ['insum', 'invent', 'vencim'],
        "etiqueta": "Insumos e inventario",
        "descripcion": "Stock de cada insumo, su mínimo, lotes y próximo vencimiento.",
        "sinonimos": ["insumo", "insumos", "inventario", "stock", "almacen", "ingredientes", "productos", "lotes", "existencias", "vencimiento", "vencer"],
        "palabras_clave": "insumos inventario stock almacén ingredientes lotes vencimiento por vencer stock bajo existencias",
        "fecha": "vence",
        "columnas": [
            col("insumo", "Insumo", "texto", ["nombre", "producto", "ingrediente"]),
            col("unidad", "Unidad", "categoria", ["medida"]),
            col("stock", "Stock actual", "numero", ["existencia", "existencias", "cantidad", "disponible", "inventario"], "decimal"),
            col("minimo", "Stock mínimo", "numero", ["minimo", "stock minimo", "umbral"], "decimal"),
            col("estado", "Estado", "categoria", ["situacion", "nivel"]),
            col("lotes", "Lotes", "numero", ["cantidad de lotes", "numero de lotes"], "entero"),
            col("vence", "Próximo vencimiento", "fecha", ["vencimiento", "fecha de vencimiento", "caducidad", "vence"]),
            col("diasParaVencer", "Días para vencer", "numero", ["dias restantes", "dias para el vencimiento", "dias hasta vencer"], "entero"),
        ],
        "defecto": ["insumo", "stock", "unidad", "minimo", "estado", "vence", "diasParaVencer"],
        "medida": [("count", None)],
        "ejemplos": ["insumos con stock bajo", "insumos que vencen en los próximos 7 días", "inventario ordenado por stock ascendente en pdf"],
    },
    "desperdicio": {
        "raices": ['desperdic', 'sobrant', 'merma'],
        "etiqueta": "Desperdicio (fotos de bandejas)",
        "descripcion": "Bandejas analizadas con TensorFlow: porcentaje que sobró y que se comió.",
        "sinonimos": ["desperdicio", "desperdicios", "sobrante", "sobrantes", "merma", "bandeja", "bandejas", "fotos", "restante", "desperdiciado"],
        "palabras_clave": "desperdicio sobrante merma bandejas fotos porcentaje que sobró lo que se comió",
        "fecha": "fecha",
        "columnas": [
            col("fecha", "Fecha", "fecha", ["dia"]),
            col("turno", "Turno", "categoria", ["horario", "comida"]),
            col("plato", "Plato", "categoria", ["platillo", "menu"]),
            col("restante", "Sobrante (%)", "numero", ["desperdicio", "sobro", "merma", "porcentaje sobrante", "restante"], "porcentaje"),
            col("comido", "Comido (%)", "numero", ["consumido", "aprovechado", "porcentaje comido"], "porcentaje"),
            col("confianza", "Confianza (%)", "numero", ["certeza", "seguridad"], "porcentaje"),
        ],
        "defecto": ["fecha", "turno", "plato", "restante", "comido", "confianza"],
        "medida": [("avg", "restante"), ("count", None)],
        "ejemplos": ["desperdicio promedio por plato", "los 5 platos con más desperdicio", "sobrante por mes en excel"],
    },
}

# Quién puede consultar qué (con la autenticación activa el rol sale del token)
PERMISOS = {
    "administrador": set(DATASETS),
    "nutricionista": {"menus", "desperdicio", "reservas", "insumos"},
    "cocina_almacen": {"insumos", "menus", "reservas", "desperdicio"},
    "servicio_caja": {"pagos", "reservas"},
}


def columna(dataset: str, nombre: str) -> dict:
    return next(c for c in DATASETS[dataset]["columnas"] if c["nombre"] == nombre)


def etiqueta(dataset: str, nombre: str) -> str:
    """La etiqueta de la columna; si el nombre no es una columna (p. ej. «cantidad»), se devuelve tal cual."""
    c = next((c for c in DATASETS[dataset]["columnas"] if c["nombre"] == nombre), None)
    return c["etiqueta"] if c else nombre
