"""Tiny ROS 2 subscriber that records a camera topic to a video file.

Standalone on purpose: rclpy doesn't multiplex two rclpy.init()
contexts in one process cleanly with the manipulation demo's own
ROS 2 node graph, so we run this as a sibling process with its own
node + DDS participant.

Default topic /color_image5 is what the RAI manipulation demo
publishes and what the agent "sees" via get_ros2_camera_image.

Auto-stop: once no frame has arrived for --idle-timeout seconds (i.e.
the benchmark finished and O3DE stopped publishing), the recorder
finalizes the file and exits on its own. You can still stop it early
with Ctrl-C / SIGTERM.

Format: writes MJPG/AVI by default. Each frame is self-contained, so
even a dirty kill leaves a file that plays up to the cut — unlike
mp4v, which is unrecoverable without its trailing moov atom. For
slides: ffmpeg -i run.avi -c:v libx264 run.mp4

Usage:
    Inside the rai container it lives at /ryzers/record_camera.py (baked in
    via the rai-stage Dockerfile). Run it as a sibling to the benchmark:
        python /ryzers/record_camera.py --output run.avi --fps 6
"""
from __future__ import annotations

import argparse
import signal
import sys
import time

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import Image


class CameraRecorder(Node):
    def __init__(self, output_path: str, topic: str, fps: int,
                 idle_timeout: float) -> None:
        super().__init__("camera_recorder")
        self.output_path = output_path
        self.fps = fps
        self.idle_timeout = idle_timeout
        self.bridge = CvBridge()
        self.writer: cv2.VideoWriter | None = None
        self.n_frames = 0
        self.t_first_frame: float | None = None
        self.t_last_frame: float | None = None
        self._done = False
        self.sub = self.create_subscription(Image, topic, self._on_frame, 10)
        # Check once a second whether the stream has gone idle.
        self.timer = self.create_timer(1.0, self._check_idle)
        self.get_logger().info(
            f"camera_recorder: subscribing to {topic}, writing to {output_path} "
            f"@ {fps} fps, auto-stop after {idle_timeout:.0f}s idle"
        )

    def _on_frame(self, msg: Image) -> None:
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as e:
            self.get_logger().error(f"cv_bridge failed: {e}")
            return
        if self.writer is None:
            h, w = frame.shape[:2]
            # MJPG/AVI: every frame self-contained, so a truncated file
            # still plays. mp4v needs a trailing moov atom and dies if
            # the process is killed before release().
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            self.writer = cv2.VideoWriter(self.output_path, fourcc, self.fps, (w, h))
            if not self.writer.isOpened():
                self.get_logger().error(
                    f"cv2.VideoWriter refused to open {self.output_path} ({w}x{h}@{self.fps})"
                )
                self.writer = None
                return
            self.get_logger().info(f"opened video writer: {w}x{h}")
        self.writer.write(frame)
        self.n_frames += 1
        now = time.time()
        if self.t_first_frame is None:
            self.t_first_frame = now
        self.t_last_frame = now

    def _check_idle(self) -> None:
        # Only start counting idle time after the first frame, so the
        # ~25s O3DE cold start doesn't trip the timeout before recording.
        if self._done or self.t_last_frame is None:
            return
        if time.time() - self.t_last_frame > self.idle_timeout:
            self.get_logger().info(
                f"no frames for {self.idle_timeout:.0f}s — benchmark done, finalizing"
            )
            self.finalize()
            self._done = True
            raise SystemExit(0)

    def finalize(self) -> None:
        if self.writer is not None:
            self.writer.release()
            self.writer = None
            dur = (
                (self.t_last_frame - self.t_first_frame)
                if (self.t_first_frame and self.t_last_frame)
                else 0.0
            )
            self.get_logger().info(
                f"wrote {self.n_frames} frames ({dur:.1f}s of camera time) to {self.output_path}"
            )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True, help="Path of the video file to write (.avi)")
    ap.add_argument("--topic", default="/color_image5")
    ap.add_argument("--fps", type=int, default=6,
                    help="Playback framerate. O3DE publishes ~6 Hz; lower = slower playback.")
    ap.add_argument("--idle-timeout", type=float, default=10.0,
                    help="Auto-stop after this many seconds with no new frame.")
    args = ap.parse_args()

    rclpy.init()
    node = CameraRecorder(args.output, args.topic, args.fps, args.idle_timeout)

    def _shutdown(_signum, _frame):
        node.finalize()
        try:
            rclpy.shutdown()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        rclpy.spin(node)
    except SystemExit:
        pass
    finally:
        node.finalize()
        try:
            rclpy.shutdown()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())