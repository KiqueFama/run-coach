import argparse
import json
from datetime import datetime, timezone
from statistics import mean

from db import get_conn


DEFAULT_SLUG = "kique"  # nombre (en minusculas, sin espacios) de la persona del perfil por defecto


def export(output_path: str, persona=None):
    conn = get_conn(persona)
    cur = conn.cursor()

    actividades = []
    for row in cur.execute(
        """
        SELECT activity_id, name, activity_type, start_time, duration_sec,
               distance_m, calories, avg_hr, max_hr, avg_speed_mps, elevation_gain_m,
               training_effect_aerobic, training_effect_anaerobic, raw_json
        FROM activities
        ORDER BY start_time
        """
    ):
        (
            activity_id, name, activity_type, start_time, duration_sec,
            distance_m, calories, avg_hr, max_hr, avg_speed_mps, elevation_gain_m,
            te_aerobic, te_anaerobic, raw_json,
        ) = row
        try:
            raw = json.loads(raw_json) if raw_json else {}
        except Exception:
            raw = {}
        cadencia = raw.get("averageRunningCadenceInStepsPerMinute")
        zancada = raw.get("avgStrideLength")
        actividades.append(
            {
                "activityId": activity_id,
                "nombre": name,
                "deporte": activity_type,
                "fecha": (start_time or "")[:10],
                "duracionSec": duration_sec,
                "distanciaM": distance_m,
                "calorias": calories,
                "fc": avg_hr,
                "fcMax": max_hr,
                "velocidadMps": avg_speed_mps,
                "desnivelM": elevation_gain_m,
                "teAerobico": te_aerobic,
                "teAnaerobico": te_anaerobic,
                "cadencia": round(cadencia, 1) if cadencia else None,
                "zancadaCm": round(zancada, 1) if zancada else None,
            }
        )

    resting_hr_by_date = {}
    diario = {}
    for row in cur.execute(
        """
        SELECT date, steps, resting_hr, avg_stress, calories_total, calories_active
        FROM daily_summary
        """
    ):
        fecha, steps, resting_hr, avg_stress, cal_total, cal_active = row
        resting_hr_by_date[fecha] = resting_hr
        diario[fecha] = {
            "fecha": fecha,
            "pasos": steps,
            "fcReposo": resting_hr,
            "estres": avg_stress,
            "caloriasTotal": cal_total,
            "caloriasActivas": cal_active,
        }

    bb_by_date = {}
    for fecha, value in cur.execute("SELECT date, value FROM body_battery_intraday"):
        bb_by_date.setdefault(fecha, []).append(value)
    for fecha, d in diario.items():
        vals = bb_by_date.get(fecha)
        d["bodyBatteryValor"] = round(mean(vals), 1) if vals else None

    sueno = []
    for fecha, sleep_score, total_sec in cur.execute("SELECT date, sleep_score, total_sleep_sec FROM sleep"):
        sueno.append(
            {
                "fecha": fecha,
                "puntuacion": sleep_score,
                "fcReposo": resting_hr_by_date.get(fecha),
                "horas": round(total_sec / 3600, 2) if total_sec else None,
            }
        )
    sueno.sort(key=lambda x: x["fecha"])

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "actividades": actividades,
        "sueno": sueno,
        "diario": sorted(diario.values(), key=lambda x: x["fecha"]),
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(
        f"Exportado {len(actividades)} actividades, {len(sueno)} dias de sueno, "
        f"{len(payload['diario'])} dias de resumen diario -> {output_path}"
    )

    from dotenv import load_dotenv
    import os, shutil
    from pathlib import Path
    load_dotenv(Path(__file__).parent / ".env")

    # Archivo de datos que la app carga sola al abrirse: datos_<persona>.js junto al HTML
    slug = (persona or DEFAULT_SLUG).lower().replace(" ", "")
    app_dir = Path(os.getenv("RUNCOACH_APP_DIR") or (Path(__file__).parent.parent / "run-coach-10k-export" / "run-coach-10k-export"))
    if app_dir.exists():
        js = app_dir / f"datos_{slug}.js"
        with open(js, "w", encoding="utf-8") as f:
            f.write("window.RUNCOACH_DATOS = window.RUNCOACH_DATOS || {};\n")
            f.write(f"window.RUNCOACH_DATOS[{json.dumps(slug)}] = ")
            json.dump(payload, f, ensure_ascii=False)
            f.write(";\n")
        print(f"Datos para la app (carga automatica): {js}")
    else:
        print(f"Carpeta de la app no encontrada ({app_dir}); define RUNCOACH_APP_DIR en .env")

    # Copia opcional a una carpeta sincronizada (OneDrive/Drive) para elegir el archivo desde el movil
    destino = os.getenv("RUNCOACH_EXPORT_PATH")
    if destino:
        try:
            Path(destino).mkdir(parents=True, exist_ok=True)
            shutil.copy(output_path, Path(destino) / Path(output_path).name)
            print(f"Copiado tambien a {destino}")
        except Exception as e:
            print(f"No se pudo copiar a {destino}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Exporta garmin.db a JSON para Run Coach 10K.")
    parser.add_argument("--output", default="runcoach_import.json", help="Ruta del JSON de salida.")
    parser.add_argument("--persona", default=None, help="Persona (data/<persona>/garmin.db). Sin esto, el perfil por defecto.")
    args = parser.parse_args()
    export(args.output, args.persona)


if __name__ == "__main__":
    main()
