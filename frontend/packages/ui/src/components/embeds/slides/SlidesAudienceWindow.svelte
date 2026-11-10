<!--
  frontend/packages/ui/src/components/embeds/slides/SlidesAudienceWindow.svelte

  Content of the second (audience) window opened by presenter mode. It knows
  only the random session id from its URL; the deck arrives through the
  BroadcastChannel once the presenter answers its hello. Shows nothing but the
  slide (SlidesAudienceView). Navigation here is mirrored to the presenter, and
  Esc, the exit button or the presenter's bye close this window.
-->
<script lang="ts">
  import SlidesAudienceView from './SlidesAudienceView.svelte';
  import { parseSlidesMarkup, type Deck } from './slidesMarkup';
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
    sessionId: string;
    /** Called when the presentation ended; the route closes the window. */
    onEnded: () => void;
  }

  let { sessionId, onEnded }: Props = $props();

  const HELLO_RETRY_MS = 1000;

  let deck = $state<Deck | null>(null);
  let position = $state<PresentPosition>({ index: 0, step: 0 });
  let channel: BroadcastChannel | null = null;

  function send(message: PresentMessage) {
    channel?.postMessage(message);
  }

  function onAction(action: Exclude<PresentAction, 'exit'>) {
    if (!deck) return;
    position = applyAction(deck.slides, position, action);
    send({ type: 'goto', index: position.index, step: position.step });
  }

  function exit() {
    send({ type: 'bye' });
    onEnded();
  }

  $effect(() => {
    if (!sessionId) return;
    const bus = new BroadcastChannel(presentChannelName(sessionId));
    channel = bus;
    bus.onmessage = (event: MessageEvent) => {
      const message = event.data;
      if (!isPresentMessage(message)) return;
      if (message.type === 'deck') {
        const parsed = parseSlidesMarkup(message.markup);
        if (!parsed.ok) return;
        deck = parsed.deck;
        position = clampPosition(parsed.deck.slides, message);
      } else if (message.type === 'goto' && deck) {
        position = clampPosition(deck.slides, message);
      } else if (message.type === 'bye') {
        onEnded();
      }
    };
    // The presenter may not be listening yet when this window finishes loading.
    const hello = setInterval(() => {
      if (deck) clearInterval(hello);
      else send({ type: 'hello' });
    }, HELLO_RETRY_MS);
    send({ type: 'hello' });
    const onPageHide = () => send({ type: 'bye' });
    window.addEventListener('pagehide', onPageHide);
    return () => {
      clearInterval(hello);
      window.removeEventListener('pagehide', onPageHide);
      bus.close();
      channel = null;
    };
  });
</script>

{#if deck}
  <SlidesAudienceView {deck} {position} {onAction} onExit={exit} />
{/if}
