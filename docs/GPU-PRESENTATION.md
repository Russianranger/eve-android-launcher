# Follow-up: replace the VNC presentation leg

The current development branch keeps native ARM64EC DXVK 2.4.1 and the accepted
pristine Mesa 26.2.4 KGSL driver with optional linear presentation. Existing
startup probes require the actual A740, exact selected driver, Vulkan device and
presentation, native shader/readback and three visible RFB frames. These gates,
GPU completion fences and the WineD3D recovery selection remain authoritative.
No older main GPU package is imported by 0.1.23.

GPU rendering still presents through the Vulkan software X11 swapchain into
Xtigervnc, then loopback RFB and an Android bitmap or separate Surface. The branch
also retains its qualified optional shared-memory X11 transport. These CPU
readback/copy/composition legs can limit delivered frames even when EVE's HUD
reports a higher rate. Received/drawn counters do not measure physical panel scans.

A later Android-surface X server, similar in architecture to Termux:X11, could
remove the Xtigervnc/RFB hop:

1. Host the X server in this app with a private Unix socket and the existing
   lifecycle/session ownership model. Keep network listeners closed.
2. Transfer Surface/HardwareBuffer handles through a narrow native interface
   with explicit ownership, release fences and bounded buffering. Retain a
   software presentation path and current RFB runtime fallback.
3. Qualify DRI3/Present, Vulkan WSI and buffer import against the exact glibc
   runtime. Android bionic and guest glibc libraries cannot be interchanged;
   exchange documented IPC/buffer handles rather than arbitrary library objects.
4. Preserve controller/gear/text layering, input coordinates, resize/recreation,
   app switching, process journaling, memory reserve and shutdown behavior.
5. Measure present-to-screen latency, actual displayed frames, CPU/RSS/temperature
   and graphics correctness on Thor. Any permission/containment change requires
   separate explicit approval; do not make one as a performance workaround.

No replacement X server or Android permission change is implemented in 0.1.23.
