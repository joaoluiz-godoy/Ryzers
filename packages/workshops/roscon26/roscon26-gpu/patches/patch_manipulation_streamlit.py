#!/usr/bin/env python3
# Copyright (C) 2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""Patch RAI's manipulation-demo-streamlit.py into a two-column layout.

Left column  = the live O3DE camera feed, streamed to the browser as MJPEG by
               web_video_server (no local display needed).
Right column = the existing robot-agent chat, unchanged.

The patch is purely additive and needs no re-indentation of the original app:
the simulation column is inserted just before ``st.chat_input()`` (which must
stay at the app root), and the chat widgets are routed into a right-hand column
object by rewriting ``st.chat_message(...)`` -> ``_chat_col.chat_message(...)``.

The patched copy is written NEXT TO the original so its sibling import
(``manipulation_common``) and relative paths keep resolving. Idempotent: it
always derives from the pristine source, so re-running is safe.

Usage:
    python3 patch_manipulation_streamlit.py [SRC] [DST]
"""

import sys
from pathlib import Path

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    "/ryzers/rai/examples/manipulation-demo-streamlit.py"
)
DST = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(
    "/ryzers/rai/examples/manipulation-demo-streamlit-headless.py"
)

TOPIC = "/color_image5"   # O3DE camera feed (see packages/robotics/rai/Blog/BLOG.md)
STREAM_PORT = 8080        # web_video_server MJPEG port

code = SRC.read_text()

# 1. Wide page so the two columns have room.
code = code.replace(
    'page_icon=":robot:",',
    'page_icon=":robot:",\n        layout="wide",',
    1,
)

# 2. Insert the simulation column immediately before the chat input. The MJPEG
#    <img> src is built from window.location.hostname so it works no matter how
#    the attendee reaches the box (localhost forward, cloud hostname, proxy).
sim_block = f'''    _sim_html = (
        '<img id="sim" style="width:100%;border-radius:8px;background:#000" />'
        '<script>document.getElementById("sim").src='
        '"http://"+window.location.hostname+":{STREAM_PORT}/stream?topic={TOPIC}&type=mjpeg";'
        '</script>'
    )
    _sim_col, _chat_col = st.columns([1, 1])
    with _sim_col:
        st.subheader("Simulation")
        import streamlit.components.v1 as _components
        _components.html(_sim_html, height=520)
    prompt = st.chat_input()'''

assert "    prompt = st.chat_input()" in code, "chat_input anchor not found — app changed?"
code = code.replace("    prompt = st.chat_input()", sim_block, 1)

# 3. Route the chat widgets into the right-hand column (no re-indentation).
code = code.replace('st.chat_message("assistant").write', '_chat_col.chat_message("assistant").write')
code = code.replace('st.chat_message("user").write', '_chat_col.chat_message("user").write')
code = code.replace('with st.chat_message("assistant"):', 'with _chat_col.chat_message("assistant"):')

DST.write_text(code)
print(f"[patch] wrote two-column headless demo -> {DST}")
