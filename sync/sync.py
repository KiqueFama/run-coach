import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta

from garmin_client import get_client
from db import get_conn


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _extract_pairs(raw_array):
    """Normaliza los distintos formatos [ts, value] / [ts, status, value, version]
    que usa Garmin para las series intradia."""
    pairs = []
    if not raw_array:
        return pairs
    for row in raw_array:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        ts = row[0]
        value = row[-2] if len(row) >= 4 else row[1]
        if ts is None or value is None:
            continue
        pairs.append((int(ts), value))
    return pairs


def sync_activities(client, conn, start: date, end: date):
    print(f"Sincronizando actividades {start} -> {end} ...")
    try:
        activities = client.get_activities_by_date(start.isoformat(), end.isoformat())
    except Exception as e:
        print(f"  ! error obteniendo actividades: {e}", file=sys.stderr)
        return

    cur = conn.cursor()
    for act in activities:
        activity_type = (act.get("activityType") or {}).get("typeKey")
        cur.execute(
            """
            INSERT INTO activities (
                activity_id, name, activity_type, start_time, duration_sec,
                distance_m, calories, avg_hr, max_hr, avg_speed_mps,
                elevation_gain_m, training_effect_aerobic, training_effect_anaerobic,
                raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(activity_id) DO UPDATE SET
                name=excluded.name,
                activity_type=excluded.activity_type,
                start_time=excluded.start_time,
                duration_sec=excluded.duration_sec,
                distance_m=excluded.distance_m,
                calories=excluded.calories,
                avg_hr=excluded.avg_hr,
                max_hr=excluded.max_hr,
                avg_speed_mps=excluded.avg_speed_mps,
                elevation_gain_m=excluded.elevation_gain_m,
                training_effect_aerobic=excluded.training_effect_aerobic,
                training_effect_anaerobic=excluded.training_effect_anaerobic,
                raw_json=excluded.raw_json
            """,
            (
                act.get("activityId"),
                act.get("activityName"),
                activity_type,
                act.get("startTimeLocal"),
                act.get("duration"),
                act.get("distance"),
                act.get("calories"),
                act.get("averageHR"),
                act.get("maxHR"),
                act.get("averageSpeed"),
                act.get("elevationGain"),
                act.get("aerobicTrainingEffect"),
                act.get("anaerobicTrainingEffect"),
                json.dumps(act),
            ),
        )
    conn.commit()
    print(f"  {len(activities)} actividades sincronizadas.")
    sync_splits(client, conn, activities)


def sync_splits(client, conn, activities, pausa=0.7):
    """Parciales (un tramo por km) de las carreras. Solo se piden los que aun no estan guardados."""
    cur = conn.cursor()
    hechos = {r[0] for r in cur.execute("SELECT activity_id FROM splits")}
    pend = [
        a for a in activities
        if "running" in ((a.get("activityType") or {}).get("typeKey") or "") and a.get("activityId") not in hechos
    ]
    nuevos = 0
    for act in pend:
        try:
            s = client.get_activity_splits(act["activityId"]) or {}
        except Exception as e:
            print(f"  ! parciales de {act['activityId']}: {type(e).__name__}", file=sys.stderr)
            continue
        laps = [
            [
                round(l.get("distance") or 0),
                round(l.get("duration") or 0, 1),
                l.get("averageHR"),
                round(l.get("elevationGain") or 0),
                round(l["averageRunCadence"], 1) if l.get("averageRunCadence") else None,
                round(l["strideLength"], 1) if l.get("strideLength") else None,
            ]
            for l in (s.get("lapDTOs") or [])
            if (l.get("distance") or 0) > 0
        ]
        if laps:
            cur.execute("INSERT OR REPLACE INTO splits (activity_id, splits_json) VALUES (?, ?)", (act["activityId"], json.dumps(laps)))
            nuevos += 1
        time.sleep(pausa)
    conn.commit()
    print(f"  Parciales: {nuevos} carreras nuevas.")


def sync_day(client, conn, d: date):
    ds = d.isoformat()
    cur = conn.cursor()

    # --- Sleep ---
    try:
        sleep = client.get_sleep_data(ds)
        dto = (sleep or {}).get("dailySleepDTO") or {}
        if dto.get("sleepTimeSeconds") is not None or dto:
            score = None
            scores = dto.get("sleepScores") or {}
            if isinstance(scores, dict):
                overall = scores.get("overall") or {}
                score = overall.get("value")
            cur.execute(
                """
                INSERT INTO sleep (date, total_sleep_sec, deep_sec, light_sec,
                    rem_sec, awake_sec, sleep_score, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    total_sleep_sec=excluded.total_sleep_sec,
                    deep_sec=excluded.deep_sec,
                    light_sec=excluded.light_sec,
                    rem_sec=excluded.rem_sec,
                    awake_sec=excluded.awake_sec,
                    sleep_score=excluded.sleep_score,
                    raw_json=excluded.raw_json
                """,
                (
                    ds,
                    dto.get("sleepTimeSeconds"),
                    dto.get("deepSleepSeconds"),
                    dto.get("lightSleepSeconds"),
                    dto.get("remSleepSeconds"),
                    dto.get("awakeSleepSeconds"),
                    score,
                    json.dumps(sleep),
                ),
            )
    except Exception as e:
        print(f"  ! {ds} sleep: {e}", file=sys.stderr)

    # --- Daily summary / stats ---
    try:
        stats = client.get_stats(ds)
        if stats:
            cur.execute(
                """
                INSERT INTO daily_summary (date, steps, calories_total, calories_active,
                    resting_hr, avg_stress, floors_climbed, distance_m, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    steps=excluded.steps,
                    calories_total=excluded.calories_total,
                    calories_active=excluded.calories_active,
                    resting_hr=excluded.resting_hr,
                    avg_stress=excluded.avg_stress,
                    floors_climbed=excluded.floors_climbed,
                    distance_m=excluded.distance_m,
                    raw_json=excluded.raw_json
                """,
                (
                    ds,
                    stats.get("totalSteps"),
                    stats.get("totalKilocalories"),
                    stats.get("activeKilocalories"),
                    stats.get("restingHeartRate"),
                    stats.get("averageStressLevel"),
                    stats.get("floorsAscended"),
                    stats.get("totalDistanceMeters"),
                    json.dumps(stats),
                ),
            )
    except Exception as e:
        print(f"  ! {ds} stats: {e}", file=sys.stderr)

    # --- Heart rate intraday ---
    try:
        hr = client.get_heart_rates(ds)
        pairs = _extract_pairs((hr or {}).get("heartRateValues"))
        for ts, value in pairs:
            cur.execute(
                "INSERT OR REPLACE INTO heart_rate_intraday (date, ts, value) VALUES (?, ?, ?)",
                (ds, ts, value),
            )
    except Exception as e:
        print(f"  ! {ds} heart_rates: {e}", file=sys.stderr)

    # --- Stress intraday ---
    try:
        stress = client.get_stress_data(ds)
        pairs = _extract_pairs((stress or {}).get("stressValuesArray"))
        for ts, value in pairs:
            cur.execute(
                "INSERT OR REPLACE INTO stress_intraday (date, ts, value) VALUES (?, ?, ?)",
                (ds, ts, value),
            )
    except Exception as e:
        print(f"  ! {ds} stress: {e}", file=sys.stderr)

    # --- Body battery intraday ---
    try:
        bb = client.get_body_battery(ds, ds)
        entries = bb if isinstance(bb, list) else [bb]
        for entry in entries:
            pairs = _extract_pairs((entry or {}).get("bodyBatteryValuesArray"))
            for ts, value in pairs:
                cur.execute(
                    "INSERT OR REPLACE INTO body_battery_intraday (date, ts, value) VALUES (?, ?, ?)",
                    (ds, ts, value),
                )
    except Exception as e:
        print(f"  ! {ds} body_battery: {e}", file=sys.stderr)

    cur.execute(
        "INSERT OR REPLACE INTO sync_log (date, dataset, synced_at) VALUES (?, 'day', ?)",
        (ds, datetime.utcnow().isoformat()),
    )
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Sincroniza datos de Garmin Connect a SQLite local.")
    parser.add_argument("--days", type=int, default=30, help="Numero de dias hacia atras a sincronizar (por defecto 30).")
    parser.add_argument("--start-date", type=str, default=None, help="Fecha de inicio YYYY-MM-DD (anula --days).")
    parser.add_argument("--end-date", type=str, default=None, help="Fecha de fin YYYY-MM-DD (por defecto hoy).")
    parser.add_argument("--sleep", type=float, default=0.5, help="Segundos de pausa entre dias para no saturar la API.")
    parser.add_argument("--persona", type=str, default=None, help="Nombre de la persona (usa .env.<persona> y data/<persona>/). Sin esto, usa .env y data/ (perfil por defecto).")
    args = parser.parse_args()

    end = date.fromisoformat(args.end_date) if args.end_date else date.today()
    if args.start_date:
        start = date.fromisoformat(args.start_date)
    else:
        start = end - timedelta(days=args.days - 1)

    print(f"Rango a sincronizar: {start} -> {end}")

    client = get_client(args.persona)
    conn = get_conn(args.persona)

    sync_activities(client, conn, start, end)

    for d in daterange(start, end):
        print(f"Dia {d.isoformat()} ...")
        sync_day(client, conn, d)
        time.sleep(args.sleep)

    conn.close()
    print("Listo. Datos en data/garmin.db")


if __name__ == "__main__":
    main()
