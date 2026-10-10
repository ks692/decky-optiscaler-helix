"""HelixSR support: DLSS Model E reconstruction on AMD GPUs via OptiScaler.

Upstream HelixSR (1.5.x) is an ``nvngx.dll`` NGX core that OptiScaler's DLSS
backend loads. This module automates the documented per-game route:

1. One-time setup builds the network into ``nvngx.dll`` on the Deck.
2. Per game with OptiScaler installed: copy ``nvngx.dll`` into a ``HelixSR``
   folder next to ``OptiScaler.ini`` and set ``Dx12Upscaler = dlss`` plus
   ``NvngxPath`` to that file. Original ini values are journaled and
   restored on uninstall.
3. The Steam launch option ``PROTON_FORCE_NVAPI=1 DXVK_NVAPI_GPU_ARCH=AD100
   %command%`` is shown for copy-paste; it is written by the frontend
   through the Steam client, following this repo's launchOptions pattern.
"""
