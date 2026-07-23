#!/bin/bash
# Copyright (C) 2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
#
# Headless launch of the RAI manipulation demo for the ROSCon '26 GPU workshop.
#
# Attendees run this on a remote Strix Halo / Strix Point box from their laptop.
# There is no monitor on that box, so instead of rendering O3DE to a local
# display we stream the simulation's camera topic to the browser and show it
# next to the chat on a SINGLE page:
#
#     http://<host>:8501   ->  [ live simulation | robot-agent chat ]
#
# Pipeline:  O3DE --/color_image5--> web_video_server (:8080 MJPEG)
#                                          |
#                                          v
#            patched Streamlit page (:8501) embeds it in the left column.
set -e

WORKSHOP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCHED_DEMO=/ryzers/rai/examples/manipulation-demo-streamlit-headless.py

# --- 1. Display for O3DE -----------------------------------------------------
# O3DE renders with Vulkan and must PRESENT, which needs DRI3 — i.e. an X server
# backed by the GPU. On a headless box (SSH, no monitor) we start our OWN Xorg
# on the amdgpu with a virtual framebuffer (xorg-headless.conf).
#
# PREREQUISITE: the GPU must be FREE. A desktop session (gdm/gnome-shell) holds
# the card as DRM-master EVEN WITH NO MONITOR ATTACHED, and Xorg then fails with
# "amdgpu_query_info(ACCEL_WORKING) failed (-13)". Make the workshop box truly
# headless once:
#     sudo systemctl stop gdm
#     sudo systemctl set-default multi-user.target   # persists across reboots
#
# Dev box WITH a monitor/desktop? Don't fight for the GPU — borrow the running
# display instead:   REUSE_DISPLAY=:0 bash manipulation_demo_headless.sh
#     (authorize it once on the host session with:  xhost +local:)
if [ -z "$DISPLAY" ] && [ -n "${REUSE_DISPLAY:-}" ]; then
  export DISPLAY="$REUSE_DISPLAY"
  echo "[headless] reusing DISPLAY=$DISPLAY (REUSE_DISPLAY set)"
fi

if [ -z "$DISPLAY" ]; then
  echo "[headless] starting our own headless Xorg on the AMD GPU (:99, DRI3)"
  if ! command -v Xorg >/dev/null 2>&1; then
    apt-get update && apt-get install -y xserver-xorg-core xserver-xorg-video-amdgpu
  fi
  cp "${WORKSHOP_DIR}/xorg-headless.conf" /etc/X11/xorg.conf
  Xorg :99 -sharevts -novtswitch -noreset >/tmp/xorg.log 2>&1 &
  export DISPLAY=:99
  for _ in $(seq 1 15); do [ -S /tmp/.X11-unix/X99 ] && break; sleep 1; done
  if [ ! -S /tmp/.X11-unix/X99 ]; then
    echo "[headless] ERROR: Xorg :99 did not start — see /tmp/xorg.log"
    echo "[headless] If it says 'ACCEL_WORKING failed (-13)', a desktop session"
    echo "[headless] still owns the GPU:  sudo systemctl stop gdm   (then retry)"
    tail -n 30 /tmp/xorg.log || true
    exit 1
  fi
  echo "[headless] Xorg :99 is up"
else
  echo "[headless] using DISPLAY=$DISPLAY"
fi

# --- 2. ROS environment ------------------------------------------------------
cd /ryzers/rai
source "/opt/ros/${ROS_DISTRO}/setup.sh"
source install/setup.bash

# --- 3. Stream the O3DE camera topic to the browser (MJPEG on :8080) ---------
if ! ros2 pkg executables web_video_server >/dev/null 2>&1; then
  echo "[headless] installing web_video_server..."
  apt-get update && apt-get install -y "ros-${ROS_DISTRO}-web-video-server"
fi
echo "[headless] starting web_video_server on :8080"
ros2 run web_video_server web_video_server --ros-args -p port:=8080 \
  >/tmp/web_video_server.log 2>&1 &

# --- 4. Patch the Streamlit demo into a two-column (sim | chat) layout --------
python3 "${WORKSHOP_DIR}/patch_manipulation_streamlit.py" \
  /ryzers/rai/examples/manipulation-demo-streamlit.py "${PATCHED_DEMO}"

# --- 5. Launch the combined page on :8501 ------------------------------------
# cwd stays /ryzers/rai so the app's relative paths + sibling imports resolve.
echo "[headless] open http://<host>:8501  (left = simulation, right = chat)"
exec streamlit run "examples/$(basename "${PATCHED_DEMO}")" \
  --server.address 0.0.0.0 --server.port 8501
