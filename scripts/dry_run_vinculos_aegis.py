"""Dry-run de vínculos. No escribe y no abre Mongo aunque exista MONGO_URI."""
import json
import sys

from core.vinculo_identidad import plan_vinculos


def main(argv):
    if len(argv) != 2:
        print("Uso: python scripts/dry_run_vinculos_aegis.py archivo.json", file=sys.stderr)
        print("El JSON es una exportación local {usuarios, identidades}. No se aplica.", file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as archivo:
        datos = json.load(archivo)
    plan = plan_vinculos(datos.get("usuarios") or [], datos.get("identidades") or [])
    json.dump(plan, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
