#!/usr/bin/env python3

import argparse
import sys
from servo_controller import ServoController, list_ports


def interactive_mode(controller: ServoController):
    print("\n=== Interactive Mode ===")
    print("Commands:")
    print("  [servo_id],[angle]      - Move single servo (e.g., 1,90)")
    print("  both,[angle1],[angle2]  - Move both servos")
    print("  center                  - Center all (90°)")
    print("  speed,[ms]              - Set speed (e.g., speed,15)")
    print("  status                  - Show positions")
    print("  quit                    - Exit")
    print()

    while True:
        try:
            user_input = input(">> ").strip().lower()
            if not user_input:
                continue
            if user_input in ["quit", "q"]:
                break
            elif user_input == "center":
                controller.center_all()
            elif user_input == "status":
                pos = controller.get_positions()
                print(f"Servo 1: {pos[1]}°, Servo 2: {pos[2]}°")
                print(f"Speed: {controller.step_delay * 1000:.1f}ms/step")
            elif user_input.startswith("speed,"):
                parts = user_input.split(",")
                if len(parts) == 2:
                    controller.set_speed(float(parts[1]))
            elif user_input.startswith("both,"):
                parts = user_input.split(",")
                if len(parts) == 3:
                    controller.move_both(int(parts[1]), int(parts[2]))
            elif "," in user_input:
                parts = user_input.split(",")
                if len(parts) == 2:
                    controller.move_servo(int(parts[0]), int(parts[1]))
            else:
                print("Unknown command")
        except ValueError as e:
            print(f"Error: {e}")
        except KeyboardInterrupt:
            print("\nExiting...")
            break


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port")
    parser.add_argument("-b", "--baudrate", type=int, default=115200)
    parser.add_argument("-l", "--list-ports", action="store_true")
    parser.add_argument("-s", "--servo", type=int, choices=[1, 2])
    parser.add_argument("-a", "--angle", type=int)
    parser.add_argument("--speed", type=float, default=15)

    args = parser.parse_args()

    if args.list_ports:
        list_ports()
        return

    if args.servo is not None and args.angle is not None:
        with ServoController(port=args.port, baudrate=args.baudrate) as ctrl:
            ctrl.set_speed(args.speed)
            ctrl.move_servo(args.servo, args.angle)
    elif args.servo is None and args.angle is None:
        with ServoController(port=args.port, baudrate=args.baudrate) as ctrl:
            ctrl.set_speed(args.speed)
            interactive_mode(ctrl)
    else:
        print("Error: Both --servo and --angle required")
        sys.exit(1)


if __name__ == "__main__":
    main()

