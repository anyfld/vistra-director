#!/usr/bin/env python3

import time
import argparse
from servo_controller import ServoController


def run_demo(ctrl: ServoController):
    print("\n" + "=" * 50)
    print("  Dual Servo Controller - Demo")
    print("=" * 50)

    print("\n[1] Current positions")
    pos = ctrl.get_positions()
    print(f"    Servo 1: {pos[1]}°, Servo 2: {pos[2]}°")
    time.sleep(1)

    print("\n[2] Centering (90°)")
    ctrl.center_all()
    time.sleep(1)

    print("\n[3] Servo 1 -> 45°")
    ctrl.move_servo(1, 45)
    time.sleep(0.5)

    print("\n[4] Servo 2 -> 135°")
    ctrl.move_servo(2, 135)
    time.sleep(0.5)

    print("\n[5] Both -> (135°, 45°)")
    ctrl.move_both(135, 45)
    time.sleep(0.5)

    print("\n[6] FAST (3ms/step)")
    ctrl.set_speed(3)
    ctrl.move_both(45, 135)
    time.sleep(0.5)

    print("\n[7] SLOW (50ms/step)")
    ctrl.set_speed(50)
    ctrl.move_both(90, 90)
    time.sleep(0.5)

    print("\n[8] Normal (15ms/step)")
    ctrl.set_speed(15)

    print("\n[9] Sweep")
    for _ in range(2):
        ctrl.move_both(30, 30)
        ctrl.move_both(150, 150)

    print("\n[10] Diagonal")
    ctrl.move_both(30, 150)
    time.sleep(0.3)
    ctrl.move_both(150, 30)
    time.sleep(0.3)

    print("\n[11] Center")
    ctrl.center_all()

    print("\n" + "=" * 50)
    print("  Demo completed!")
    print("=" * 50)

    pos = ctrl.get_positions()
    print(f"\nFinal: Servo 1: {pos[1]}°, Servo 2: {pos[2]}°\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port")
    parser.add_argument("-b", "--baudrate", type=int, default=115200)

    args = parser.parse_args()
    print("Starting demo...")

    with ServoController(port=args.port, baudrate=args.baudrate) as ctrl:
        run_demo(ctrl)


if __name__ == "__main__":
    main()

