<!-- frontend/packages/ui/src/components/enter_message/SketchView.svelte
     Drawing canvas overlay for the message input field.
     Architecture: mirrors CameraView / MapsView — fills the .message-field container
     (which grows to 400px when showSketch is true in MessageInput.svelte) via
     `position: absolute; inset: 0`. Dispatches 'sketchcaptured' with a PNG Blob when
     the user clicks "Done", and 'close' when dismissed.

     Future plans (not yet implemented):
       - Save the drawing as a "sketch" embed type that can be re-opened and edited.
       - For now, the canvas is exported as a plain PNG image (same pipeline as camera photos).

     See: docs/architecture/message-input-field.md for overlay conventions.
-->
<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';
    import { slide } from 'svelte/transition';
    import { tooltip } from '../../actions/tooltip';
    import { text } from '@repo/ui';

    const dispatch = createEventDispatcher();

    // ─── Tool types ──────────────────────────────────────────────────────────
    type Tool = 'pen' | 'eraser';

    // ─── State ───────────────────────────────────────────────────────────────
    let canvas = $state<HTMLCanvasElement>();
    let ctx: CanvasRenderingContext2D | null = null;

    let currentTool = $state<Tool>('pen');
    let currentColor = $state('#000000');
    let strokeWidth = $state(3);
    let isDrawing = false;
    let hasStrokes = $state(false); // track whether anything has been drawn

    // Zoom / pan state
    let scale = $state(1);
    let panX = $state(0);
    let panY = $state(0);
    const MIN_SCALE = 0.25;
    const MAX_SCALE = 8;

    // Touch gesture helpers
    let lastTouchDist = 0;
    let isPanning = false;
    let lastPanX = 0;
    let lastPanY = 0;

    // Canvas logical resolution (pixels the user draws on)
    const CANVAS_W = 1200;
    const CANVAS_H = 900;

    // Preset pen colours
    const COLOR_PRESETS = [
        '#000000', '#FFFFFF', '#FF3B30', '#FF9500',
        '#FFCC00', '#34C759', '#007AFF', '#AF52DE',
    ] as const;

    // Preset stroke widths
    const WIDTH_PRESETS = [2, 5, 10, 20] as const;

    // ─── Lifecycle ───────────────────────────────────────────────────────────
    onMount(() => {
        if (!canvas) return;
        ctx = canvas.getContext('2d');
        if (!ctx) return;

        // Fill white background so PNG export has a solid background
        ctx.fillStyle = '#FFFFFF';
        ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

        // Initial fit-to-container transform
        fitCanvas();

        // Handle resize
        window.addEventListener('resize', fitCanvas);
    });

    onDestroy(() => {
        window.removeEventListener('resize', fitCanvas);
    });

    /**
     * Recalculate the initial transform so the canvas fits inside its container,
     * centred, without overflowing. Called once on mount and on window resize.
     */
    function fitCanvas() {
        if (!canvas) return;
        const wrapper = canvas.parentElement;
        if (!wrapper) return;
        const ww = wrapper.clientWidth;
        const wh = wrapper.clientHeight;
        const scaleX = ww / CANVAS_W;
        const scaleY = wh / CANVAS_H;
        const newScale = Math.min(scaleX, scaleY) * 0.95; // 5% margin
        scale = newScale;
        panX = (ww - CANVAS_W * newScale) / 2;
        panY = (wh - CANVAS_H * newScale) / 2;
    }

    // ─── Coordinate helpers ──────────────────────────────────────────────────

    /** Map a pointer event position (in wrapper-relative px) to canvas logical coords. */
    function toCanvasCoords(clientX: number, clientY: number): [number, number] {
        if (!canvas) return [0, 0];
        const rect = canvas.getBoundingClientRect();
        // The canvas element is transformed via CSS transform; getBoundingClientRect
        // returns the rendered (screen) rect, so we can map directly.
        const x = (clientX - rect.left) * (CANVAS_W / rect.width);
        const y = (clientY - rect.top) * (CANVAS_H / rect.height);
        return [x, y];
    }

    // ─── Drawing ─────────────────────────────────────────────────────────────

    function applyToolSettings() {
        if (!ctx) return;
        if (currentTool === 'eraser') {
            ctx.globalCompositeOperation = 'destination-out';
            ctx.strokeStyle = 'rgba(0,0,0,1)';
            ctx.lineWidth = strokeWidth * 3; // eraser is wider
        } else {
            ctx.globalCompositeOperation = 'source-over';
            ctx.strokeStyle = currentColor;
            ctx.lineWidth = strokeWidth;
        }
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
    }

    function startDraw(x: number, y: number) {
        if (!ctx) return;
        isDrawing = true;
        applyToolSettings();
        ctx.beginPath();
        ctx.moveTo(x, y);
    }

    function continueDraw(x: number, y: number) {
        if (!isDrawing || !ctx) return;
        ctx.lineTo(x, y);
        ctx.stroke();
        hasStrokes = true;
    }

    function endDraw() {
        if (!ctx) return;
        isDrawing = false;
        ctx.closePath();
        // Reset composite operation so subsequent fills (e.g. background refill) work normally
        ctx.globalCompositeOperation = 'source-over';
    }

    // ─── Mouse events ────────────────────────────────────────────────────────

    function onMouseDown(e: MouseEvent) {
        if (e.button !== 0) return;
        const [x, y] = toCanvasCoords(e.clientX, e.clientY);
        startDraw(x, y);
    }

    function onMouseMove(e: MouseEvent) {
        if (!isDrawing) return;
        const [x, y] = toCanvasCoords(e.clientX, e.clientY);
        continueDraw(x, y);
    }

    function onMouseUp() { endDraw(); }
    function onMouseLeave() { endDraw(); }

    // ─── Touch events ────────────────────────────────────────────────────────

    function getTouchDist(t1: Touch, t2: Touch): number {
        const dx = t1.clientX - t2.clientX;
        const dy = t1.clientY - t2.clientY;
        return Math.sqrt(dx * dx + dy * dy);
    }

    function onTouchStart(e: TouchEvent) {
        e.preventDefault();
        if (e.touches.length === 1) {
            // Single finger — draw
            isPanning = false;
            const t = e.touches[0];
            const [x, y] = toCanvasCoords(t.clientX, t.clientY);
            startDraw(x, y);
        } else if (e.touches.length === 2) {
            // Two fingers — begin pinch-zoom / pan, cancel drawing
            endDraw();
            isPanning = true;
            lastTouchDist = getTouchDist(e.touches[0], e.touches[1]);
            lastPanX = (e.touches[0].clientX + e.touches[1].clientX) / 2;
            lastPanY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
        }
    }

    function onTouchMove(e: TouchEvent) {
        e.preventDefault();
        if (e.touches.length === 1 && !isPanning) {
            const t = e.touches[0];
            const [x, y] = toCanvasCoords(t.clientX, t.clientY);
            continueDraw(x, y);
        } else if (e.touches.length === 2 && isPanning) {
            const dist = getTouchDist(e.touches[0], e.touches[1]);
            const midX = (e.touches[0].clientX + e.touches[1].clientX) / 2;
            const midY = (e.touches[0].clientY + e.touches[1].clientY) / 2;

            // Zoom
            const delta = dist / lastTouchDist;
            const newScale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale * delta));
            // Zoom toward the mid-point
            panX = midX - (midX - panX) * (newScale / scale);
            panY = midY - (midY - panY) * (newScale / scale);
            scale = newScale;

            // Pan
            panX += midX - lastPanX;
            panY += midY - lastPanY;

            lastTouchDist = dist;
            lastPanX = midX;
            lastPanY = midY;
        }
    }

    function onTouchEnd(e: TouchEvent) {
        e.preventDefault();
        if (e.touches.length === 0) {
            isPanning = false;
            endDraw();
        } else if (e.touches.length === 1 && isPanning) {
            // Dropped one finger while pinching — stop panning, don't draw
            isPanning = false;
        }
    }

    // ─── Wheel zoom ──────────────────────────────────────────────────────────

    function onWheel(e: WheelEvent) {
        e.preventDefault();
        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        const newScale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale * delta));
        // Zoom toward pointer
        if (!canvas) return;
        // The pointer relative to the canvas wrapper
        const wrapper = canvas.parentElement!;
        const wrapRect = wrapper.getBoundingClientRect();
        const px = e.clientX - wrapRect.left;
        const py = e.clientY - wrapRect.top;
        panX = px - (px - panX) * (newScale / scale);
        panY = py - (py - panY) * (newScale / scale);
        scale = newScale;
    }

    // ─── Zoom buttons ────────────────────────────────────────────────────────
    function zoomIn() {
        const newScale = Math.min(MAX_SCALE, scale * 1.25);
        if (!canvas) return;
        const wrapper = canvas.parentElement!;
        const cx = wrapper.clientWidth / 2;
        const cy = wrapper.clientHeight / 2;
        panX = cx - (cx - panX) * (newScale / scale);
        panY = cy - (cy - panY) * (newScale / scale);
        scale = newScale;
    }
    function zoomOut() {
        const newScale = Math.max(MIN_SCALE, scale / 1.25);
        if (!canvas) return;
        const wrapper = canvas.parentElement!;
        const cx = wrapper.clientWidth / 2;
        const cy = wrapper.clientHeight / 2;
        panX = cx - (cx - panX) * (newScale / scale);
        panY = cy - (cy - panY) * (newScale / scale);
        scale = newScale;
    }
    function resetZoom() { fitCanvas(); }

    // ─── Clear canvas ────────────────────────────────────────────────────────
    function clearCanvas() {
        if (!ctx) return;
        ctx.globalCompositeOperation = 'source-over';
        ctx.fillStyle = '#FFFFFF';
        ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);
        hasStrokes = false;
    }

    // ─── Done / export ───────────────────────────────────────────────────────
    /**
     * Export the canvas as a PNG Blob and dispatch 'sketchcaptured'.
     * The caller (MessageInput) passes the blob to insertImage() — same path as camera photo.
     *
     * Future: dispatch the ImageData / base64 string alongside a unique sketch ID so
     * the sketch can be saved as a dedicated "sketch" embed type that the user can
     * re-open and edit (not yet implemented).
     */
    function done() {
        if (!canvas) return;
        canvas.toBlob((blob) => {
            if (!blob) {
                console.error('[SketchView] Failed to export canvas as PNG blob');
                return;
            }
            dispatch('sketchcaptured', { blob });
            dispatch('close');
        }, 'image/png');
    }

    function handleClose() {
        dispatch('close');
    }

    // CSS transform string for the canvas element
    let canvasTransform = $derived(
        `transform: translate(${panX}px, ${panY}px) scale(${scale}); transform-origin: 0 0;`
    );
</script>

<div
    class="sketch-overlay"
    transition:slide={{ duration: 300, axis: 'y' }}
>
    <!-- Canvas drawing area -->
    <div
        class="canvas-wrapper"
        onwheel={onWheel}
        role="none"
    >
        <canvas
            bind:this={canvas}
            width={CANVAS_W}
            height={CANVAS_H}
            style={canvasTransform}
            class="sketch-canvas {currentTool === 'eraser' ? 'eraser-cursor' : 'pen-cursor'}"
            onmousedown={onMouseDown}
            onmousemove={onMouseMove}
            onmouseup={onMouseUp}
            onmouseleave={onMouseLeave}
            ontouchstart={onTouchStart}
            ontouchmove={onTouchMove}
            ontouchend={onTouchEnd}
        ></canvas>
    </div>

    <!-- Bottom toolbar -->
    <div class="sketch-toolbar">
        <!-- Left: close -->
        <div class="toolbar-section toolbar-left">
            <button
                class="clickable-icon icon_close"
                onclick={handleClose}
                aria-label={$text('sketchview.close')}
                use:tooltip
            ></button>
        </div>

        <!-- Centre: tools, colours, width, zoom -->
        <div class="toolbar-section toolbar-center">
            <!-- Tool selector -->
            <div class="tool-group">
                <button
                    class="tool-btn tool-btn-text {currentTool === 'pen' ? 'active' : ''}"
                    onclick={() => currentTool = 'pen'}
                    aria-label={$text('sketchview.pen')}
                    use:tooltip
                >
                    <!-- ✏ pen symbol -->
                    <span class="tool-icon-text">✏</span>
                </button>
                <button
                    class="tool-btn tool-btn-text {currentTool === 'eraser' ? 'active' : ''}"
                    onclick={() => currentTool = 'eraser'}
                    aria-label={$text('sketchview.eraser')}
                    use:tooltip
                >
                    <!-- ◻ eraser symbol -->
                    <span class="tool-icon-text">◻</span>
                </button>
            </div>

            <div class="divider"></div>

            <!-- Colour presets (hidden in eraser mode) -->
            {#if currentTool === 'pen'}
                <div class="color-group">
                    {#each COLOR_PRESETS as preset}
                        <button
                            class="color-swatch {currentColor === preset ? 'active' : ''}"
                            style="background: {preset};"
                            onclick={() => { currentColor = preset; currentTool = 'pen'; }}
                            aria-label={preset}
                        ></button>
                    {/each}
                    <!-- Custom colour picker -->
                    <label class="color-swatch color-picker-label" aria-label={$text('sketchview.custom_color')} title={$text('sketchview.custom_color')}>
                        <input
                            type="color"
                            bind:value={currentColor}
                            onchange={() => currentTool = 'pen'}
                            class="sr-only"
                        />
                        <span class="color-picker-icon" style="background: {currentColor};"></span>
                    </label>
                </div>

                <div class="divider"></div>
            {/if}

            <!-- Stroke width -->
            <div class="width-group">
                {#each WIDTH_PRESETS as w}
                    <button
                        class="width-btn {strokeWidth === w ? 'active' : ''}"
                        onclick={() => strokeWidth = w}
                        aria-label="{w}px"
                    >
                        <span class="width-dot" style="width: {Math.min(w * 1.5, 20)}px; height: {Math.min(w * 1.5, 20)}px;"></span>
                    </button>
                {/each}
            </div>

            <div class="divider"></div>

            <!-- Zoom controls -->
            <div class="zoom-group">
                <button
                    class="zoom-btn"
                    onclick={zoomOut}
                    aria-label={$text('sketchview.zoom_out')}
                    use:tooltip
                >−</button>
                <button
                    class="zoom-btn zoom-reset"
                    onclick={resetZoom}
                    aria-label={$text('sketchview.reset_zoom')}
                    use:tooltip
                >{Math.round(scale * 100)}%</button>
                <button
                    class="zoom-btn"
                    onclick={zoomIn}
                    aria-label={$text('sketchview.zoom_in')}
                    use:tooltip
                >+</button>
            </div>

            <div class="divider"></div>

            <!-- Clear -->
            <button
                class="tool-btn"
                onclick={clearCanvas}
                aria-label={$text('sketchview.clear')}
                use:tooltip
            >
                <span class="clickable-icon icon_delete"></span>
            </button>
        </div>

        <!-- Right: Done -->
        <div class="toolbar-section toolbar-right">
            <button
                class="done-btn {hasStrokes ? '' : 'disabled'}"
                onclick={done}
                disabled={!hasStrokes}
                aria-label={$text('sketchview.done')}
                use:tooltip
            >
                {$text('sketchview.done')}
            </button>
        </div>
    </div>
</div>

<style>
    /* Fill the .message-field container edge-to-edge — same pattern as CameraView / MapsView. */
    .sketch-overlay {
        position: absolute;
        inset: 0;
        background: #F5F5F5;
        z-index: 1000;
        display: flex;
        flex-direction: column;
        border-radius: 24px;
        overflow: hidden;
    }

    /* Scrollable drawing surface */
    .canvas-wrapper {
        flex: 1;
        position: relative;
        overflow: hidden;
        background: #E8E8E8;
        background-image:
            linear-gradient(rgba(0,0,0,0.07) 1px, transparent 1px),
            linear-gradient(90deg, rgba(0,0,0,0.07) 1px, transparent 1px);
        background-size: 20px 20px;
        cursor: crosshair;
    }

    .sketch-canvas {
        position: absolute;
        top: 0;
        left: 0;
        box-shadow: 0 4px 20px rgba(0,0,0,0.2);
        touch-action: none; /* prevent browser scroll/zoom while drawing */
    }

    .pen-cursor {
        cursor: crosshair;
    }

    .eraser-cursor {
        cursor: cell;
    }

    /* Bottom toolbar — matches CameraView bottom-bar style */
    .sketch-toolbar {
        height: 60px;
        background: rgba(255, 255, 255, 0.95);
        backdrop-filter: blur(8px);
        border-top: 1px solid rgba(0,0,0,0.08);
        display: flex;
        align-items: center;
        padding: 0 12px;
        gap: 8px;
        flex-shrink: 0;
    }

    .toolbar-section {
        display: flex;
        align-items: center;
        gap: 4px;
    }

    .toolbar-left {
        flex: 0 0 auto;
    }

    .toolbar-center {
        flex: 1;
        justify-content: center;
        flex-wrap: nowrap;
        overflow-x: auto;
        scrollbar-width: none;
        gap: 4px;
    }

    .toolbar-center::-webkit-scrollbar { display: none; }

    .toolbar-right {
        flex: 0 0 auto;
    }

    /* Divider between toolbar groups */
    .divider {
        width: 1px;
        height: 24px;
        background: rgba(0,0,0,0.15);
        margin: 0 4px;
        flex-shrink: 0;
    }

    /* Tool group */
    .tool-group, .color-group, .width-group, .zoom-group {
        display: flex;
        align-items: center;
        gap: 4px;
    }

    .tool-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 32px;
        height: 32px;
        border-radius: 8px;
        border: none;
        background: transparent;
        cursor: pointer;
        transition: background 0.15s;
        padding: 0;
        flex-shrink: 0;
    }

    /* Text-based tool icons (pen ✏, eraser ◻) */
    .tool-icon-text {
        font-size: 16px;
        line-height: 1;
        pointer-events: none;
    }

    .tool-btn:hover {
        background: rgba(0,0,0,0.08);
    }

    .tool-btn.active {
        background: rgba(0, 122, 255, 0.12);
    }

    /* Colour swatches */
    .color-swatch {
        width: 20px;
        height: 20px;
        border-radius: 50%;
        border: 2px solid transparent;
        cursor: pointer;
        transition: transform 0.15s, border-color 0.15s;
        padding: 0;
        flex-shrink: 0;
    }

    .color-swatch:hover {
        transform: scale(1.15);
    }

    .color-swatch.active {
        border-color: #007AFF;
        transform: scale(1.15);
    }

    /* White swatch needs a visible border so it's visible on white background */
    .color-swatch[style*="#FFFFFF"], .color-swatch[style*="rgb(255, 255, 255)"] {
        border-color: rgba(0,0,0,0.2);
    }

    /* Custom colour picker */
    .color-picker-label {
        position: relative;
        overflow: hidden;
        cursor: pointer;
    }

    .sr-only {
        position: absolute;
        width: 1px;
        height: 1px;
        padding: 0;
        margin: -1px;
        overflow: hidden;
        clip: rect(0,0,0,0);
        border: 0;
    }

    .color-picker-icon {
        display: block;
        width: 100%;
        height: 100%;
        border-radius: 50%;
        border: 2px dashed rgba(0,0,0,0.3);
    }

    /* Width selector */
    .width-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 30px;
        height: 30px;
        border-radius: 8px;
        border: none;
        background: transparent;
        cursor: pointer;
        padding: 0;
        transition: background 0.15s;
        flex-shrink: 0;
    }

    .width-btn:hover {
        background: rgba(0,0,0,0.08);
    }

    .width-btn.active {
        background: rgba(0, 122, 255, 0.12);
    }

    .width-dot {
        border-radius: 50%;
        background: #000;
        display: block;
    }

    .width-btn.active .width-dot {
        background: #007AFF;
    }

    /* Zoom controls */
    .zoom-btn {
        min-width: 28px;
        height: 28px;
        border-radius: 6px;
        border: none;
        background: transparent;
        cursor: pointer;
        font-size: 14px;
        font-weight: 600;
        padding: 0 4px;
        transition: background 0.15s;
        flex-shrink: 0;
        white-space: nowrap;
    }

    .zoom-btn:hover {
        background: rgba(0,0,0,0.08);
    }

    .zoom-reset {
        min-width: 44px;
        font-size: 11px;
        font-weight: 500;
        color: rgba(0,0,0,0.5);
    }

    /* Done button */
    .done-btn {
        background: #007AFF;
        color: white;
        border: none;
        padding: 6px 16px;
        border-radius: 20px;
        cursor: pointer;
        font-weight: 500;
        font-size: 14px;
        height: 36px;
        transition: background 0.15s, opacity 0.15s;
        white-space: nowrap;
    }

    .done-btn:hover:not(.disabled) {
        background: #0056CC;
    }

    .done-btn.disabled {
        opacity: 0.4;
        cursor: not-allowed;
    }

    /* Dark mode — respect system preference */
    @media (prefers-color-scheme: dark) {
        .sketch-overlay {
            background: #1C1C1E;
        }

        .canvas-wrapper {
            background: #2C2C2E;
            background-image:
                linear-gradient(rgba(255,255,255,0.05) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255,255,255,0.05) 1px, transparent 1px);
            background-size: 20px 20px;
        }

        .sketch-toolbar {
            background: rgba(28, 28, 30, 0.95);
            border-top-color: rgba(255,255,255,0.1);
        }

        .divider {
            background: rgba(255,255,255,0.15);
        }

        .tool-btn:hover, .width-btn:hover, .zoom-btn:hover {
            background: rgba(255,255,255,0.1);
        }

        .tool-btn.active, .width-btn.active {
            background: rgba(10, 132, 255, 0.2);
        }

        .zoom-reset {
            color: rgba(255,255,255,0.5);
        }

        .width-dot { background: #FFF; }
        .width-btn.active .width-dot { background: #0A84FF; }
    }
</style>
