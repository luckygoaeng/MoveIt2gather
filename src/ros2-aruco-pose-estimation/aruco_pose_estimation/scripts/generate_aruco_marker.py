#!/usr/bin/env python3
"""
Generates a printable ArUco marker image.

Upstream ros2-aruco-pose-estimation does not ship a marker generation
script, so this one is added locally to fill that gap. Uses the same
cv2.aruco dictionary names accepted by aruco_parameters.yaml
(aruco_dictionary_id), so generated markers stay consistent with the
detection node's configuration.

Usage:
    ros2 run aruco_pose_estimation generate_aruco_marker.py --id 1 --size 200 --dictionary DICT_5X5_250
"""

import argparse
import os

import cv2


def main():
    parser = argparse.ArgumentParser(description="Generate a printable ArUco marker image.")
    parser.add_argument("--id", type=int, required=True, help="Marker ID to encode.")
    parser.add_argument("--size", type=int, default=200, help="Marker image size in pixels (square).")
    parser.add_argument("--dictionary", type=str, default="DICT_5X5_250",
                         help="cv2.aruco dictionary name, e.g. DICT_5X5_250.")
    parser.add_argument("--output-dir", type=str, default=".", help="Directory to save the marker image.")
    parser.add_argument("--border-bits", type=int, default=1, help="Width of the marker border in bits.")
    args = parser.parse_args()

    if not hasattr(cv2.aruco, args.dictionary):
        raise SystemExit(f"Unknown aruco dictionary: {args.dictionary}")

    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, args.dictionary))
    marker_image = cv2.aruco.generateImageMarker(dictionary, args.id, args.size, borderBits=args.border_bits)

    os.makedirs(args.output_dir, exist_ok=True)
    output_path = os.path.join(args.output_dir, f"marker_{args.dictionary}_id{args.id}.png")
    cv2.imwrite(output_path, marker_image)
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
