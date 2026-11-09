"""Calendario académico y feriados de Bolivia (2023-2027): configuración, no datos de demanda.

Lo usan la regresión (variables del modelo) y el generador de datos históricos de demostración.
"""
from datetime import date, timedelta

ANIOS = range(2023, 2028)

# Feriados de fecha fija (Bolivia) + los móviles (Carnaval, Viernes Santo, Corpus Christi) por año
_FIJOS = [(1, 1), (1, 22), (5, 1), (6, 21), (8, 6), (11, 2), (12, 25)]
_CARNAVAL = {2023: date(2023, 2, 20), 2024: date(2024, 2, 12), 2025: date(2025, 3, 3), 2026: date(2026, 2, 16), 2027: date(2027, 2, 8)}
_VIERNES_SANTO = {2023: date(2023, 4, 7), 2024: date(2024, 3, 29), 2025: date(2025, 4, 18), 2026: date(2026, 4, 3), 2027: date(2027, 3, 26)}
_CORPUS = {2023: date(2023, 6, 8), 2024: date(2024, 5, 30), 2025: date(2025, 6, 19), 2026: date(2026, 6, 4), 2027: date(2027, 5, 27)}

FERIADOS: set[date] = {date(a, m, d) for a in ANIOS for m, d in _FIJOS}
for _a in ANIOS:
    FERIADOS |= {_CARNAVAL[_a], _CARNAVAL[_a] + timedelta(days=1), _VIERNES_SANTO[_a], _CORPUS[_a]}

# Exámenes: segunda quincena de junio y de noviembre. Vacaciones: mitad de año (10-25 jul) y fin de año (20 dic - 1 feb).
PERIODOS_EXAMENES = [(date(a, 6, 15), date(a, 6, 30)) for a in ANIOS] + [(date(a, 11, 15), date(a, 11, 30)) for a in ANIOS]
PERIODOS_VACACIONES = ([(date(a, 7, 10), date(a, 7, 25)) for a in ANIOS]
                       + [(date(a, 12, 20), date(a + 1, 2, 1)) for a in ANIOS] + [(date(2023, 1, 1), date(2023, 2, 1))])


