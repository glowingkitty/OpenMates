<!--
  frontend/packages/ui/src/components/embeds/slides/SlidesPresentation.svelte

  Presenting a deck from the fullscreen viewer, local only. Two modes:
  - 'single': this window becomes the audience view (slide only, full screen).
  - 'presenter': the audience view lives in `popup` (a same-origin window opened
    by the viewer's click handler) and this window becomes the presenter view.
    The windows stay in sync through a BroadcastChannel named after a random
    session id: the popup says hello, this window answers with the deck markup
    and the position, and either side's navigation is mirrored to the other.
    Closing either window ends the presentation (bye message and a closed-popup
    check, because a closing window cannot always send a message).
  The view is moved to document.body so no transformed ancestor (the fullscreen
  slide-in) can break its fixed positioning.
-->
<script lang="ts">
  import SlidesAudienceView from './SlidesAudienceView.svelte';
  import SlidesPresenterView from './SlidesPresenterView.svelte';
  import { parseSlidesMarkup } from './slidesMarkup';
  import {
    applyAction,
    clampPosition,
    isPresentMessage,
    presentChannelName,
    type PresentAction,
    type PresentMessage,
    type PresentPosition
  } from './slidesPresentation';

  interface Props {
    markup: string;
    startIndex: number;
    mode: 'single' | 'presenter';
    onExit: () => void;
    /** Presenter mode: the audience window and the id of the channel it listens on. */
    popup?: Window | null;
    sessionId?: string;
    /** Shown briefly (audience view) or permanently (presenter view) when the second window was blocked. */
    notice?: string;
  }

  let { markup, startIndex, mode, onExit, popup = null, sessionId = '', notice = '' }: Props = $props();

  const POPUP_POLL_MS = 500;

  let parsed = $derived(parseSlidesMarkup(markup));
  let slides = $derived(parsed.ok ? parsed.deck.slides : []);
  let position = $state<PresentPosition>({ index: 0, step: 0 });
  let channel: BroadcastChannel | null = null;

  $effect(() => {
    position = clampPosition(slides, { index: startIndex, step: 0 });
  });

  function send(message: PresentMessage) {
    channel?.postMessage(message);
  }

  function setPosition(next: PresentPosition) {
    position = next;
    send({ type: 'goto', index: next.index, step: next.step });
  }

  function onAction(action: Exclude<PresentAction, 'exit'>) {
    setPosition(applyAction(slides, position, action));
  }

  function onGoto(index: number) {
    setPosition(clampPosition(slides, { index, step: 0 }));
  }

  $effect(() => {
    if (mode !== 'presenter' || !sessionId) return;
    const channelName = presentChannelName(sessionId);
    const bus = new BroadcastChannel(channelName);
    channel = bus;
    const sendDeck = () => send({ type: 'deck', markup, index: position.index, step: position.step });
    bus.onmessage = (event: MessageEvent) => {
      const message = event.data;
      if (!isPresentMessage(message)) return;
      if (message.type === 'hello') sendDeck();
      else if (message.type === 'goto') position = clampPosition(slides, message);
      else if (message.type === 'bye') onExit();
    };
    const poll = setInterval(() => {
      if (popup?.closed) onExit();
    }, POPUP_POLL_MS);
    const onPageHide = () => send({ type: 'bye' });
    window.addEventListener('pagehide', onPageHide);
    return () => {
      clearInterval(poll);
      window.removeEventListener('pagehide', onPageHide);
      send({ type: 'bye' });
      bus.close();
      channel = null;
      if (popup && !popup.closed) popup.close();
    };
  });

  /** Moves the node to document.body for the lifetime of the component. */
  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }
</script>

<div use:portal data-testid="slides-presentation" data-mode={mode}>
  {#if parsed.ok && slides.length > 0}
    {#if mode === 'presenter'}
      <SlidesPresenterView deck={parsed.deck} {position} {onAction} {onExit} {onGoto} {notice} />
    {:else}
      <SlidesAudienceView deck={parsed.deck} {position} {onAction} {onExit} {notice} />
    {/if}
  {/if}
</div>
