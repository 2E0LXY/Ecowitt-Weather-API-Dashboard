#!/usr/bin/env python3
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HOME = Path("/home/daren/raspberry-noaa-v2")
CONF = Path("/home/daren/.noaa-v2.conf")
DB = HOME / "db/panel.db"
LOG = Path("/var/log/raspberry-noaa-v2/output.log")
IMAGE_DIR = Path("/srv/images")
AUDIO_DIR = Path("/srv/audio/meteor")
OUTPUT = Path("/var/www/wx-new/public/receiver_diagnostics.json")
LOCAL_TZ = ZoneInfo("Europe/London")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def run(command, timeout=5):
    try:
        proc = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except Exception as exc:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(exc)}


def parse_conf():
    values = {}
    if not CONF.exists():
        return values
    for line in CONF.read_text(errors="ignore").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def parse_time(line):
    m = re.search(r"\[(\d{2}:\d{2}:\d{2}) - (\d{2}/\d{2}/\d{4})\]", line)
    if m:
        dt = datetime.strptime(f"{m.group(2)} {m.group(1)}", "%d/%m/%Y %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc).timestamp()
    m = re.match(r"(\d{2}-\d{2}-\d{4}) (\d{2}:\d{2})", line)
    if m:
        dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%d-%m-%Y %H:%M")
        return dt.replace(tzinfo=LOCAL_TZ).timestamp()
    return None


def load_log_entries():
    entries = []
    if not LOG.exists():
        return entries
    for raw in LOG.read_text(errors="ignore").splitlines():
        clean = ANSI_RE.sub("", raw)
        ts = parse_time(clean)
        if ts is not None:
            entries.append((ts, clean))
    return entries


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def mean(values):
    values = [v for v in values if v is not None and math.isfinite(v)]
    return sum(values) / len(values) if values else None


def age_payload(path):
    if not path.exists():
        return {"path": str(path), "exists": False, "age_hours": None, "status": "missing"}
    age_hours = max(0, (time.time() - path.stat().st_mtime) / 3600)
    status = "ok"
    if age_hours > 72:
        status = "critical"
    elif age_hours > 24:
        status = "warning"
    return {
        "path": str(path),
        "exists": True,
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "age_hours": round(age_hours, 1),
        "status": status,
    }


def image_inventory(base):
    images = sorted(IMAGE_DIR.glob(f"{base}*.jpg"))
    weather = [p for p in images if "polar-" not in p.name and "spectrogram" not in p.name]
    projected = [p for p in weather if "projected" in p.name]
    corrected = [p for p in weather if "corrected" in p.name]
    return {
        "weather_images": len(weather),
        "projected_images": len(projected),
        "corrected_images": len(corrected),
        "files": [p.name for p in weather],
        "total_bytes": sum(p.stat().st_size for p in weather if p.exists()),
    }


def pass_rows(limit=25):
    if not DB.exists():
        return []
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT d.id, d.pass_start, d.file_path, d.gain, d.daylight_pass,
                   p.sat_name, p.pass_end, p.max_elev, p.pass_start_azimuth,
                   p.azimuth_at_max, p.direction
            FROM decoded_passes d
            LEFT JOIN predict_passes p ON p.pass_start = d.pass_start
            WHERE d.file_path LIKE 'METEOR-%'
            ORDER BY d.pass_start DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def pass_log_slice(entries, row):
    start = int(row.get("pass_start") or 0)
    end = int(row.get("pass_end") or start + 900)
    return [line for ts, line in entries if start - 180 <= ts <= end + 1800]


def analyse_pass(row, entries):
    base = row["file_path"]
    lines = pass_log_slice(entries, row)
    snrs = []
    peaks = []
    bers = []
    viterbi = []
    deframers = []
    channels = {}
    fill_missing = None
    max_fill_lines = None
    saved_products = []

    for line in lines:
        m = re.search(r"SNR\s*:\s*([0-9.]+)dB,\s*Peak SNR:\s*([0-9.]+)dB", line)
        if m:
            snrs.append(float(m.group(1)))
            peaks.append(float(m.group(2)))
        m = re.search(r"Viterbi\s*:\s*(SYNCED|NOSYNC)\s*BER\s*:\s*([0-9.]+),\s*Deframer\s*:\s*(SYNCED|NOSYNC)", line)
        if m:
            viterbi.append(m.group(1))
            bers.append(float(m.group(2)))
            deframers.append(m.group(3))
        m = re.search(r"MSU-MR Channel\s+(\d+)\s+Lines\s+:\s+(\d+)", line)
        if m:
            channels[m.group(1)] = int(m.group(2))
        m = re.search(r"- fill_missing\s*:\s*(\w+)", line)
        if m:
            fill_missing = m.group(1).lower() == "true"
        m = re.search(r"- max_fill_lines\s*:\s*(\d+)", line)
        if m:
            max_fill_lines = int(m.group(1))
        m = re.search(r"Saving .*/([^/]+\.(?:png|jpg))", line)
        if m:
            saved_products.append(m.group(1))

    inv = image_inventory(base)
    cadu = AUDIO_DIR / f"{base}.cadu"
    cadu_size = cadu.stat().st_size if cadu.exists() else 0
    cadu_frames = cadu_size // 1024 if cadu_size else 0
    avg_snr = mean(snrs)
    avg_ber = mean(bers)
    peak_snr = max(peaks) if peaks else None
    sync_ratio = deframers.count("SYNCED") / len(deframers) if deframers else None
    positive_lines = [v for v in channels.values() if v > 0]
    max_lines = max(positive_lines) if positive_lines else 0
    min_lines = min(positive_lines) if positive_lines else 0
    line_completeness = (min_lines / max_lines) if max_lines else None
    estimated_missing_lines = sum(max_lines - v for v in positive_lines) if max_lines else None

    snr_score = clamp((avg_snr or 0) / 18) * 30
    ber_score = (1 - clamp((avg_ber or 0) / 0.08)) * 25 if avg_ber is not None else 10
    sync_score = (sync_ratio if sync_ratio is not None else 0.5) * 20
    line_score = (line_completeness if line_completeness is not None else 0.5) * 15
    product_score = clamp(inv["weather_images"] / 6) * 10
    score = round(snr_score + ber_score + sync_score + line_score + product_score)

    if score >= 82:
        label = "Excellent"
    elif score >= 68:
        label = "Good"
    elif score >= 50:
        label = "Fair"
    else:
        label = "Poor"

    reasons = []
    max_elev = row.get("max_elev") or 0
    if avg_snr is not None and avg_snr < 7:
        reasons.append(f"Low average SNR ({avg_snr:.1f} dB) made the signal weak.")
    if avg_ber is not None and avg_ber > 0.05:
        reasons.append(f"High average Viterbi BER ({avg_ber:.3f}) means many bit corrections were needed.")
    if sync_ratio is not None and sync_ratio < 0.8:
        reasons.append(f"Deframer sync was lost for about {(1 - sync_ratio) * 100:.0f}% of samples.")
    if line_completeness is not None and line_completeness < 0.92:
        reasons.append("One or more MSU-MR channels had fewer lines, so SatDump had to fill/bridge gaps.")
    if max_elev and max_elev < 30:
        reasons.append(f"Low pass elevation ({max_elev} deg) limits signal strength and pass duration.")
    if inv["weather_images"] < 3:
        reasons.append("Only a small set of weather products was generated.")
    if not reasons:
        reasons.append("Decode looks healthy: good sync, usable BER/SNR, and a full set of weather products.")

    return {
        "pass_id": row.get("id"),
        "file_path": base,
        "satellite": row.get("sat_name"),
        "pass_start": row.get("pass_start"),
        "pass_start_local": datetime.fromtimestamp(row.get("pass_start"), LOCAL_TZ).isoformat() if row.get("pass_start") else None,
        "pass_end": row.get("pass_end"),
        "max_elevation": row.get("max_elev"),
        "pass_start_azimuth": row.get("pass_start_azimuth"),
        "azimuth_at_max": row.get("azimuth_at_max"),
        "direction": row.get("direction"),
        "gain": row.get("gain"),
        "score": score,
        "label": label,
        "why": reasons[0],
        "reasons": reasons,
        "satdump": {
            "avg_snr_db": round(avg_snr, 2) if avg_snr is not None else None,
            "peak_snr_db": round(peak_snr, 2) if peak_snr is not None else None,
            "avg_ber": round(avg_ber, 5) if avg_ber is not None else None,
            "max_ber": round(max(bers), 5) if bers else None,
            "deframer_sync_percent": round((sync_ratio or 0) * 100, 1) if sync_ratio is not None else None,
            "viterbi_sync_percent": round((viterbi.count("SYNCED") / len(viterbi)) * 100, 1) if viterbi else None,
            "fill_missing": fill_missing,
            "max_fill_lines": max_fill_lines,
            "channel_lines": channels,
            "saved_product_count": len(set(saved_products)),
        },
        "packet_quality": {
            "cadu_bytes": cadu_size,
            "estimated_cadu_frames": cadu_frames,
            "sync_loss_percent": round((1 - sync_ratio) * 100, 1) if sync_ratio is not None else None,
            "line_completeness_percent": round(line_completeness * 100, 1) if line_completeness is not None else None,
            "estimated_missing_lines": estimated_missing_lines,
            "note": "Missing-line count is estimated from SatDump sync/BER/channel-line output; SatDump did not emit an exact missing-packet counter in these logs.",
        },
        "images": inv,
    }


def band_elevation(value):
    if value is None:
        return "Unknown"
    if value >= 60:
        return "High (60+ deg)"
    if value >= 30:
        return "Medium (30-59 deg)"
    return "Low (<30 deg)"


def band_azimuth(value):
    if value is None:
        return "Unknown"
    value = value % 360
    if value >= 315 or value < 45:
        return "North"
    if value < 135:
        return "East"
    if value < 225:
        return "South"
    return "West"


def grouped_quality(passes, key_fn):
    groups = {}
    for item in passes:
        key = key_fn(item)
        groups.setdefault(key, []).append(item["score"])
    return [
        {"band": key, "count": len(scores), "avg_score": round(sum(scores) / len(scores), 1)}
        for key, scores in sorted(groups.items())
    ]


def receiver_health(conf, passes):
    usb = run(["lsusb"])
    processes = run(["pgrep", "-af", "satdump|receive_meteor|receive_noaa|rtl_fm"], timeout=3)
    active_capture = bool(processes["stdout"])
    disk = shutil.disk_usage("/")
    temp_path = Path("/sys/class/thermal/thermal_zone0/temp")
    temp_c = None
    if temp_path.exists():
        try:
            temp_c = round(int(temp_path.read_text().strip()) / 1000, 1)
        except Exception:
            temp_c = None
    high_elev = [p for p in passes if (p.get("max_elevation") or 0) >= 45 and p["satdump"].get("avg_snr_db") is not None]
    avg_high_snr = mean([p["satdump"]["avg_snr_db"] for p in high_elev])
    antenna_status = "unknown"
    if avg_high_snr is not None:
        antenna_status = "good" if avg_high_snr >= 10 else ("watch" if avg_high_snr >= 6 else "weak")
    return {
        "receiver_type": conf.get("RECEIVER_TYPE"),
        "rtl_sdr_usb_present": "RTL2838" in usb["stdout"] or "0bda:2838" in usb["stdout"],
        "active_capture": active_capture,
        "bias_tee": {
            "meteor_m2_3": conf.get("METEOR_M2_3_ENABLE_BIAS_TEE"),
            "meteor_m2_4": conf.get("METEOR_M2_4_ENABLE_BIAS_TEE"),
        },
        "gain": {
            "meteor_m2_3": conf.get("METEOR_M2_3_GAIN"),
            "meteor_m2_4": conf.get("METEOR_M2_4_GAIN"),
        },
        "antenna_inferred_status": antenna_status,
        "avg_high_elevation_snr_db": round(avg_high_snr, 2) if avg_high_snr is not None else None,
        "disk_root_percent_used": round((disk.used / disk.total) * 100, 1),
        "disk_root_free_gb": round(disk.free / (1024 ** 3), 1),
        "cpu_temp_c": temp_c,
        "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
        "chrony": run(["chronyc", "tracking"], timeout=4),
    }


def main():
    conf = parse_conf()
    entries = load_log_entries()
    passes = [analyse_pass(row, entries) for row in pass_rows(25)]
    tle_candidates = [
        Path("/home/daren/.config/satdump/satdump_tles.txt"),
        HOME / "tmp/weather.txt",
        HOME / "tmp/orbit.tle",
    ]
    tle_files = [age_payload(p) for p in tle_candidates]
    primary_tle = next((item for item in tle_files if item["exists"]), tle_files[0])
    payload = {
        "status": "ok",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "satdump": {
            "path": shutil.which("satdump") or "/usr/bin/satdump",
            "available": Path("/usr/bin/satdump").exists(),
            "decode_signals_used": [
                "SNR",
                "Peak SNR",
                "Viterbi BER",
                "Deframer sync",
                "MSU-MR channel line counts",
                "fill_missing/max_fill_lines",
                "generated product count",
                "CADU byte/frame estimate",
            ],
        },
        "tle": {"primary": primary_tle, "files": tle_files},
        "receiver_health": receiver_health(conf, passes),
        "quality_by_geometry": {
            "elevation": grouped_quality(passes, lambda p: band_elevation(p.get("max_elevation"))),
            "azimuth_at_max": grouped_quality(passes, lambda p: band_azimuth(p.get("azimuth_at_max"))),
        },
        "pass_diagnostics": passes,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(OUTPUT)


if __name__ == "__main__":
    main()
