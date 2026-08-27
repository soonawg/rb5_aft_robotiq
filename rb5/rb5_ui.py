#!/usr/bin/env python3
"""Windows UI for RB5 F/T monitoring and a directly connected Robotiq 2F-85."""

import queue
import socket
import struct
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from capture_ft import read_ft
from filter_ft import AXES, FinalFTFilter

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None


AXIS_LABELS = ("Fx (N)", "Fy (N)", "Fz (N)", "Mx (Nm)", "My (Nm)", "Mz (Nm)")


def modbus_crc(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return struct.pack("<H", crc)


class Robotiq:
    def __init__(self):
        self.port = None
        self.lock = threading.Lock()

    @property
    def connected(self):
        return self.port is not None and self.port.is_open

    def connect(self, port_name):
        if serial is None:
            raise RuntimeError("pyserial이 없습니다: py -m pip install pyserial")
        self.close()
        self.port = serial.Serial(
            port_name, 115200, bytesize=8, parity="N", stopbits=1, timeout=0.3
        )

    def close(self):
        if self.port is not None:
            self.port.close()
            self.port = None

    def request(self, payload, response_size):
        if not self.connected:
            raise RuntimeError("그리퍼 COM 포트가 연결되지 않았습니다")
        with self.lock:
            self.port.reset_input_buffer()
            self.port.write(payload + modbus_crc(payload))
            response = self.port.read(response_size)
        if len(response) != response_size:
            raise RuntimeError("그리퍼 Modbus 응답이 없습니다")
        if modbus_crc(response[:-2]) != response[-2:]:
            raise RuntimeError("그리퍼 응답 CRC가 잘못되었습니다")
        if response[0] != 9 or response[1] & 0x7F != payload[1]:
            raise RuntimeError("예상하지 못한 그리퍼 응답입니다")
        if response[1] & 0x80:
            raise RuntimeError(f"그리퍼 Modbus 예외 코드: {response[2]}")
        return response

    def write(self, action, position=0, speed=64, force=32):
        payload = struct.pack(
            ">BBHHB6B", 9, 0x10, 0x03E8, 3, 6, action, 0, 0,
            position, speed, force,
        )
        self.request(payload, 8)

    def initialize(self):
        self.write(0)
        time.sleep(0.2)
        self.write(1)

    def move(self, position, speed, force):
        self.write(9, position, speed, force)

    def fault(self):
        response = self.request(struct.pack(">BBHH", 9, 3, 0x07D0, 3), 11)
        return response[5]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RB5 F/T + Robotiq 2F-85")
        self.geometry("760x560")
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.samples = queue.SimpleQueue()
        self.stop_event = threading.Event()
        self.ft_filter = FinalFTFilter(alpha=0.1, sample_rate=50)
        self.gripper = Robotiq()
        self.host = tk.StringVar(value="10.0.2.7")
        self.sensor_status = tk.StringVar(value="연결 중")
        self.gripper_status = tk.StringVar(value="연결 안 됨")
        self.mass = tk.StringVar(value="영점 버튼을 누르세요")
        self.raw_vars = [tk.StringVar(value="-") for _ in AXES]
        self.filtered_vars = [tk.StringVar(value="-") for _ in AXES]
        self.com_port = tk.StringVar()
        self.speed = tk.IntVar(value=64)
        self.force = tk.IntVar(value=32)
        self._build()
        self.refresh_ports()
        threading.Thread(
            target=self.sensor_worker, args=(self.host.get(),), daemon=True
        ).start()
        self.after(20, self.consume_samples)

    def _build(self):
        sensor = ttk.LabelFrame(self, text="AIDIN AFT200 — RB 제어박스 Modbus TCP")
        sensor.pack(fill="x", padx=12, pady=10)
        ttk.Label(sensor, text="제어박스 IP").grid(row=0, column=0, padx=6, pady=6)
        ttk.Entry(sensor, textvariable=self.host, width=16).grid(row=0, column=1)
        ttk.Label(sensor, textvariable=self.sensor_status).grid(row=0, column=2, padx=12)
        ttk.Button(sensor, text="영점(Tare)", command=self.tare).grid(row=0, column=3, padx=6)

        ttk.Label(sensor, text="축").grid(row=1, column=0)
        ttk.Label(sensor, text="원값").grid(row=1, column=1)
        ttk.Label(sensor, text="필터값").grid(row=1, column=2)
        for row, (name, raw, filtered) in enumerate(
            zip(AXIS_LABELS, self.raw_vars, self.filtered_vars), 2
        ):
            ttk.Label(sensor, text=name).grid(row=row, column=0, sticky="w", padx=6)
            ttk.Label(sensor, textvariable=raw, width=16).grid(row=row, column=1)
            ttk.Label(sensor, textvariable=filtered, width=16).grid(row=row, column=2)
        ttk.Label(sensor, textvariable=self.mass, font=("Segoe UI", 13, "bold")).grid(
            row=8, column=0, columnspan=4, sticky="w", padx=6, pady=8
        )

        grip = ttk.LabelFrame(self, text="Robotiq 2F-85 — 데스크탑 USB/COM 직접 연결")
        grip.pack(fill="x", padx=12, pady=10)
        self.port_box = ttk.Combobox(grip, textvariable=self.com_port, width=18, state="readonly")
        self.port_box.grid(row=0, column=0, padx=6, pady=8)
        ttk.Button(grip, text="새로고침", command=self.refresh_ports).grid(row=0, column=1)
        ttk.Button(grip, text="연결", command=self.connect_gripper).grid(row=0, column=2, padx=6)
        ttk.Label(grip, textvariable=self.gripper_status).grid(row=0, column=3, padx=8)

        ttk.Label(grip, text="속도").grid(row=1, column=0)
        ttk.Scale(grip, from_=1, to=255, variable=self.speed, orient="horizontal").grid(
            row=1, column=1, columnspan=2, sticky="ew"
        )
        ttk.Label(grip, text="힘").grid(row=2, column=0)
        ttk.Scale(grip, from_=1, to=255, variable=self.force, orient="horizontal").grid(
            row=2, column=1, columnspan=2, sticky="ew"
        )
        ttk.Button(grip, text="Reset + Activate", command=self.initialize_gripper).grid(
            row=3, column=0, padx=6, pady=12
        )
        ttk.Button(grip, text="열기", command=lambda: self.move_gripper(0)).grid(
            row=3, column=1, padx=6
        )
        ttk.Button(grip, text="닫기", command=lambda: self.move_gripper(255)).grid(
            row=3, column=2, padx=6
        )
        ttk.Label(
            self,
            text="주의: 영점과 측정 자세를 같게 유지하고, 그리퍼 동작 전 주변을 비우세요.",
            foreground="#a00000",
        ).pack(anchor="w", padx=18, pady=4)

    def sensor_worker(self, host):
        while not self.stop_event.is_set():
            try:
                with socket.create_connection((host, 502), timeout=2) as sock:
                    sock.settimeout(1)
                    transaction_id = 1
                    next_sample = time.monotonic()
                    self.samples.put(("status", "연결됨"))
                    while not self.stop_event.is_set():
                        values = read_ft(sock, transaction_id)
                        transaction_id = transaction_id % 65535 + 1
                        self.samples.put(("sample", values))
                        next_sample += 0.02
                        time.sleep(max(0, next_sample - time.monotonic()))
            except Exception as error:
                self.samples.put(("status", f"오류: {error}"))
                self.stop_event.wait(1)

    def consume_samples(self):
        try:
            while True:
                kind, value = self.samples.get_nowait()
                if kind == "status":
                    self.sensor_status.set(value)
                    continue
                filtered, mass_g, stable_mass_g = self.ft_filter.update(value)
                for variable, number in zip(self.raw_vars, value):
                    variable.set(f"{number:.3f}")
                for variable, number in zip(self.filtered_vars, filtered):
                    variable.set(f"{number:.3f}")
                if stable_mass_g is None:
                    self.mass.set(f"질량 변화: {mass_g:+.1f} g  ·  안정화 중")
                else:
                    self.mass.set(f"확정 질량 변화: {stable_mass_g:+.1f} g  ·  안정")
        except queue.Empty:
            pass
        self.after(20, self.consume_samples)

    def tare(self):
        try:
            self.ft_filter.tare()
            self.mass.set("영점 완료 · 안정화 중")
        except RuntimeError as error:
            messagebox.showerror("영점 실패", str(error))

    def refresh_ports(self):
        ports = [port.device for port in list_ports.comports()] if list_ports else []
        self.port_box["values"] = ports
        if ports and self.com_port.get() not in ports:
            self.com_port.set(ports[0])
        if serial is None:
            self.gripper_status.set("pyserial 필요: py -m pip install pyserial")

    def connect_gripper(self):
        try:
            self.gripper.connect(self.com_port.get())
            fault = self.gripper.fault()
            self.gripper_status.set(f"연결됨 · fault=0x{fault:02X}")
        except Exception as error:
            self.gripper_status.set("연결 실패")
            messagebox.showerror("그리퍼 연결 실패", str(error))

    def run_gripper(self, action):
        def worker():
            try:
                action()
                fault = self.gripper.fault()
                self.after(0, self.gripper_status.set, f"명령 완료 · fault=0x{fault:02X}")
            except Exception as error:
                self.after(0, self.gripper_status.set, "통신 실패")
                self.after(0, messagebox.showerror, "그리퍼 오류", str(error))

        threading.Thread(target=worker, daemon=True).start()

    def initialize_gripper(self):
        self.run_gripper(self.gripper.initialize)

    def move_gripper(self, position):
        self.run_gripper(
            lambda: self.gripper.move(position, int(self.speed.get()), int(self.force.get()))
        )

    def close(self):
        self.stop_event.set()
        self.gripper.close()
        self.destroy()


if __name__ == "__main__":
    assert modbus_crc(bytes.fromhex("01030000000A")) == bytes.fromhex("C5CD")
    App().mainloop()
