# Frontend design direction

The interface is designed as a private research room: a deep ocean-blue glass field, cool ivory typography, and quiet cyan/amber refractions. The home view treats each thread as a floating work object above a fractured-glass surface, with radial shard lines and slow environmental drift. The detail view deliberately flattens into a reading desk so the user can scan a thread, answer one question, and inspect the generated requirement without visual noise.

The spatial layer keeps real HTML text above the shader. WebGPU and WebGL share the same projection model, while CSS cards remain the usable fallback. Reduced motion removes drift and shortens transitions. When the API is unavailable, demo threads remain browseable as an explicit read-only preview instead of attempting `demo-*` detail requests.

Acceptance checks:

- Home cards are keyboard reachable and can be opened from the thread index.
- Escape and Back return from detail to the spatial workspace.
- Detail content scrolls as a complete document on narrow windows.
- Email guard refreshes the complete thread state after the server mutation.
- WebGPU initialization handles unmount races and disposes renderer, geometry, and materials.
