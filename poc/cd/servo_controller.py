#!/usr/bin/env python3

import logging
import serial
import serial.tools.list_ports
import time
import threading
from typing import Optional


logger = logging.getLogger(__name__)


class ServoController:
    def __init__(
        self, port: Optional[str] = None, baudrate: int = 115200, timeout: float = 2.0
    ):
        self.port = port or self._find_arduino_port()
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial: Optional[serial.Serial] = None
        self.servo_positions = {1: 90, 2: 90}
        self.step_delay = 0.015
        self._lock = threading.Lock()

    def _find_arduino_port(self) -> str:
        ports = serial.tools.list_ports.comports()
        for port in ports:
            if any(
                keyword in port.description.lower()
                for keyword in ["arduino", "ch340", "ftdi", "usb"]
            ):
                return port.device
            if "usbmodem" in port.device or "usbserial" in port.device:
                return port.device
        raise RuntimeError("Arduino not found")

    def connect(self) -> None:
        logger.info("Connecting to USB serial port: %s", self.port)
        self.serial = serial.Serial(
            port=self.port, baudrate=self.baudrate, timeout=self.timeout
        )
        time.sleep(2)
        while self.serial.in_waiting > 0:
            self.serial.readline()
        self._query_positions()
        logger.info("USB serial connection established: %s", self.port)

    def disconnect(self) -> None:
        if self.serial and self.serial.is_open:
            self.serial.close()
            logger.info("USB serial connection closed: %s", self.port)

    def set_speed(self, delay_ms: float) -> None:
        self.step_delay = delay_ms / 1000.0
        logger.info("Servo step speed set: %.1f ms/step", delay_ms)

    def _send_command_fast(self, servo_id: int, angle: int) -> None:
        assert self.serial is not None, "Serial connection not established"
        command = f"{servo_id},{angle}\n"
        logger.debug(
            "USB serial send (fast): port=%s, servo_id=%s, angle=%s",
            self.port,
            servo_id,
            angle,
        )
        self.serial.write(command.encode("utf-8"))
        self.servo_positions[servo_id] = angle

    def _send_command(self, servo_id: int, angle: int) -> tuple[int, int]:
        assert self.serial is not None, "Serial connection not established"
        with self._lock:
            command = f"{servo_id},{angle}\n"
            logger.debug(
                "USB serial send: port=%s, servo_id=%s, angle=%s",
                self.port,
                servo_id,
                angle,
            )
            self.serial.write(command.encode("utf-8"))
            start_time = time.time()
            while time.time() - start_time < 1.0:
                if self.serial.in_waiting > 0:
                    line = (
                        self.serial.readline().decode("utf-8", errors="ignore").strip()
                    )
                    if line.startswith("POS:"):
                        parts = line[4:].split(",")
                        if len(parts) == 2:
                            pos1, pos2 = int(parts[0]), int(parts[1])
                            self.servo_positions[1] = pos1
                            self.servo_positions[2] = pos2
                            return pos1, pos2
                    elif line == "ERROR":
                        raise ValueError("Arduino error")
                time.sleep(0.001)
            return self.servo_positions[1], self.servo_positions[2]

    def _flush_input(self) -> None:
        assert self.serial is not None, "Serial connection not established"
        while self.serial.in_waiting > 0:
            self.serial.read(self.serial.in_waiting)

    def _query_positions(self) -> tuple[int, int]:
        self._flush_input()
        return self._send_command(0, 0)

    def move_servo(self, servo_id: int, target_angle: int) -> None:
        if servo_id not in [1, 2]:
            raise ValueError("Servo ID must be 1 or 2")
        if not 0 <= target_angle <= 180:
            raise ValueError("Angle must be 0-180")

        current = self.servo_positions[servo_id]
        if current == target_angle:
            return

        logger.info(
            "Servo move: port=%s, servo_id=%s, from=%s°, to=%s°",
            self.port,
            servo_id,
            current,
            target_angle,
        )
        self._flush_input()

        step = 1 if target_angle > current else -1
        for angle in range(current + step, target_angle + step, step):
            self._send_command_fast(servo_id, angle)
            time.sleep(self.step_delay)

        time.sleep(0.01)
        self._flush_input()

    def move_both(self, target1: int, target2: int) -> None:
        if not 0 <= target1 <= 180 or not 0 <= target2 <= 180:
            raise ValueError("Angle must be 0-180")

        current1 = self.servo_positions[1]
        current2 = self.servo_positions[2]
        diff1 = target1 - current1
        diff2 = target2 - current2

        if diff1 == 0 and diff2 == 0:
            return

        logger.info(
            "Servo move both: port=%s, servo1=%s°->%s°, servo2=%s°->%s°",
            self.port,
            current1,
            target1,
            current2,
            target2,
        )

        max_steps = max(abs(diff1), abs(diff2))
        if max_steps == 0:
            return

        self._flush_input()
        step1 = diff1 / max_steps
        step2 = diff2 / max_steps

        for i in range(1, max_steps + 1):
            angle1 = round(current1 + step1 * i)
            angle2 = round(current2 + step2 * i)
            self._send_command_fast(1, angle1)
            self._send_command_fast(2, angle2)
            time.sleep(self.step_delay)

        self.servo_positions[1] = target1
        self.servo_positions[2] = target2
        time.sleep(0.01)
        self._flush_input()

    def get_positions(self) -> dict:
        return self.servo_positions.copy()

    def center_all(self) -> None:
        logger.info("Centering all servos to 90°")
        self.move_both(90, 90)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()


def list_ports():
    ports = serial.tools.list_ports.comports()
    logger.info("Available USB serial ports:")
    for port in ports:
        logger.info("  %s: %s", port.device, port.description)

