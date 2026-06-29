"""
frametime_harness.py — measure runlog.exe's real impact on Marathon's frame times.

The capture audit's recurring caveat was that "zero game-frame impact" is asserted,
not measured. This harness closes that gap. It drives Intel PresentMon (an ETW
front-end) to record the game's present timeline, then reports the metrics that
actually matter for "did we hurt the game":

  - PresentMode distribution — is the game on Hardware: Independent Flip (the cheap
    path) or did something (e.g. the always-on-top overlay) demote it to a Composed
    path? This is the single most important number for capture overhead.
  - Frame-time percentiles — mean, p50, p95, p99, p99.9, max (ms between presents),
    plus the derived "1% low" / "0.1% low" FPS gamers care about.
  - Dropped/duplicate present counts where PresentMon exposes them.

Two modes:

  capture   One timed capture of the current state → a stats table.
  compare   Guided A/B/C/... — you set up each scenario (runlog off, watching,
            recording, recording+overlay), the harness captures each for the same
            duration and prints a side-by-side delta table. This is how you prove
            a change (1440p30, overlay static dot, E-core pinning, …) moved — or
            did not move — the game's frame times.

PresentMon is NOT bundled (it's an Intel/GameTechDev tool). Download the latest
PresentMon-*-x64.exe from https://github.com/GameTechDev/PresentMon/releases and
either put it on PATH, drop it next to this script, or pass --presentmon PATH.
PresentMon needs an elevated (Administrator) console to read ETW.

This tool only observes; it never touches the recorder, the encoder, or any
game/runlog process. Safe to run anytime.

Usage:
  python frametime_harness.py capture --seconds 30
  python frametime_harness.py capture --process Marathon.exe --seconds 60 --keep-csv
  python frametime_harness.py compare --seconds 30 \
      --scenarios "runlog OFF" "watching" "recording 1440p30" "recording + overlay"
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

DEFAULT_PROCESS = "Marathon.exe"

# Frame-to-frame interval column, across PresentMon 1.x and 2.x CSV schemas.
FRAMETIME_COLUMNS = ("msBetweenPresents", "MsBetweenPresents", "FrameTime", "msBetweenDisplayChange")
PRESENTMODE_COLUMNS = ("PresentMode",)
DROPPED_COLUMNS = ("Dropped",)
# PresentMon binary name has churned across releases.
PRESENTMON_CANDIDATES = (
    "PresentMon.exe", "PresentMon-2.3.0-x64.exe", "PresentMon-2.2.0-x64.exe",
    "PresentMon-2.1.1-x64.exe", "PresentMon-2.0.0-x64.exe", "PresentMon-1.10.0-x64.exe",
    "presentmon.exe",
)


# --------------------------------------------------------------------------- #
# Discovery / environment
# --------------------------------------------------------------------------- #
def find_presentmon(explicit: str | None) -> str | None:
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    here = os.path.dirname(os.path.abspath(__file__))
    for name in PRESENTMON_CANDIDATES:
        cand = os.path.join(here, name)
        if os.path.isfile(cand):
            return cand
        on_path = shutil.which(name)
        if on_path:
            return on_path
    return None


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def process_running(image_name: str) -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/NH"],
            capture_output=True, text=True, timeout=5,
        ).stdout.lower()
        return image_name.lower() in out
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# PresentMon capture
# --------------------------------------------------------------------------- #
def run_presentmon(pm_exe: str, process: str, seconds: int) -> str | None:
    """Capture `seconds` of presents for `process` to a temp CSV; return its path."""
    fd, csv_path = tempfile.mkstemp(prefix="runlog_frametime_", suffix=".csv")
    os.close(fd)
    try:
        os.remove(csv_path)  # PresentMon refuses to overwrite; hand it a free path
    except OSError:
        pass

    # Flag spelling differs across PresentMon majors. 2.x: -process_name / -output_file
    # / -timed / -terminate_after_timed / -stop_existing_session. These are accepted
    # (ignored-if-unknown is NOT safe, so keep to the long-stable set).
    cmd = [
        pm_exe,
        "-process_name", process,
        "-output_file", csv_path,
        "-timed", str(seconds),
        "-terminate_after_timed",
        "-stop_existing_session",
        "-no_top",
    ]
    print(f"  capturing {seconds}s of {process} ...", flush=True)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds + 45)
    except subprocess.TimeoutExpired:
        print("  ! PresentMon timed out", file=sys.stderr)
        return None

    if not os.path.isfile(csv_path):
        # Surface PresentMon's own diagnostics — usually "not elevated" or bad flag.
        msg = (proc.stderr or proc.stdout or "").strip()
        print(f"  ! PresentMon produced no CSV (exit {proc.returncode}). {msg}", file=sys.stderr)
        return None
    return csv_path


def _col(header: list[str], candidates) -> str | None:
    lowered = {h.lower(): h for h in header}
    for c in candidates:
        if c.lower() in lowered:
            return lowered[c.lower()]
    return None


def parse_csv(csv_path: str) -> dict | None:
    with open(csv_path, "r", newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return None
        ft_col = _col(header, FRAMETIME_COLUMNS)
        pm_col = _col(header, PRESENTMODE_COLUMNS)
        drop_col = _col(header, DROPPED_COLUMNS)
        if ft_col is None:
            print(f"  ! no frame-time column in CSV header: {header}", file=sys.stderr)
            return None
        ft_idx = header.index(ft_col)
        pm_idx = header.index(pm_col) if pm_col else None
        drop_idx = header.index(drop_col) if drop_col else None

        frame_times: list[float] = []
        present_modes: dict[str, int] = {}
        dropped = 0
        for row in reader:
            if len(row) <= ft_idx:
                continue
            try:
                ft = float(row[ft_idx])
            except ValueError:
                continue
            if ft <= 0:
                continue
            frame_times.append(ft)
            if pm_idx is not None and len(row) > pm_idx:
                mode = row[pm_idx].strip() or "Unknown"
                present_modes[mode] = present_modes.get(mode, 0) + 1
            if drop_idx is not None and len(row) > drop_idx:
                try:
                    dropped += int(float(row[drop_idx]))
                except ValueError:
                    pass

    if not frame_times:
        return None
    return summarize(frame_times, present_modes, dropped)


def _pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return float("nan")
    k = min(len(sorted_vals) - 1, max(0, int(round(p / 100.0 * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def summarize(frame_times: list[float], present_modes: dict[str, int], dropped: int) -> dict:
    s = sorted(frame_times)
    mean = statistics.fmean(s)
    n = len(s)
    # "1% low" FPS = average FPS over the slowest 1% of frames (longest frame times).
    worst1 = s[int(n * 0.99):] or s[-1:]
    worst01 = s[int(n * 0.999):] or s[-1:]
    return {
        "frames": n,
        "mean_ms": mean,
        "mean_fps": 1000.0 / mean if mean else float("nan"),
        "p50_ms": _pct(s, 50),
        "p95_ms": _pct(s, 95),
        "p99_ms": _pct(s, 99),
        "p999_ms": _pct(s, 99.9),
        "max_ms": s[-1],
        "low1_fps": 1000.0 / statistics.fmean(worst1),
        "low01_fps": 1000.0 / statistics.fmean(worst01),
        "dropped": dropped,
        "present_modes": present_modes,
    }


def dominant_mode(stats: dict) -> str:
    modes = stats.get("present_modes") or {}
    if not modes:
        return "n/a"
    name, count = max(modes.items(), key=lambda kv: kv[1])
    pct = 100.0 * count / max(1, stats["frames"])
    return f"{name} ({pct:.0f}%)"


def print_stats(label: str, stats: dict) -> None:
    print(f"\n=== {label} ===")
    print(f"  frames captured : {stats['frames']}")
    print(f"  mean            : {stats['mean_ms']:.2f} ms  ({stats['mean_fps']:.1f} fps)")
    print(f"  p50 / p95 / p99 : {stats['p50_ms']:.2f} / {stats['p95_ms']:.2f} / {stats['p99_ms']:.2f} ms")
    print(f"  p99.9 / max     : {stats['p999_ms']:.2f} / {stats['max_ms']:.2f} ms")
    print(f"  1% / 0.1% low   : {stats['low1_fps']:.1f} / {stats['low01_fps']:.1f} fps")
    print(f"  dropped presents: {stats['dropped']}")
    print(f"  present mode    : {dominant_mode(stats)}")
    if len(stats.get("present_modes") or {}) > 1:
        for m, c in sorted(stats["present_modes"].items(), key=lambda kv: -kv[1]):
            print(f"        - {m}: {100.0 * c / stats['frames']:.1f}%")


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def preflight(pm_exe: str | None, process: str) -> bool:
    if pm_exe is None:
        print(
            "PresentMon not found. Download PresentMon-*-x64.exe from\n"
            "  https://github.com/GameTechDev/PresentMon/releases\n"
            "and put it on PATH, beside this script, or pass --presentmon PATH.",
            file=sys.stderr,
        )
        return False
    if not is_admin():
        print("! Not elevated — PresentMon needs an Administrator console to read ETW.", file=sys.stderr)
        # Not fatal on every Windows config, so continue and let PresentMon decide.
    if not process_running(process):
        print(f"! {process} does not appear to be running — start the game first.", file=sys.stderr)
        return False
    return True


def cmd_capture(args) -> int:
    pm_exe = find_presentmon(args.presentmon)
    if not preflight(pm_exe, args.process):
        return 2
    csv_path = run_presentmon(pm_exe, args.process, args.seconds)
    if not csv_path:
        return 1
    stats = parse_csv(csv_path)
    if not stats:
        print("! No frame data parsed.", file=sys.stderr)
        return 1
    print_stats(f"{args.process} — {args.seconds}s", stats)
    if args.keep_csv:
        print(f"\n  raw CSV: {csv_path}")
    else:
        try:
            os.remove(csv_path)
        except OSError:
            pass
    return 0


def cmd_compare(args) -> int:
    pm_exe = find_presentmon(args.presentmon)
    if pm_exe is None:
        preflight(pm_exe, args.process)
        return 2
    results: list[tuple[str, dict]] = []
    for i, scenario in enumerate(args.scenarios, 1):
        print(f"\n[{i}/{len(args.scenarios)}] SET UP: {scenario}")
        try:
            input("         get the game into this state, then press Enter to capture... ")
        except (EOFError, KeyboardInterrupt):
            print("\n  aborted.")
            break
        if not process_running(args.process):
            print(f"  ! {args.process} not running — skipping this scenario.", file=sys.stderr)
            continue
        csv_path = run_presentmon(pm_exe, args.process, args.seconds)
        if not csv_path:
            continue
        stats = parse_csv(csv_path)
        try:
            os.remove(csv_path)
        except OSError:
            pass
        if stats:
            results.append((scenario, stats))
            print_stats(scenario, stats)

    if len(results) >= 2:
        print_comparison(results)
    return 0


def print_comparison(results: list[tuple[str, dict]]) -> None:
    base_label, base = results[0]
    print("\n" + "=" * 78)
    print(f"COMPARISON (baseline = '{base_label}')")
    print("=" * 78)
    hdr = f"{'scenario':<26}{'mean ms':>9}{'p99 ms':>9}{'1% low':>9}{'Δmean':>9}{'Δp99':>9}"
    print(hdr)
    print("-" * len(hdr))
    for label, st in results:
        d_mean = st["mean_ms"] - base["mean_ms"]
        d_p99 = st["p99_ms"] - base["p99_ms"]
        print(
            f"{label[:25]:<26}{st['mean_ms']:>9.2f}{st['p99_ms']:>9.2f}"
            f"{st['low1_fps']:>9.1f}{d_mean:>+9.2f}{d_p99:>+9.2f}"
        )
    print("\nPresent mode per scenario (watch for a drop OUT of Independent Flip):")
    for label, st in results:
        print(f"  {label[:34]:<35} {dominant_mode(st)}")
    print(
        "\nReading it: +Δmean / +Δp99 over baseline = the game got slower under that\n"
        "scenario. A shift from 'Hardware: Independent Flip' to a 'Composed' mode is\n"
        "the overlay/capture demoting the game's present path — usually the biggest\n"
        "single source of added latency."
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Measure runlog's impact on Marathon frame times via PresentMon.")
    p.add_argument("--presentmon", help="Path to PresentMon*.exe (else: PATH or beside this script).")
    p.add_argument("--process", default=DEFAULT_PROCESS, help=f"Target process image name (default {DEFAULT_PROCESS}).")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("capture", help="One timed capture → stats.")
    c.add_argument("--seconds", type=int, default=30)
    c.add_argument("--keep-csv", action="store_true", help="Keep the raw PresentMon CSV.")
    c.set_defaults(func=cmd_capture)

    cmp = sub.add_parser("compare", help="Guided A/B/C across scenarios → delta table.")
    cmp.add_argument("--seconds", type=int, default=30)
    cmp.add_argument(
        "--scenarios", nargs="+",
        default=["runlog OFF", "runlog watching", "runlog recording", "runlog recording + overlay"],
        help="Scenario labels; you set up each one when prompted.",
    )
    cmp.set_defaults(func=cmd_compare)
    return p


def main() -> int:
    if sys.platform != "win32":
        print("This harness is Windows-only (PresentMon/ETW).", file=sys.stderr)
        return 2
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
