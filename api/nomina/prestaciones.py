# api/nomina/prestaciones.py
# ─────────────────────────────────────────────────────────────────────────────
# Cálculos de prestaciones según la Ley Federal del Trabajo (LFT) y la Ley del
# ISR, como funciones puras (sin base de datos) para poder probarlas solas:
#
#   • Aguinaldo (LFT art. 87): mínimo 15 días de salario por año; quien no
#     trabajó el año completo recibe la parte proporcional. Exento de ISR
#     hasta 30 UMA diarias (LISR art. 93 fr. XIV); el excedente es gravable.
#   • Horas extra (LFT arts. 66–68): máximo 3 horas al día y 3 veces por
#     semana (9 h). Esas se pagan DOBLES; las que rebasan el límite, TRIPLES.
#     Exento: 50 % de las dobles, hasta 5 UMA por semana (LISR art. 93 fr. I);
#     las triples son gravables completas. (El caso de salario mínimo, donde
#     las dobles quedan exentas completas dentro del límite, no se modela.)
#   • Rotación: bajas del periodo / plantilla promedio × 100.
#
# Igual que el resto del motor de nómina, es un cálculo de REFERENCIA interno,
# no un timbrado fiscal oficial.
# ─────────────────────────────────────────────────────────────────────────────
import calendar
from datetime import date, datetime, timedelta

DIAS_MES = 30.4
DIAS_AGUINALDO_LEY = 15
EXENCION_AGUINALDO_UMAS = 30
EXENCION_HORAS_EXTRA_UMAS_SEMANA = 5
MAX_HORAS_DOBLES_DIA = 3
MAX_DIAS_DOBLES_SEMANA = 3
MAX_HORAS_DOBLES_SEMANA = 9


def parse_fecha(valor):
    """Acepta 'YYYY-MM-DD', ISO con hora, 'DD/MM/YYYY' o date/datetime."""
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto[:10], formato).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _numero(valor):
    try:
        n = float(str(valor).replace(",", "").replace("$", "").strip())
        return n if n > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def salario_diario(rh):
    """Salario diario del expediente; si solo hay mensual, mensual / 30.4."""
    diario = _numero((rh or {}).get("SalarioDiario"))
    if diario:
        return round(diario, 2)
    mensual = _numero((rh or {}).get("Salario"))
    return round(mensual / DIAS_MES, 2) if mensual else 0.0


def calcular_aguinaldo(sd, anio, fecha_ingreso=None, fecha_baja=None,
                       dias_aguinaldo=DIAS_AGUINALDO_LEY, uma_diaria=0.0,
                       isr_mensual=None, sueldo_mensual=0.0):
    """
    Aguinaldo de un año calendario. `isr_mensual(base)` calcula el ISR de un
    mes; el ISR del aguinaldo es la diferencia entre el ISR del mes con y sin
    la parte gravada (método simplificado de LISR art. 96).
    """
    inicio_anio, fin_anio = date(anio, 1, 1), date(anio, 12, 31)
    inicio = max(inicio_anio, fecha_ingreso) if fecha_ingreso else inicio_anio
    fin = min(fin_anio, fecha_baja) if fecha_baja else fin_anio
    dias_anio = 366 if calendar.isleap(anio) else 365
    dias_trabajados = (fin - inicio).days + 1 if fin >= inicio else 0

    dias_a_pagar = round(dias_aguinaldo * dias_trabajados / dias_anio, 2)
    monto = round(sd * dias_a_pagar, 2)
    exento = round(min(monto, EXENCION_AGUINALDO_UMAS * uma_diaria), 2) if uma_diaria else 0.0
    gravado = round(monto - exento, 2)
    isr = 0.0
    if gravado > 0 and isr_mensual:
        isr = round(max(isr_mensual(sueldo_mensual + gravado) - isr_mensual(sueldo_mensual), 0), 2)
    return {
        "anio": anio,
        "salario_diario": sd,
        "dias_aguinaldo": dias_aguinaldo,
        "periodo_desde": inicio.isoformat() if dias_trabajados else None,
        "periodo_hasta": fin.isoformat() if dias_trabajados else None,
        "dias_trabajados": dias_trabajados,
        "dias_anio": dias_anio,
        "proporcional": dias_trabajados < dias_anio,
        "dias_a_pagar": dias_a_pagar,
        "monto": monto,
        "exento": exento,
        "gravado": gravado,
        "isr": isr,
        "neto": round(monto - isr, 2),
    }


def _semana(fecha):
    lunes = fecha - timedelta(days=fecha.weekday())
    return lunes, lunes + timedelta(days=6)


def calcular_horas_extra(registros, sd, jornada_horas=8, uma_diaria=0.0):
    """
    `registros` = [{"fecha": date|str, "horas": float}, …] ya aprobados.
    Agrupa por semana (lunes a domingo) y reparte dobles/triples por día en
    orden cronológico: un día cuenta como "vez" de la semana si tuvo horas.
    """
    por_dia = {}
    for r in registros:
        f = parse_fecha(r.get("fecha"))
        h = _numero(r.get("horas"))
        if f and h:
            por_dia[f] = por_dia.get(f, 0.0) + h

    salario_hora = round(sd / jornada_horas, 4) if jornada_horas else 0.0
    semanas = {}
    for dia in sorted(por_dia):
        lunes, domingo = _semana(dia)
        s = semanas.setdefault(lunes, {"desde": lunes, "hasta": domingo, "dias": [], "dobles": 0.0, "triples": 0.0,
                                       "dias_con_extra": 0, "alertas": []})
        horas = por_dia[dia]
        s["dias_con_extra"] += 1
        if s["dias_con_extra"] > MAX_DIAS_DOBLES_SEMANA:
            dobles = 0.0
            s["alertas"].append(f"{dia.isoformat()}: más de {MAX_DIAS_DOBLES_SEMANA} días con horas extra en la semana; se pagan triples")
        else:
            dobles = min(horas, MAX_HORAS_DOBLES_DIA, MAX_HORAS_DOBLES_SEMANA - s["dobles"])
            if horas > MAX_HORAS_DOBLES_DIA:
                s["alertas"].append(f"{dia.isoformat()}: {horas:g} h rebasan el máximo de {MAX_HORAS_DOBLES_DIA} h diarias")
        triples = round(horas - dobles, 2)
        s["dobles"] = round(s["dobles"] + dobles, 2)
        s["triples"] = round(s["triples"] + triples, 2)
        s["dias"].append({"fecha": dia.isoformat(), "horas": horas, "dobles": round(dobles, 2), "triples": triples})

    detalle = []
    tot = {"horas": 0.0, "dobles": 0.0, "triples": 0.0, "pago_dobles": 0.0, "pago_triples": 0.0,
           "monto": 0.0, "exento": 0.0, "gravado": 0.0}
    for lunes in sorted(semanas):
        s = semanas[lunes]
        pago_dobles = round(s["dobles"] * salario_hora * 2, 2)
        pago_triples = round(s["triples"] * salario_hora * 3, 2)
        monto = round(pago_dobles + pago_triples, 2)
        tope = EXENCION_HORAS_EXTRA_UMAS_SEMANA * uma_diaria if uma_diaria else 0.0
        exento = round(min(pago_dobles * 0.5, tope), 2)
        gravado = round(monto - exento, 2)
        if s["dobles"] + s["triples"] > MAX_HORAS_DOBLES_SEMANA:
            s["alertas"].append(f"Semana con {s['dobles'] + s['triples']:g} h: rebasa el máximo legal de {MAX_HORAS_DOBLES_SEMANA} h")
        detalle.append({
            "desde": s["desde"].isoformat(), "hasta": s["hasta"].isoformat(), "dias": s["dias"],
            "horas": round(s["dobles"] + s["triples"], 2), "dobles": s["dobles"], "triples": s["triples"],
            "pago_dobles": pago_dobles, "pago_triples": pago_triples, "monto": monto,
            "exento": exento, "gravado": gravado, "alertas": s["alertas"],
        })
        for k, v in (("horas", s["dobles"] + s["triples"]), ("dobles", s["dobles"]), ("triples", s["triples"]),
                     ("pago_dobles", pago_dobles), ("pago_triples", pago_triples), ("monto", monto),
                     ("exento", exento), ("gravado", gravado)):
            tot[k] = round(tot[k] + v, 2)

    return {"salario_hora": round(salario_hora, 2), "jornada_horas": jornada_horas, "semanas": detalle, "totales": tot}


def _meses(desde, hasta):
    """Lista de (primer_dia, ultimo_dia) por mes entre dos fechas."""
    meses = []
    y, m = desde.year, desde.month
    while (y, m) <= (hasta.year, hasta.month):
        ultimo = calendar.monthrange(y, m)[1]
        meses.append((date(y, m, 1), date(y, m, ultimo)))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return meses


def _activos_en(personas, dia):
    return sum(1 for p in personas
               if (p["ingreso"] is None or p["ingreso"] <= dia) and (p["baja"] is None or p["baja"] > dia))


def calcular_rotacion(personas, desde, hasta):
    """
    `personas` = [{"area", "ingreso": date|None, "baja": date|None, "tipo_baja"}].
    Sin fecha de ingreso se asume que ya estaba al inicio del periodo.
    Rotación del mes = bajas del mes / ((plantilla inicial + final) / 2) × 100.
    """
    por_mes = []
    for primero, ultimo in _meses(desde, hasta):
        inicial = _activos_en(personas, primero - timedelta(days=1))
        final = _activos_en(personas, ultimo)
        altas = sum(1 for p in personas if p["ingreso"] and primero <= p["ingreso"] <= ultimo)
        bajas = sum(1 for p in personas if p["baja"] and primero <= p["baja"] <= ultimo)
        promedio = (inicial + final) / 2
        por_mes.append({
            "mes": primero.strftime("%Y-%m"), "plantilla_inicial": inicial, "plantilla_final": final,
            "altas": altas, "bajas": bajas,
            "rotacion_pct": round(bajas / promedio * 100, 1) if promedio else 0.0,
        })

    en_periodo = [p for p in personas if p["baja"] and desde <= p["baja"] <= hasta]
    inicial = _activos_en(personas, desde - timedelta(days=1))
    final = _activos_en(personas, hasta)
    promedio = (inicial + final) / 2

    por_area = {}
    for p in personas:
        area = p.get("area") or "Sin asignar"
        a = por_area.setdefault(area, {"area": area, "bajas": 0, "plantilla_final": 0})
        if p in en_periodo:
            a["bajas"] += 1
        if (p["ingreso"] is None or p["ingreso"] <= hasta) and (p["baja"] is None or p["baja"] > hasta):
            a["plantilla_final"] += 1
    for a in por_area.values():
        base = a["plantilla_final"] + a["bajas"]
        a["rotacion_pct"] = round(a["bajas"] / base * 100, 1) if base else 0.0

    por_tipo = {}
    for p in en_periodo:
        t = p.get("tipo_baja") or "otro"
        por_tipo[t] = por_tipo.get(t, 0) + 1

    return {
        "desde": desde.isoformat(), "hasta": hasta.isoformat(),
        "plantilla_inicial": inicial, "plantilla_final": final,
        "altas": sum(m["altas"] for m in por_mes), "bajas": len(en_periodo),
        "rotacion_pct": round(len(en_periodo) / promedio * 100, 1) if promedio else 0.0,
        "por_mes": por_mes,
        "por_area": sorted(por_area.values(), key=lambda a: (-a["bajas"], a["area"])),
        "por_tipo": por_tipo,
    }
