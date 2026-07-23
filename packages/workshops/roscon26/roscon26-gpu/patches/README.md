# ROSCon '26 GPU workshop — headless manipulation demo

Attendees drive a remote Strix Halo / Strix Point box from their laptop, so the
RAI manipulation demo must run **without a local monitor** yet still be visible.
Instead of rendering O3DE to a display, we stream the simulation's camera topic
to the browser and show it next to the chat on a **single page**:

```
O3DE ──/color_image5──► web_video_server (:8080 MJPEG) ─┐
                                                         ├─► Streamlit (:8501)
RAI agent ◄──────────── chat ──────────────────────────► │   [ simulation | chat ]
                                                         ┘
```

## Files

| File | Purpose |
|------|---------|
| `manipulation_demo_headless.sh` | Launch script: headless display → `web_video_server` → patched Streamlit page. Run it inside the container instead of `/ryzers/manipulation_demo.sh`. |
| `patch_manipulation_streamlit.py` | Rewrites RAI's `manipulation-demo-streamlit.py` into a two-column (simulation \| chat) layout. Additive, idempotent, writes a copy next to the original so its imports keep resolving. |

## Wiring (already applied to `packages/robotics/rai/config.yaml`)

```yaml
port_mappings:
  - "8501:8501"   # Streamlit frontend
  - "8080:8080"   # web_video_server (simulation MJPEG stream)
volume_mappings:
  - "$PWD/packages/workshops/roscon26/roscon26-gpu/patches:/ryzers/workshop"
```

Re-run `ryzers run` after editing `config.yaml` so the generated launch command
picks up the new port + mount. Then, inside the container:

```bash
source lemonade_env.sh                        # point RAI at the local Gemma
bash /ryzers/workshop/manipulation_demo_headless.sh
```

Open `http://<host>:8501` — left panel is the live simulation, right panel is
the robot-agent chat.

## Headless display for O3DE (the one setup step)

O3DE renders with **Vulkan** and must **present** to a surface, which requires
**DRI3** — i.e. a GPU-backed X server. `Xvfb` has no DRI3 (`No DRI3 support
detected`, sim never initializes), so the script starts a real **Xorg** on the
amdgpu DRM node with a virtual framebuffer (`xorg-headless.conf`): GPU rendering
*and* DRI3 presentation, no monitor.

### Prerequisite: free the GPU (one-time box setup)

A desktop session (`gdm`/`gnome-shell`) holds the iGPU as DRM-master **even with
no monitor attached** — unplugging the display does NOT free it. Xorg then fails
with `amdgpu_query_info(ACCEL_WORKING) failed (-13)`. Make the workshop box truly
headless:

```bash
sudo systemctl stop gdm                          # free the GPU now
sudo systemctl set-default multi-user.target     # boot headless from now on
```

After that the box is SSH-only, the iGPU is free, and the demo's own Xorg `:99`
grabs it. This is the real workshop shape: users SSH in, run the demo, watch it
on `:8501`.

If Xorg `:99` still fails, read `/tmp/xorg.log`. Common tweaks:
- Still `-13`? A desktop session is still running — recheck `fuser -v /dev/dri/card1`.
- Multiple DRM devices → add the GPU's `BusID "PCI:x:y:z"` to the `Device`
  section (`lspci -D | grep -i vga`).
- amdgpu refuses a virtual head → try `Driver "modesetting"` +
  `Option "kmsdev" "/dev/dri/card1"`.

### Dev box with a monitor

Don't fight for the GPU — borrow the running desktop's X server:
`REUSE_DISPLAY=:0 bash manipulation_demo_headless.sh` (authorize once on the
host session with `xhost +local:`).

Everything downstream (topic → MJPEG → embedded page) is proven repo pattern
(`web_video_server`, see `packages/npu/ryzenai_cvml`).

## Camera topic

The stream defaults to `/color_image5` (the O3DE camera feed documented in
`packages/robotics/rai/Blog/BLOG.md`). Change `TOPIC` in
`patch_manipulation_streamlit.py` if the level publishes a different topic.
