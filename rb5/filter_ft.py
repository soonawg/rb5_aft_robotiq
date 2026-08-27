#!/usr/bin/env python3
"""Causal RB F/T filter with same-pose tare and stable mass estimation."""

import argparse
import csv
import statistics
from collections import deque
from pathlib import Path


AXES = ("fx_n", "fy_n", "fz_n", "mx_nm", "my_nm", "mz_nm")
GRAVITY = 9.80665


class FinalFTFilter:
    """EMA for live display plus a one-second stable mass window."""

    def __init__(self, alpha=0.1, sample_rate=50, stable_seconds=1, threshold_g=30):
        if not 0 < alpha <= 1:
            raise ValueError("alpha must be in (0, 1]")
        if min(sample_rate, stable_seconds, threshold_g) <= 0:
            raise ValueError("sample rate, stable seconds and threshold must be positive")
        self.alpha = alpha
        self.state = None
        self.tare_fz = 0.0
        self.mass_window = deque(maxlen=max(1, round(sample_rate * stable_seconds)))
        self.threshold_g = threshold_g

    def tare(self):
        if self.state is None:
            raise RuntimeError("cannot tare before the first sample")
        self.tare_fz = self.state[2]
        self.mass_window.clear()

    def update(self, values):
        values = tuple(values)
        if len(values) != len(AXES):
            raise ValueError(f"expected {len(AXES)} values, got {len(values)}")
        if self.state is None:
            self.state = values
        else:
            self.state = tuple(
                old + self.alpha * (new - old)
                for old, new in zip(self.state, values)
            )
        mass_g = (self.state[2] - self.tare_fz) / GRAVITY * 1000
        self.mass_window.append(mass_g)
        stable = (
            len(self.mass_window) == self.mass_window.maxlen
            and max(self.mass_window) - min(self.mass_window) <= self.threshold_g
        )
        stable_mass_g = statistics.fmean(self.mass_window) if stable else None
        return self.state, mass_g, stable_mass_g


def read_rows(source):
    with source.open(newline="") as input_file:
        reader = csv.DictReader(input_file)
        missing = tuple(
            name for name in ("time_s",) + AXES if name not in (reader.fieldnames or ())
        )
        if missing:
            raise ValueError("missing CSV columns: " + ", ".join(missing))
        rows = []
        for row_number, row in enumerate(reader, 2):
            try:
                rows.append(
                    (float(row["time_s"]), tuple(float(row[axis]) for axis in AXES))
                )
            except (TypeError, ValueError) as error:
                raise ValueError(f"invalid numeric value at CSV row {row_number}") from error
    if len(rows) < 2:
        raise ValueError("CSV needs at least two samples")
    return rows


def filter_csv(source, destination, alpha, tare_seconds, stable_seconds, threshold_g):
    if source.resolve() == destination.resolve():
        raise ValueError("output must differ from input so raw data is preserved")
    rows = read_rows(source)
    periods = [b[0] - a[0] for a, b in zip(rows, rows[1:]) if b[0] > a[0]]
    if not periods:
        raise ValueError("time_s must contain increasing timestamps")
    sample_rate = 1 / statistics.median(periods)
    tare_count = max(1, round(tare_seconds * sample_rate))
    if max(tare_count, round(stable_seconds * sample_rate)) > len(rows):
        raise ValueError("CSV is shorter than the tare or stable interval")

    ft_filter = FinalFTFilter(alpha, sample_rate, stable_seconds, threshold_g)
    filtered_rows = []
    for time_s, values in rows:
        filtered, mass_g, stable_mass_g = ft_filter.update(values)
        filtered_rows.append((time_s, values, filtered, mass_g, stable_mass_g))
        if len(filtered_rows) == tare_count:
            ft_filter.tare()

    with destination.open("w", newline="") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(
            ("time_s",)
            + AXES
            + tuple(axis + "_filtered" for axis in AXES)
            + ("mass_g", "stable_mass_g")
        )
        for time_s, values, filtered, mass_g, stable_mass_g in filtered_rows:
            writer.writerow(
                (f"{time_s:.6f}",)
                + tuple(f"{value:.6f}" for value in values)
                + tuple(f"{value:.6f}" for value in filtered)
                + (f"{mass_g:.3f}", "" if stable_mass_g is None else f"{stable_mass_g:.3f}")
            )
    return sample_rate, ft_filter, filtered_rows[-1][3]


def main():
    parser = argparse.ArgumentParser(
        description="EMA filter plus same-pose tare and stable mass estimate"
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--alpha", type=float, default=0.1)
    parser.add_argument("--tare-seconds", type=float, default=1.0)
    parser.add_argument("--stable-seconds", type=float, default=1.0)
    parser.add_argument("--stable-threshold-g", type=float, default=30.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 0 < args.alpha <= 1:
        parser.error("--alpha must be in (0, 1]")
    if min(args.tare_seconds, args.stable_seconds, args.stable_threshold_g) <= 0:
        parser.error("time intervals and stability threshold must be positive")
    if not args.input.is_file():
        parser.error(f"input file not found: {args.input}")

    output = args.output or args.input.with_name(args.input.stem + "_final.csv")
    output.parent.mkdir(parents=True, exist_ok=True)
    sample_rate, ft_filter, mass_g = filter_csv(
        args.input,
        output,
        args.alpha,
        args.tare_seconds,
        args.stable_seconds,
        args.stable_threshold_g,
    )
    stable_mass = (
        statistics.fmean(ft_filter.mass_window)
        if len(ft_filter.mass_window) == ft_filter.mass_window.maxlen
        else None
    )
    noise_g = statistics.pstdev(ft_filter.mass_window)
    peak_to_peak_g = max(ft_filter.mass_window) - min(ft_filter.mass_window)
    stable = peak_to_peak_g <= ft_filter.threshold_g
    print(f"saved={output} sample_rate_hz={sample_rate:.2f} alpha={args.alpha}")
    print(f"tare_fz_n={ft_filter.tare_fz:.5f} final_mass_g={mass_g:.2f}")
    print(
        f"stable_mass_g={stable_mass:.2f} noise_std_g={noise_g:.2f} "
        f"peak_to_peak_g={peak_to_peak_g:.2f} stable={'yes' if stable else 'no'}"
    )


if __name__ == "__main__":
    demo = FinalFTFilter(alpha=0.5, sample_rate=2, stable_seconds=1, threshold_g=1000)
    assert demo.update((0, 0, 0, 0, 0, 0))[0] == (0, 0, 0, 0, 0, 0)
    assert demo.update((2, 4, 6, 8, 10, 12))[0] == (1, 2, 3, 4, 5, 6)
    demo.tare()
    assert abs(demo.update((1, 2, 3, 4, 5, 6))[1]) < 1e-12
    main()
