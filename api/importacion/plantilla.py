# api/importacion/plantilla.py — genera la plantilla .xlsx de carga masiva.
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.comments import Comment

from .columnas import COLUMNAS, GRUPOS

FILAS_DATOS = 1000


def generar_plantilla(areas=()):
    wb = Workbook()
    ws = wb.active
    ws.title = "Empleados"

    # Fila 1: grupos (celdas combinadas con color); fila 2: encabezados.
    borde = Border(bottom=Side(style="thin", color="94A3B8"))
    i = 0
    while i < len(COLUMNAS):
        grupo = COLUMNAS[i][2]
        j = i
        while j + 1 < len(COLUMNAS) and COLUMNAS[j + 1][2] == grupo:
            j += 1
        titulo, fondo, texto = GRUPOS[grupo]
        ws.merge_cells(start_row=1, start_column=i + 1, end_row=1, end_column=j + 1)
        c = ws.cell(row=1, column=i + 1, value=titulo)
        c.font = Font(bold=True, color=texto, size=11)
        c.alignment = Alignment(horizontal="center", vertical="center")
        for col in range(i + 1, j + 2):
            ws.cell(row=1, column=col).fill = PatternFill("solid", fgColor=fondo)
        i = j + 1

    for idx, (clave, encabezado, grupo, obligatoria, ayuda) in enumerate(COLUMNAS, start=1):
        _, fondo, texto = GRUPOS[grupo]
        c = ws.cell(row=2, column=idx, value=f"{encabezado} *" if obligatoria else encabezado)
        c.font = Font(bold=True, color=texto)
        c.fill = PatternFill("solid", fgColor=fondo)
        c.alignment = Alignment(wrap_text=True, vertical="center")
        c.border = borde
        if ayuda:
            c.comment = Comment(ayuda, "Sistema de Empleados")
        ws.column_dimensions[get_column_letter(idx)].width = max(14, min(32, len(encabezado) + 6))
        # Texto (no número) para que Excel no se coma ceros a la izquierda.
        if clave in ("NumeroEmpleado", "JefeNumero", "Celular", "CURP", "RFC", "NSS", "CLABE", "CuentaBancaria"):
            for fila in range(3, FILAS_DATOS + 3):
                ws.cell(row=fila, column=idx).number_format = "@"
        if clave in ("FecNacimiento", "FechaIngreso"):
            for fila in range(3, FILAS_DATOS + 3):
                ws.cell(row=fila, column=idx).number_format = "yyyy-mm-dd"
    ws.row_dimensions[1].height = 22
    ws.row_dimensions[2].height = 34
    ws.freeze_panes = "C3"

    # Listas desplegables (en una hoja oculta para que quepan muchas áreas).
    listas = wb.create_sheet("Listas")
    listas.sheet_state = "hidden"
    opciones = {
        "TipoContrato": ["Firmado digitalmente", "Firmado en papel", "Pendiente de firma"],
        "Regimen": ["Nómina", "Asimilados", "Honorarios"],
        "Area": sorted({a for a in areas if a}),
    }
    for col, (clave, valores) in enumerate(opciones.items(), start=1):
        for fila, v in enumerate(valores, start=1):
            listas.cell(row=fila, column=col, value=v)
        if not valores:
            continue
        letra = get_column_letter(col)
        idx = next(i for i, c in enumerate(COLUMNAS, start=1) if c[0] == clave)
        dv = DataValidation(type="list", formula1=f"=Listas!${letra}$1:${letra}${len(valores)}",
                            allow_blank=True, showErrorMessage=(clave != "Area"))
        if clave == "Area":
            dv.errorStyle = "information"   # puede escribir un área nueva
        ws.add_data_validation(dv)
        dv.add(f"{get_column_letter(idx)}3:{get_column_letter(idx)}{FILAS_DATOS + 2}")

    # Hoja de instrucciones (primera en abrirse).
    ins = wb.create_sheet("Instrucciones", 0)
    ins.column_dimensions["A"].width = 30
    ins.column_dimensions["B"].width = 90
    ins["A1"] = "Carga masiva de empleados"
    ins["A1"].font = Font(bold=True, size=16, color="1E3A8A")
    pasos = [
        "1. Llena la hoja «Empleados»: una fila por persona, desde la fila 3.",
        "2. Las columnas con * son obligatorias: Número de empleado, Nombre(s) y Apellido paterno.",
        "3. Si un número de empleado ya existe en el sistema, esa fila ACTUALIZA a la persona (no la duplica). Las celdas vacías no borran nada.",
        "4. El jefe se indica con SU número de empleado; así se arma el organigrama solo.",
        "5. Sube el archivo en Empleados / RH → Carga masiva. Antes de guardar verás qué filas están listas y cuáles tienen errores.",
    ]
    for n, p in enumerate(pasos, start=3):
        ins.cell(row=n, column=1, value=p).alignment = Alignment(wrap_text=True)
        ins.merge_cells(start_row=n, start_column=1, end_row=n, end_column=2)
    ins.cell(row=9, column=1, value="Columna").font = Font(bold=True)
    ins.cell(row=9, column=2, value="Qué poner").font = Font(bold=True)
    for n, (clave, encabezado, grupo, obligatoria, ayuda) in enumerate(COLUMNAS, start=10):
        ins.cell(row=n, column=1, value=f"{encabezado}{' *' if obligatoria else ''}")
        ins.cell(row=n, column=2, value=ayuda or "—").alignment = Alignment(wrap_text=True)
    wb.active = 1

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
