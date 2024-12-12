<script lang="ts">
  export let type: 'user' | 'mate' = 'user';
  export let mateName: string | undefined = undefined;
  export let mateProfile: string | undefined = undefined;
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
      </div>
    </div>
  </div>
</div>