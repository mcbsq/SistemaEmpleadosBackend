# api/importacion/columnas.py
# Definición ÚNICA de las columnas de la plantilla de carga masiva: la usa la
# generación del Excel, el lector y el validador, para que nunca se desfasen.
# (clave interna, encabezado visible, grupo, obligatoria, ayuda)

GRUPOS = {
    "personal":     ("Datos personales", "DBEAFE", "1E3A8A"),
    "laboral":      ("Datos laborales",  "D1FAE5", "065F46"),
    "identidad":    ("Identificación oficial", "FEF3C7", "92400E"),
    "compensacion": ("Sueldo y banco",   "EDE9FE", "5B21B6"),
    "acceso":       ("Acceso al sistema", "E0F2FE", "075985"),
}

COLUMNAS = [
    ("NumeroEmpleado",  "Número de empleado",  "laboral",      True,  "Único por persona. Si ya existe, la fila ACTUALIZA a esa persona en vez de duplicarla."),
    ("Nombre",          "Nombre(s)",           "personal",     True,  ""),
    ("ApelPaterno",     "Apellido paterno",    "personal",     True,  ""),
    ("ApelMaterno",     "Apellido materno",    "personal",     False, ""),
    ("FecNacimiento",   "Fecha de nacimiento", "personal",     False, "Formato fecha de Excel o AAAA-MM-DD."),
    ("CorreoPersonal",  "Correo personal",     "personal",     False, ""),
    ("Celular",         "Celular",             "personal",     False, "10 dígitos."),
    ("Puesto",          "Puesto",              "laboral",      False, ""),
    ("Area",            "Área",                "laboral",      False, "Si el área no existe, se crea."),
    ("JefeNumero",      "Núm. de empleado del jefe", "laboral", False, "El jefe puede venir en el mismo archivo o existir ya en el sistema."),
    ("FechaIngreso",    "Fecha de ingreso",    "laboral",      False, ""),
    ("TipoContrato",    "Contrato",            "laboral",      False, "Firmado digitalmente / Firmado en papel / Pendiente de firma."),
    ("Regimen",         "Régimen",             "laboral",      False, "Nómina / Asimilados / Honorarios."),
    ("HoraEntrada",     "Hora de entrada",     "laboral",      False, "HH:MM, ej. 09:00."),
    ("HoraSalida",      "Hora de salida",      "laboral",      False, "HH:MM, ej. 18:00."),
    ("DiasLaborales",   "Días laborales",      "laboral",      False, "Ej. Lunes a viernes."),
    ("CURP",            "CURP",                "identidad",    False, "18 caracteres; se valida el dígito verificador."),
    ("RFC",             "RFC",                 "identidad",    False, "13 caracteres con homoclave."),
    ("NSS",             "NSS",                 "identidad",    False, "11 dígitos; se valida el dígito verificador."),
    ("SalarioDiario",   "Salario diario",      "compensacion", False, "Solo el número. El mensual se calcula solo (× 30.4)."),
    ("Banco",           "Banco",               "compensacion", False, ""),
    ("CLABE",           "CLABE",               "compensacion", False, "18 dígitos; se valida el dígito de control."),
    ("CuentaBancaria",  "Número de cuenta",    "compensacion", False, ""),
    ("CorreoTrabajo",   "Correo de trabajo",   "acceso",       False, "Con él se crea su cuenta para entrar al sistema (opcional al importar)."),
]

CONTRATOS = {"firmado digitalmente": "digital", "digital": "digital", "firmado en papel": "autografa",
             "papel": "autografa", "autografa": "autografa", "autógrafa": "autografa",
             "pendiente de firma": "pendiente", "pendiente": "pendiente"}
REGIMENES = {"nomina": "nomina", "nómina": "nomina", "asimilados": "asimilados",
             "asimilados a salarios": "asimilados", "honorarios": "prestador_servicios"}
