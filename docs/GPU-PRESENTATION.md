# Optional DXVK / Turnip renderer and presentation follow-up

The `dxvk-turnip` performance renderer uses the existing, pinned Wine 10.13
ARM64EC / FEX-2510 rootfs. Official DXVK 2.7.1 **x64** `d3d11.dll` and
`dxgi.dll` execute through that translator; these are not ARM64EC DXVK builds.
The Wine Vulkan bridge loads a native ARM64 **glibc** Turnip ICD. Android
AdrenoTools/bionic driver ZIPs cannot be substituted into this glibc rootfs.

Mesa does not publish this glibc KGSL binary. The renderer build produces our
ICD from the unmodified official Mesa 25.2.8 release, in Debian 12 Bookworm
to match the installed rootfs. It selects only `freedreno`, `kgsl` and X11,
with Gallium, LLVM, GLX and EGL disabled. The manifest records SHA-256 for
every shipped member, the output archive, and both official input releases.
The corresponding source artifact preserves those release archives, complete
license texts, the build scripts, compiler version and Debian package list.
The official release pins are also enforced in the installed Python backend.

The existing rootfs archive was independently downloaded and its unchanged
SHA-256 `f036c00a290abb953bec26be80c4d8fe492fd986e7a589c51008124432c8641e`
verified before inspecting its contents. It already contains the Vulkan loader
`libvulkan.so.1.3.239` (`libvulkan1` 1.3.239.0-1), XCB 1.15-1, X11 1.8.4,
`libX11-xcb.so.1`, `libxcb-xfixes.so.0`, `libxcb-randr.so.0`, and the
Xau/Xdmcp/bsd/md dependencies. It also contains the DRI3/Present/SHM/sync/Xshmfence
libraries even though this profile presents through the software WSI path.
The renderer build rejects a missing shared dependency and any libdrm linkage;
static libstdc++/libgcc avoid introducing a newer C++ runtime dependency. No
additional Vulkan loader or distro binary is downloaded on the device.

| Input | Source | SHA-256 |
| --- | --- | --- |
| DXVK 2.7.1 binary release | <https://github.com/doitsujin/dxvk/releases/tag/v2.7.1> | `d85ce7c79f57ecd765aaa1b9e7007cb875e6fde9f6d331df799bce73d513ce87` |
| DXVK 2.7.1 source archive | <https://github.com/doitsujin/dxvk/archive/refs/tags/v2.7.1.tar.gz> | `4966be884da4a1ded7e38ee018caef5626bd06bbd0853715084b1a1644aaaf02` |
| Mesa 25.2.8 source release | <https://archive.mesa3d.org/mesa-25.2.8.tar.xz> | `097842f3e49d996868b38688db87b006f7d4541e93ce86d2f341d8b3e7be7c93` |

No new client source, CCP files, rootfs, exposed listener or device bind is
introduced. The existing `-b /dev` makes `/dev/kgsl-3d0` visible if Android's
permissions permit this app to open it. PRoot does not grant those permissions;
the startup check requires an accessible character device. The existing
loopback network gate, exact EVE build/hash checks, memory reserve and process
journal remain mandatory for either renderer.

The GPU profile forces `d3d11,dxgi=n`, removes the llvmpipe environment settings
and points `VK_ICD_FILENAMES` / `VK_DRIVER_FILES` exclusively at the verified
ICD. Mesa's `MESA_VK_WSI_DEBUG=sw` selects a CPU copy for the X11 presentation
leg; GPU command processing and shaders still use Turnip. This avoids depending
on DRI3/dma-buf support in Xtigervnc. A small original x64 helper runs through
Wine, creates a hardware D3D11 device and an X11 swapchain, clears it and
presents once. The supervisor journals and bounds that process like its other
helpers. Failure selects WineD3D with a visible explanation. Probe success is
only startup compatibility evidence, not proof that EVE renders correctly or
that performance improves on the Thor.

DXVK DLLs are copied atomically into the private prefix's system32 directory;
Wine's builtin symlinks are replaced without writing through them. The
WineD3D profile uses `d3d11,dxgi=b`, so the original Wine builtins remain usable
even with those native DLLs installed. Package extraction is bounded and rejects
links, traversal, duplicate entries, architecture mismatches and hash failures.

## Replace the VNC presentation leg later

The current presentation path is GPU render → Vulkan software X11 swapchain →
Xtigervnc framebuffer → loopback RFB → Android bitmap/surface. A faster GPU
can increase EVE's own FPS while the remaining readback/copy/transport limits
the received and drawn counters. Compare all three numbers at a fixed scene;
do not report a renderer gain from EVE's counter alone.

A follow-up can use an Android-surface X server similar to Termux:X11:

1. Host an X server in the APK that accepts only this app's private Unix socket,
   with lifecycle ownership and session identity checks matching the current
   display supervisor. Do not expose a network listener.
2. Pass an Android Surface/HardwareBuffer to the native X server using a narrow
   JNI interface, with explicit buffer ownership and fences. Retain a software
   buffer path for devices that cannot share buffers.
3. Qualify X11 Vulkan presentation, DRI3/Present and any required buffer import
   against the pinned glibc Wine/Turnip rootfs. Android/bionic and glibc cannot
   exchange arbitrary library objects; only documented IPC/buffer handles cross
   the boundary. Any cross-UID or Android permission changes require separate
   containment review.
4. Measure present-to-screen latency, frames submitted versus displayed,
   temperature, CPU time and RSS before adopting it. Preserve the RFB path as
   a runtime fallback while qualifying resize, activity recreation, background
   transitions and input coordinates on the Thor.

This pass implements none of that X-server replacement.
