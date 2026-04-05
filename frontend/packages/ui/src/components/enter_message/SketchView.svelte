<!-- frontend/packages/ui/src/components/enter_message/SketchView.svelte
     Drawing canvas overlay for the message input field.
     Architecture: mirrors CameraView / MapsView — fills the .message-field container
     (which grows to 400px when showSketch is true in MessageInput.svelte) via
     `position: absolute; inset: 0`. Dispatches 'sketchcaptured' with a JPEG Blob when
     the user clicks "Done", and 'close' when dismissed.

     The canvas always has a white background. A CSS dot-grid overlay (canvas-wrapper
     ::before pseudo-element) provides scale reference while drawing; it is NOT part of
     the exported image. A ResizeObserver watches the wrapper so fitCanvas() re-runs
     whenever the message-field expands (e.g. fullscreen expand button) — same as MapsView
     which calls map.invalidateSize() on container resize.

     Future plans (not yet implemented):
       - Save the drawing as a "sketch" embed type that can be re-opened and edited.
       - For now, the canvas is exported as a plain JPEG image (same pipeline as camera photos).

     See: docs/architecture/message-input-field.md for overlay conventions.
-->
<script lang="ts">
    import { createEventDispatcher, onMount, onDestroy, tick } from 'svelte';
    import { slide } from 'svelte/transition';
    import { tooltip } from '../../actions/tooltip';
    import { text } from '@repo/ui';

    const dispatch = createEventDispatcher();

    // ─── Tool types ──────────────────────────────────────────────────────────
    type Tool = 'pen' | 'eraser';

    // ─── Props ───────────────────────────────────────────────────────────────
    interface Props {
        /** Whether the parent message field is currently in fullscreen mode. */
        isFullscreen?: boolean;
    }
    let { isFullscreen = false }: Props = $props();

    // ─── State ───────────────────────────────────────────────────────────────
    let canvas = $state<HTMLCanvasElement>();
    let ctx: CanvasRenderingContext2D | null = null;

    let currentTool = $state<Tool>('pen');
    let currentColor = $state('#000000');
    let strokeWidth = $state(3);
    let isDrawing = false;
    let hasStrokes = $state(false); // track whether anything has been drawn

    // Undo history: each entry is a full ImageData snapshot taken before each stroke begins.
    // Capped at MAX_UNDO_STEPS to avoid unbounded memory usage.
    const MAX_UNDO_STEPS = 30;
    let undoHistory = $state<ImageData[]>([]);
    let canUndo = $derived(undoHistory.length > 0);

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

    // ResizeObserver watching the canvas wrapper so fitCanvas() re-runs when the
    // message-field expands or collapses (e.g. fullscreen expand button).
    let wrapperResizeObserver: ResizeObserver | null = null;

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
    onMount(async () => {
        if (!canvas) return;
        ctx = canvas.getContext('2d');
        if (!ctx) return;

        // Fill white background so JPEG export has a solid background (JPEG has no alpha).
        ctx.fillStyle = '#FFFFFF';
        ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

        // Wait one tick so the overlay has been laid out and the wrapper has real dimensions.
        await tick();

        // Initial fit-to-container transform
        fitCanvas();

        // Watch the wrapper for size changes caused by the message-field expand button or
        // any other container resize, mirroring how MapsView calls map.invalidateSize().
        const wrapper = canvas.parentElement;
        if (wrapper) {
            wrapperResizeObserver = new ResizeObserver(() => { fitCanvas(); });
            wrapperResizeObserver.observe(wrapper);
        }

        // Also handle viewport (window) resize as a fallback
        window.addEventListener('resize', fitCanvas);
    });

    onDestroy(() => {
        wrapperResizeObserver?.disconnect();
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

    /** Save the current canvas state to undo history before starting a new stroke. */
    function saveUndoSnapshot() {
        if (!ctx) return;
        const snapshot = ctx.getImageData(0, 0, CANVAS_W, CANVAS_H);
        undoHistory = [...undoHistory.slice(-(MAX_UNDO_STEPS - 1)), snapshot];
    }

    /** Undo the last drawn stroke by restoring the previous canvas snapshot. */
    function undo() {
        if (!ctx || undoHistory.length === 0) return;
        const prev = undoHistory[undoHistory.length - 1];
        undoHistory = undoHistory.slice(0, -1);
        ctx.putImageData(prev, 0, 0);
        // Re-evaluate hasStrokes: if we're back to a blank white canvas, mark as empty.
        // We check pixel data — if any non-white pixel exists, hasStrokes stays true.
        const data = ctx.getImageData(0, 0, CANVAS_W, CANVAS_H).data;
        let foundNonWhite = false;
        for (let i = 0; i < data.length; i += 4) {
            if (data[i] !== 255 || data[i + 1] !== 255 || data[i + 2] !== 255) {
                foundNonWhite = true;
                break;
            }
        }
        hasStrokes = foundNonWhite;
    }

    function startDraw(x: number, y: number) {
        if (!ctx) return;
        // Snapshot before stroke so it can be undone
        saveUndoSnapshot();
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
        // Save snapshot before clearing so user can undo the clear
        saveUndoSnapshot();
        ctx.globalCompositeOperation = 'source-over';
        ctx.fillStyle = '#FFFFFF';
        ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);
        hasStrokes = false;
    }

    /** Toggle fullscreen by dispatching to the parent (MessageInput). */
    function toggleFullscreen() {
        dispatch('toggleFullscreen');
    }

    // ─── Done / export ───────────────────────────────────────────────────────
    /**
     * Export the canvas as a JPEG Blob and dispatch 'sketchcaptured'.
     * The caller (MessageInput) passes the blob to insertImage() — same path as camera photo.
     *
     * The canvas already has a white background fill (set on mount and on clearCanvas),
     * so the JPEG (which has no alpha channel) will always have a clean white base.
     * The dot-grid overlay is CSS-only on the wrapper element and is NOT part of the export.
     *
     * Future: dispatch the ImageData / base64 string alongside a unique sketch ID so
     * the sketch can be saved as a dedicated "sketch" embed type that the user can
     * re-open and edit (not yet implemented).
     */
    function done() {
        if (!canvas) return;
        canvas.toBlob((blob) => {
            if (!blob) {
                console.error('[SketchView] Failed to export canvas as JPEG blob');
                return;
            }
            dispatch('sketchcaptured', { blob });
            dispatch('close');
        }, 'image/jpeg', 0.92);
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
    <!-- Maximize / minimize button — top-right corner, always visible over the drawing area -->
    <button
        class="overlay-fullscreen-btn clickable-icon {isFullscreen ? 'icon_minimize' : 'icon_fullscreen'}"
        onclick={toggleFullscreen}
        aria-label={isFullscreen ? $text('enter_message.fullscreen.exit_fullscreen') : $text('enter_message.fullscreen.enter_fullscreen')}
        use:tooltip
    ></button>

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

            <!-- Undo -->
            <button
                class="tool-btn {canUndo ? '' : 'disabled-btn'}"
                onclick={undo}
                disabled={!canUndo}
                aria-label={$text('sketchview.undo')}
                use:tooltip
            >
                <span class="undo-icon">↩</span>
            </button>

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
                aria-label={$text('common.done')}
                use:tooltip
            >
                {$text('common.done')}
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

    /* Maximize/minimize button — top-right corner of the overlay.
       Overrides buttons.css global styles so it stays compact and icon-only. */
    .overlay-fullscreen-btn {
        position: absolute;
        top: 10px;
        right: 12px;
        z-index: 10;
        /* Reset buttons.css overrides */
        min-width: unset !important;
        width: 32px !important;
        height: 32px !important;
        padding: 4px !important;
        border-radius: var(--radius-3) !important;
        background: rgba(255, 255, 255, 0.85) !important;
        border: none !important;
        opacity: 0.7;
        transition: opacity var(--duration-normal) var(--easing-in-out), background var(--duration-fast);
        cursor: pointer;
        margin-right: 0 !important;
        filter: none !important;
    }

    .overlay-fullscreen-btn:hover {
        opacity: 1 !important;
        background: rgba(255, 255, 255, 0.98) !important;
        scale: 1 !important;
    }

    /* Scrollable drawing surface — white background matches the canvas.
       The dot grid is rendered as a ::before pseudo-element on the wrapper so it is
       purely cosmetic (gives a sense of scale when zooming) and is NOT part of the
       exported JPEG (which comes directly from the canvas element). */
    .canvas-wrapper {
        flex: 1;
        position: relative;
        overflow: hidden;
        background: var(--color-grey-0);
        cursor: crosshair;
    }

    /* Dot grid overlay — dots scale with the CSS background-size so they always feel
       evenly spaced relative to the visible canvas area. Not exported. */
    .canvas-wrapper::before {
        content: '';
        position: absolute;
        inset: 0;
        pointer-events: none;
        background-image: radial-gradient(circle, rgba(0,0,0,0.18) 1px, transparent 1px);
        background-size: 24px 24px;
        z-index: var(--z-index-base);
    }

    .sketch-canvas {
        position: absolute;
        top: 0;
        left: 0;
        /* Sit above the ::before dot-grid overlay */
        z-index: var(--z-index-raised);
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
        gap: var(--spacing-4);
        flex-shrink: 0;
    }

    .toolbar-section {
        display: flex;
        align-items: center;
        gap: var(--spacing-2);
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
        gap: var(--spacing-2);
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
        gap: var(--spacing-2);
    }

    /* All toolbar buttons: override buttons.css global `button` reset so they stay compact.
       buttons.css sets: padding:25px 30px, border-radius:var(--radius-8), min-width:112px, height:41px
       which would completely break the toolbar layout. We override each property explicitly. */
    .tool-btn,
    .width-btn,
    .zoom-btn,
    .done-btn {
        min-width: unset !important;
        margin-right: 0 !important;
        filter: none !important;
    }

    .tool-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 32px !important;
        height: 32px !important;
        border-radius: var(--radius-3) !important;
        border: none !important;
        background: transparent !important;
        cursor: pointer;
        transition: background var(--duration-fast);
        padding: 0 !important;
        flex-shrink: 0;
    }

    /* Text-based tool icons (pen ✏, eraser ◻) */
    .tool-icon-text {
        font-size: 1rem;
        line-height: 1;
        pointer-events: none;
    }

    .tool-btn:hover {
        background: rgba(0,0,0,0.08) !important;
        scale: unset !important;
    }

    .tool-btn.active {
        background: rgba(0, 122, 255, 0.12) !important;
    }

    /* Undo icon text */
    .undo-icon {
        font-size: 1rem;
        line-height: 1;
        pointer-events: none;
    }

    .disabled-btn {
        opacity: 0.35;
        cursor: not-allowed;
    }

    /* Colour swatches — explicitly override buttons.css global `button` rules which set
       padding, border-radius:var(--radius-8), min-width:112px, height:41px, etc. We need these to
       remain small round circles regardless of the global button reset. */
    .color-swatch {
        width: 20px !important;
        height: 20px !important;
        min-width: unset !important;
        border-radius: 50% !important;
        border: 2px solid transparent !important;
        cursor: pointer;
        transition: transform var(--duration-fast), border-color var(--duration-fast);
        padding: 0 !important;
        flex-shrink: 0;
        /* Neutralise buttons.css filter / scale hover side-effects */
        filter: none !important;
        margin-right: 0 !important;
    }

    .color-swatch:hover {
        transform: scale(1.15);
        scale: unset !important;
        background-color: unset !important;
    }

    .color-swatch.active {
        border-color: #007AFF !important;
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
        width: 30px !important;
        height: 30px !important;
        border-radius: var(--radius-3) !important;
        border: none !important;
        background: transparent !important;
        cursor: pointer;
        padding: 0 !important;
        transition: background var(--duration-fast);
        flex-shrink: 0;
    }

    .width-btn:hover {
        background: rgba(0,0,0,0.08) !important;
        scale: unset !important;
    }

    .width-btn.active {
        background: rgba(0, 122, 255, 0.12) !important;
    }

    .width-dot {
        border-radius: 50%;
        background: var(--color-grey-100);
        display: block;
    }

    .width-btn.active .width-dot {
        background: #007AFF;
    }

    /* Zoom controls */
    .zoom-btn {
        min-width: 28px !important;
        height: 28px !important;
        border-radius: var(--radius-2) !important;
        border: none !important;
        background: transparent !important;
        cursor: pointer;
        font-size: 0.875rem;
        font-weight: 600;
        padding: 0 4px !important;
        transition: background var(--duration-fast);
        flex-shrink: 0;
        white-space: nowrap;
    }

    .zoom-btn:hover {
        background: rgba(0,0,0,0.08) !important;
        scale: unset !important;
    }

    .zoom-reset {
        min-width: 44px !important;
        font-size: 0.6875rem;
        font-weight: 500;
        color: rgba(0,0,0,0.5);
    }

    /* Done button */
    .done-btn {
        background: #007AFF !important;
        color: white;
        border: none !important;
        padding: 6px 16px !important;
        border-radius: var(--radius-8) !important;
        cursor: pointer;
        font-weight: 500;
        font-size: 0.875rem;
        height: 36px !important;
        transition: background var(--duration-fast), opacity var(--duration-fast);
        white-space: nowrap;
    }

    .done-btn:hover:not(.disabled) {
        background: #0056CC !important;
        scale: unset !important;
    }

    .done-btn.disabled {
        opacity: 0.4;
        cursor: not-allowed;
    }

    /* Dark mode — respect system preference.
       The canvas itself always stays white (sketch is always on a white background)
       but the surrounding chrome (overlay bg, toolbar) adapts to dark mode. */
    @media (prefers-color-scheme: dark) {
        .sketch-overlay {
            background: #1C1C1E;
        }

        /* Canvas wrapper stays white — the sketch surface is always white.
           The dot-grid dots are slightly more visible on white in dark mode. */
        .canvas-wrapper::before {
            background-image: radial-gradient(circle, rgba(0,0,0,0.22) 1px, transparent 1px);
        }

        .sketch-toolbar {
            background: rgba(28, 28, 30, 0.95);
            border-top-color: rgba(255,255,255,0.1);
        }

        .divider {
            background: rgba(255,255,255,0.15);
        }

        .overlay-fullscreen-btn {
            background: rgba(28, 28, 30, 0.85) !important;
        }

        .overlay-fullscreen-btn:hover {
            background: rgba(28, 28, 30, 0.98) !important;
        }

        .tool-btn:hover, .width-btn:hover, .zoom-btn:hover {
            background: rgba(255,255,255,0.1) !important;
        }

        .tool-btn.active, .width-btn.active {
            background: rgba(10, 132, 255, 0.2);
        }

        .zoom-reset {
            color: rgba(255,255,255,0.5);
        }

        .width-dot { background: var(--color-grey-0); }
        .width-btn.active .width-dot { background: #0A84FF; }
    }
</style>
