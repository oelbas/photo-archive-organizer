#!/bin/sh
# Build the on-device Vision helper (macOS 10.15+ with Xcode command line tools).
set -e
cd "$(dirname "$0")"
swiftc -O -o pao-vision pao-vision.swift
echo "built $(pwd)/pao-vision"
