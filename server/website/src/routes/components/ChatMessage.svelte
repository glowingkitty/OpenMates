<script lang="ts">
  import type { SvelteComponent } from 'svelte';
  
  export let role: 'user' | string = 'user';
  
  // Define types for message content parts
  type AppCardData = {
    component: new (...args: any[]) => SvelteComponent;
    props: Record<string, any>;
  };

  type MessagePart = {
    type: 'text' | 'app-cards';
    content: string | AppCardData[];
  };

  export let messageParts: MessagePart[] = [];
  export let showScrollableContainer: boolean = false;
  export let appCards: AppCardData[] | undefined = undefined;
  export let defaultHidden: boolean = false;

  // If appCards is provided, add it to messageParts
  $: if (appCards && (!messageParts || messageParts.length === 0)) {
    messageParts = [
      { type: 'text', content: '' },
      { type: 'app-cards', content: appCards }
    ];
  }

  // Capitalize first letter of mate name
  $: displayName = role === 'user' ? '' : role.charAt(0).toUpperCase() + role.slice(1);

  // Add new prop for animation control
  export let animated: boolean = false;
</script>

<div class="chat-message">
  {#if role !== 'user'}
    <div class="mate-profile {role}"></div>
  {/if}
  
  <div class="message-align-{role === 'user' ? 'right' : 'left'}">
    <div class="{role === 'user' ? 'user' : 'mate'}-message-content {animated ? 'message-animated' : ''} {defaultHidden ? 'default_hidden' : ''}">
      {#if role !== 'user'}
        <div class="chat-mate-name">{displayName}</div>
      {/if}
      
      <div class="chat-message-text">
        {#if messageParts && messageParts.length > 0}
          {#each messageParts as part}
            {#if part.type === 'text'}
              <div class="text-content">{@html part.content}</div>
            {:else if part.type === 'app-cards'}
              <div class="chat-app-cards-container" class:scrollable={showScrollableContainer}>
                {#each (part.content as AppCardData[]) as card}
                  <svelte:component this={card.component} {...card.props} />
                {/each}
              </div>
            {/if}
          {/each}
        {:else}
          <div class="text-content">
            {@html $$slots.default ? '' : ''}
            <slot />
          </div>
          
          {#if appCards && appCards.length > 0}
            <div class="chat-app-cards-container" class:scrollable={showScrollableContainer}>
              {#each appCards as card}
                <svelte:component this={card.component} {...card.props} />
              {/each}
            </div>
          {/if}
        {/if}
      </div>
    </div>
  </div>
</div>

<style>
  .chat-app-cards-container {
    display: flex;
    gap: 20px;
    margin-top: 15px;
  }

  .chat-app-cards-container.scrollable {
    overflow-x: auto;
    padding-bottom: 15px;
    /* Enable smooth scrolling */
    scroll-behavior: smooth;
    /* Hide scrollbar but keep functionality */
    scrollbar-width: none;
    -ms-overflow-style: none;
  }

  .chat-app-cards-container.scrollable::-webkit-scrollbar {
    display: none;
  }

  .text-content {
    margin-bottom: 15px;
    white-space: pre-line;
  }

  /* Remove margin from last text content */
  .text-content:last-child {
    margin-bottom: 0;
  }

  /* Adjust line breaks to have a more natural spacing */
  :global(.text-content br) {
    display: block;
    content: "";
    margin-top: 0.25em;
  }
</style>