"""Tarea diaria (GitHub Actions): descarga lo nuevo de Garmin, lo une a lo anterior y lo deja cifrado.

Entradas (variables de entorno, secretos de GitHub):
  GARMIN_TOKENS    sesion de Garmin inicial (contenido de garmin_tokens.json)
  DATA_PASSPHRASE  clave con la que se cifran los datos
Salida: data/<persona>.enc (datos cifrados) y data/<persona>.tokens.enc (sesion renovada, cifrada).
No imprime datos personales: solo recuentos.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from cifrado import cifrar, descifrar

SYNC = Path(__file__).resolve().parent
RAIZ = SYNC.parent
SLUG = os.getenv("SLUG", "kique")
CLAVE = os.environ.get("DATA_PASSPHRASE", "").strip()
DIAS = os.getenv("DIAS", "14")

if not CLAVE:
    print("FALTA el secreto DATA_PASSPHRASE.")
    sys.exit(2)

TOK_DIR = SYNC / "data" / ".tokens"
TOK_FILE = TOK_DIR / "garmin_tokens.json"
TOK_ENC = RAIZ / "data" / f"{SLUG}.tokens.enc"
DATOS_ENC = RAIZ / "data" / f"{SLUG}.enc"


def leer_enc(ruta: Path):
    if not ruta.exists():
        return None
    try:
        return descifrar(ruta.read_text(encoding="utf-8"), CLAVE)
    except Exception as e:  # clave distinta o archivo danado
        print(f"No se pudo descifrar {ruta.name} ({type(e).__name__}).")
        return None


def sincronizar() -> bool:
    """Prueba primero la sesion renovada guardada en el repositorio y, si falla, la del secreto."""
    candidatos = []
    previa = leer_enc(TOK_ENC)
    if previa:
        candidatos.append(("sesion guardada", previa))
    secreto = os.getenv("GARMIN_TOKENS", "").strip()
    if secreto:
        candidatos.append(("secreto inicial", secreto))
    if not candidatos:
        print("No hay ninguna sesion de Garmin (falta el secreto GARMIN_TOKENS).")
        return False
    TOK_DIR.mkdir(parents=True, exist_ok=True)
    for nombre, texto in candidatos:
        TOK_FILE.write_text(texto, encoding="utf-8")
        r = subprocess.run(
            [sys.executable, "sync.py", "--days", DIAS, "--sleep", "1.0"], cwd=SYNC, capture_output=True, text=True
        )
        if r.returncode == 0:
            print(f"Sincronizado con la {nombre}.")
            return True
        print(f"La {nombre} no ha funcionado (codigo {r.returncode}).")
    return False


def unir(previo: dict, nuevo: dict) -> dict:
    out = dict(previo)  # conserva campos extra (por ejemplo el perfil)
    por_actividad = {a["activityId"]: a for a in previo.get("actividades", [])}
    for a in nuevo.get("actividades", []):
        # lo nuevo manda, pero no pierde lo que ya se tenia (por ejemplo los parciales) si esta vez no ha llegado
        ant = por_actividad.get(a["activityId"], {})
        por_actividad[a["activityId"]] = {**ant, **{k: v for k, v in a.items() if v is not None}}
    out["actividades"] = sorted(por_actividad.values(), key=lambda a: (a.get("fecha") or "", a["activityId"]))
    for clave in ("sueno", "diario"):
        por_fecha = {x["fecha"]: x for x in previo.get(clave, [])}
        por_fecha.update({x["fecha"]: x for x in nuevo.get(clave, [])})
        out[clave] = [por_fecha[f] for f in sorted(por_fecha)]
    out["generatedAt"] = nuevo["generatedAt"]
    return out


def main():
    if not sincronizar():
        print("RESULTADO: sin sincronizar. Los datos publicados no se tocan.")
        sys.exit(1)

    salida = SYNC / "nuevo.json"
    r = subprocess.run([sys.executable, "export_for_runcoach.py", "--output", str(salida)], cwd=SYNC, capture_output=True, text=True)
    if r.returncode != 0 or not salida.exists():
        print("La exportacion ha fallado.")
        sys.exit(1)
    nuevo = json.loads(salida.read_text(encoding="utf-8"))

    previo_txt = leer_enc(DATOS_ENC)
    previo = json.loads(previo_txt) if previo_txt else {}
    final = unir(previo, nuevo)

    DATOS_ENC.parent.mkdir(parents=True, exist_ok=True)
    DATOS_ENC.write_text(cifrar(json.dumps(final, ensure_ascii=False), CLAVE), encoding="utf-8")

    # guarda la sesion renovada por si Garmin la ha cambiado
    if TOK_FILE.exists():
        actual = TOK_FILE.read_text(encoding="utf-8")
        if actual != leer_enc(TOK_ENC):
            TOK_ENC.write_text(cifrar(actual, CLAVE), encoding="utf-8")
            print("Sesion de Garmin renovada y guardada.")

    print(
        f"RESULTADO OK: {len(final['actividades'])} actividades, {len(final['sueno'])} dias de sueno, "
        f"{len(final['diario'])} dias de resumen (nuevos del dia: {len(nuevo['actividades'])} actividades en el periodo)."
    )


if __name__ == "__main__":
    main()
