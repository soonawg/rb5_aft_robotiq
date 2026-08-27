#!/usr/bin/env python3
"""Record RB external F/T registers 304-309 over Modbus TCP."""

import argparse
import csv
import socket
import statistics
import struct
import time
from datetime import datetime
from pathlib import Path


AXES = ("fx_n", "fy_n", "fz_n", "mx_nm", "my_nm", "mz_nm")


def recv_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("RB5 closed the Modbus connection")
        data += chunk
    return data


def read_ft(sock, transaction_id):
    request = struct.pack(">HHHBBHH", transaction_id, 0, 6, 1, 3, 304, 6)
    sock.sendall(request)
    header = recv_exact(sock, 7)
    response_id, protocol_id, length, unit_id = struct.unpack(">HHHB", header)
    body = recv_exact(sock, length - 1)
    if (response_id, protocol_id, unit_id, body[:2]) != (
        transaction_id,
        0,
        1,
        b"\x03\x0c",
    ):
        raise RuntimeError("Unexpected Modbus response: " + (header + body).hex())
    return tuple(value * 0.02 for value in struct.unpack(">6h", body[2:14]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="10.0.2.7")
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--hz", type=float, default=50)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.seconds <= 0 or args.hz <= 0:
        parser.error("--seconds and --hz must be positive")

    output = args.output or Path(
        "rb5/data/ft_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    period = 1 / args.hz

    with socket.create_connection((args.host, 502), timeout=2) as sock, output.open(
        "w", newline=""
    ) as file:
        sock.settimeout(2)
        writer = csv.writer(file)
        writer.writerow(("time_s",) + AXES)
        start = next_sample = time.monotonic()
        transaction_id = 1
        while time.monotonic() - start < args.seconds:
            values = read_ft(sock, transaction_id)
            elapsed = time.monotonic() - start
            writer.writerow((f"{elapsed:.6f}",) + tuple(f"{v:.6f}" for v in values))
            rows.append(values)
            transaction_id = transaction_id % 65535 + 1
            next_sample += period
            time.sleep(max(0, next_sample - time.monotonic()))

    actual_hz = (len(rows) - 1) / max(elapsed, 1e-9)
    print(f"saved={output} samples={len(rows)} actual_hz={actual_hz:.2f}")
    print("axis       mean        std        peak_to_peak")
    for axis, values in zip(AXES, zip(*rows)):
        print(
            f"{axis:6} {statistics.fmean(values):10.5f} "
            f"{statistics.pstdev(values):10.5f} {max(values) - min(values):13.5f}"
        )


if __name__ == "__main__":
    # Known Modbus payload: 4, 1, -1, 0, 0, 0 -> 0.08, 0.02, -0.02, 0, 0, 0.
    assert struct.unpack(">6h", bytes.fromhex("00040001ffff000000000000")) == (
        4,
        1,
        -1,
        0,
        0,
        0,
    )
    main()
