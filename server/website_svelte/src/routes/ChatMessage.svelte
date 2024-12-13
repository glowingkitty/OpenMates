<script lang="ts">
  import type { SvelteComponent } from 'svelte';
  
  export let type: 'user' | 'mate' = 'user';
  export let mateName: string | undefined = undefined;
  export let mateProfile: string | undefined = undefined;
  
  type AppCardData = {
    component: new (...args: any[]) => SvelteComponent;
    props: Record<string, any>;
  };
  
  export let appCards: AppCardData[] | undefined = undefined;
  export let showScrollableContainer: boolean = false;
</script>

<div class="chat-message">
  {#if type === 'mate' && mateProfile}
    <div class="mate-profile {mateProfile}"></div>
  {/if}
  
  <div class="message-align-{type === 'user' ? 'right' : 'left'}">
    <div class="{type}-message-content">
      {#if type === 'mate' && mateName}
        <div class="chat-mate-name">{mateName}</div>
      {/if}
      <div class="chat-message-text">
        <slot />
        
        {#if appCards && appCards.length > 0}
          <div class="chat-app-cards-container" class:scrollable={showScrollableContainer}>
            {#each appCards as card}
              <svelte:component this={card.component} {...card.props} />
            {/each}
          </div>
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
</style>