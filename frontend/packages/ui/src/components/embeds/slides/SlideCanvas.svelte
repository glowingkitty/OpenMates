<!--
  frontend/packages/ui/src/components/embeds/slides/SlideCanvas.svelte

  Read-only rendering of one slide. The slide lives on a fixed 1920-unit-wide
  canvas (height 1080/1200/1440 by aspect) that is scaled uniformly with a CSS
  transform to fit its container. Elements are absolutely positioned; text is
  rebuilt from the parsed model as real nodes (never HTML strings), blocks run
  in the existing sandboxed InteractiveHtmlFrame, images use the encrypted image
  pipeline, videos are placeholders until the media phase.
  Animations/transitions are plain CSS and disabled under prefers-reduced-motion.
-->
<script lang="ts">
  import InteractiveHtmlFrame from '../code/InteractiveHtmlFrame.svelte';
  import SlideImageElement from './SlideImageElement.svelte';
  import { getTemplate, placeElements, resolveColor, resolveFont, templateStyleVars } from './slidesTemplates';
  import type { InlineNode, Slide, SlideElement } from './slidesMarkup';

  interface Props {
    slide: Slide;
    /** Canvas size in units (from the deck). */
    width: number;
    height: number;
    template: string;
    /** Build steps shown so far; elements with a higher step are hidden. */
    step?: number;
    /** Blocks accept input (fullscreen) or stay inert (preview cards, thumbnails). */
    interactive?: boolean;
    /** Play element animations and the slide transition. */
    animated?: boolean;
  }

  let { slide, width, height, template: templateId, step = 99, interactive = false, animated = false }: Props = $props();

  let viewportWidth = $state(0);
  let scale = $derived(viewportWidth > 0 ? viewportWidth / width : 0);
  let template = $derived(getTemplate(templateId));
  let placed = $derived(placeElements(slide, template, height));
  let visible = $derived(placed.filter((entry) => entry.element.step <= step));

  function boxStyle(box: { x: number; y: number; w: number; h: number }): string {
    return `left:${box.x}px;top:${box.y}px;width:${box.w}px;height:${box.h}px`;
  }

  function textStyle(entry: (typeof placed)[number]): string {
    const element = entry.element;
    if (element.type !== 'text') return '';
    const slot = entry.slot;
    const isHeading = element.role === 'title';
    const color = resolveColor(template, element.color ?? slot?.colorToken);
    const parts = [
      `font-size:${element.size ?? slot?.size ?? 40}px`,
      `font-weight:${element.weight ?? slot?.weight ?? 'normal'}`,
      `text-align:${element.align ?? slot?.align ?? 'left'}`,
      `font-family:${resolveFont(template, element.font, isHeading ? 'heading' : 'body')}`
    ];
    if (color) parts.push(`color:${color}`);
    if (slot?.italic) parts.push('font-style:italic');
    return parts.join(';');
  }

  function shapeStyle(element: Extract<SlideElement, { type: 'shape' }>): string {
    const fill = resolveColor(template, element.fill) ?? resolveColor(template, 'accent');
    const stroke = resolveColor(template, element.stroke);
    if (element.kind === 'line') return `background:${stroke ?? fill};height:6px`;
    const parts = [`background:${fill}`];
    if (stroke) parts.push(`border:6px solid ${stroke}`);
    if (element.kind === 'ellipse') parts.push('border-radius:50%');
    if (element.kind === 'triangle') parts.push('clip-path:polygon(50% 0, 100% 100%, 0 100%)');
    return parts.join(';');
  }
</script>

{#snippet inline(nodes: InlineNode[])}
  {#each nodes as node, index (index)}
    {#if node.kind === 'text'}
      {node.text}
    {:else if node.kind === 'br'}
      <br />
    {:else}
      <svelte:element this={node.tag}>{@render inline(node.children)}</svelte:element>
    {/if}
  {/each}
{/snippet}

<div
  class="slide-viewport"
  style:aspect-ratio="{width} / {height}"
  bind:clientWidth={viewportWidth}
  data-testid="slide-canvas"
  data-slide-id={slide.id}
>
  {#if scale > 0}
    <div
      class="slide-canvas"
      class:transition-fade={animated && slide.transition === 'fade'}
      class:transition-slide={animated && slide.transition === 'slide'}
      style="{templateStyleVars(template)};width:{width}px;height:{height}px;transform:scale({scale})"
    >
      {#each visible as entry (entry.element.id)}
        {@const element = entry.element}
        <div
          class="slide-element el-{element.type}"
          class:anim-fade={animated && element.animate === 'fade'}
          class:anim-slide-in={animated && element.animate === 'slide-in'}
          class:anim-appear={animated && (element.animate === 'appear' || (element.step > 0 && !element.animate))}
          style={boxStyle(entry.box)}
          data-element-id={element.id}
        >
          {#if element.type === 'text'}
            <div class="text-body" style={textStyle(entry)}>{@render inline(element.content)}</div>
          {:else if element.type === 'image'}
            <SlideImageElement embedRef={element.ref} alt={element.alt} fit={element.fit} />
          {:else if element.type === 'video'}
            <div class="video-placeholder" role="img" aria-label={element.alt || element.provider}>
              <span class="play-glyph" aria-hidden="true"></span>
            </div>
          {:else if element.type === 'shape'}
            <div class="shape shape-{element.kind}" style={shapeStyle(element)}></div>
          {:else if element.type === 'notepad'}
            <div class="card-element">
              <div class="card-title">{element.title}</div>
            </div>
          {:else if element.type === 'todo'}
            <div class="card-element">
              <div class="card-title">{element.title}</div>
              <ul class="todo-list">
                {#each element.items as item, index (index)}
                  <li class:done={item.done}>
                    <span class="check" aria-hidden="true">{item.done ? '✓' : ''}</span>{item.label}
                  </li>
                {/each}
              </ul>
            </div>
          {:else if element.type === 'link'}
            <!-- Rendered as a styled label; opening external links is an explicit action of the host. -->
            <a class="link-label" href={element.href} target="_blank" rel="noopener noreferrer" tabindex={interactive ? 0 : -1}>{element.label}</a>
          {:else if element.type === 'block'}
            <InteractiveHtmlFrame code={element.body} title={element.title || 'Interactive block'} {interactive} />
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .slide-viewport {
    position: relative;
    width: 100%;
    overflow: hidden;
    background: var(--color-grey-0);
  }

  /* Visible slide edge on any background; drawn above the scaled canvas. */
  .slide-viewport::after {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: inherit;
    box-shadow: inset 0 0 0 1px var(--color-grey-40);
    pointer-events: none;
    z-index: 1;
  }

  .slide-canvas {
    /* One canvas unit: sizes inside a slide are canvas units that scale with the slide, never rem. */
    --slide-unit: 1px;
    position: absolute;
    top: 0;
    left: 0;
    transform-origin: top left;
    background: var(--slide-color-background);
    color: var(--slide-color-foreground);
    font-family: var(--slide-font-body);
    overflow: hidden;
  }

  .slide-element {
    position: absolute;
    box-sizing: border-box;
    overflow: hidden;
  }

  .el-block,
  .el-shape {
    overflow: visible;
  }

  .el-shape {
    display: flex;
    align-items: center;
  }

  .text-body {
    width: 100%;
    height: 100%;
    line-height: 1.25;
    overflow-wrap: anywhere;
  }

  .text-body :global(ul),
  .text-body :global(ol) {
    margin: 0;
    padding-inline-start: 1.2em;
  }

  .shape {
    width: 100%;
    height: 100%;
    box-sizing: border-box;
  }

  .video-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    background: var(--slide-color-surface);
  }

  .play-glyph {
    width: 0;
    height: 0;
    border-style: solid;
    border-width: 60px 0 60px 100px;
    border-color: transparent transparent transparent var(--slide-color-muted);
  }

  .card-element {
    width: 100%;
    height: 100%;
    padding: 24px;
    box-sizing: border-box;
    background: var(--slide-color-surface);
    border-radius: 16px;
    font-size: calc(32 * var(--slide-unit));
    overflow: hidden;
  }

  .card-title {
    font-weight: bold;
    margin-bottom: 12px;
    color: var(--slide-color-foreground);
  }

  .todo-list {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .todo-list li {
    display: flex;
    gap: 16px;
    align-items: center;
    margin-bottom: 8px;
  }

  .todo-list li.done {
    color: var(--slide-color-muted);
    text-decoration: line-through;
  }

  .check {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border: 3px solid var(--slide-color-muted);
    border-radius: 6px;
    flex: none;
  }

  .link-label {
    font-size: calc(36 * var(--slide-unit));
    color: var(--slide-color-accent);
    text-decoration: underline;
  }

  .anim-fade {
    animation: slide-fade-in 0.5s ease both;
  }

  .anim-slide-in {
    animation: slide-slide-in 0.5s ease both;
  }

  .anim-appear {
    animation: slide-appear 0.01s linear both;
  }

  .transition-fade {
    animation: slide-fade-in 0.4s ease both;
  }

  .transition-slide {
    animation: slide-slide-in 0.4s ease both;
  }

  @keyframes slide-fade-in {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  @keyframes slide-slide-in {
    from { opacity: 0; translate: 120px 0; }
    to { opacity: 1; translate: 0 0; }
  }

  @keyframes slide-appear {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  @media (prefers-reduced-motion: reduce) {
    .anim-fade,
    .anim-slide-in,
    .anim-appear,
    .transition-fade,
    .transition-slide {
      animation: none;
    }
  }
</style>
