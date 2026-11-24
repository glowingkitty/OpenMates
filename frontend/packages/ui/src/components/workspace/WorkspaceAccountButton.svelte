<script lang="ts">
  import { openGuestAccountEntry } from '../../utils/guestAccountEntry';

  let {
    label, testId, class: className = '', onPress = openGuestAccountEntry,
  }: { label: string; testId: string; class?: string; onPress?: () => void } = $props();
</script>

<button
  type="button"
  onclick={onPress}
  class={['login-signup-button', className]}
  data-testid={testId}
  data-workspace-control="account"
  aria-label={label}
>
  {label}
</button>

<style>
  .login-signup-button {
    border: none;
    margin: 0;
    min-width: 0;
    padding: var(--spacing-4) var(--spacing-6);
    border-radius: var(--radius-3);
    background: var(--color-button-primary);
    color: var(--color-font-button, white);
    cursor: pointer;
    max-width: 240px;
    overflow: hidden;
    transition: all var(--duration-normal) var(--easing-default);
    white-space: nowrap;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  }

  .login-signup-button:hover {
    transform: scale(1.05);
    filter: brightness(1.12);
  }

  .login-signup-button:active {
    background-color: var(--color-button-primary-pressed);
    transform: scale(0.98);
    box-shadow: none;
  }
</style>
