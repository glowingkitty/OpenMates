<script lang="ts">
  interface Props {
    label: string;
    homeHref: string;
    primaryCtaLabel: string;
    sidebarOpen: boolean;
    onToggleSidebar: () => void;
    onPrimaryCta: () => void;
  }

  let {
    label,
    homeHref,
    primaryCtaLabel,
    sidebarOpen,
    onToggleSidebar,
    onPrimaryCta,
  }: Props = $props();
</script>

<!-- Uses the web-app header's visual primitives without loading its chat/workspace client graph. -->
<header class="publication-header">
  <nav aria-label={label}>
    <div class="left-section">
      <button
        class="sidebar-toggle clickable-icon"
        class:icon_menu={!sidebarOpen}
        class:icon_close={sidebarOpen}
        data-testid="sidebar-toggle"
        type="button"
        onclick={onToggleSidebar}
        aria-label={sidebarOpen ? `Close ${label} navigation` : `Open ${label} navigation`}
        aria-expanded={sidebarOpen}
      ></button>

      <a class="logo-link" href={homeHref} aria-label={`${label} home`}>
        <strong><mark>Open</mark><span>Mates</span></strong>
        <span class="mobile-logo-icon" aria-hidden="true"></span>
        <small>{label}</small>
      </a>
    </div>

    <button
      class="primary-cta"
      data-testid="header-login-signup-btn"
      type="button"
      onclick={onPrimaryCta}
    >
      {primaryCtaLabel}
    </button>
  </nav>
</header>

<style>
  .publication-header {
    position: relative;
    z-index: 2;
    box-sizing: border-box;
    width: 100%;
    height: 4rem;
    min-height: 4rem;
    padding: var(--spacing-6) var(--spacing-10);
    background: var(--color-grey-0);
  }

  nav {
    display: flex;
    width: 100%;
    height: 100%;
    align-items: center;
    justify-content: space-between;
    gap: var(--spacing-8);
  }

  .left-section {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 1rem;
  }

  .sidebar-toggle {
    display: block;
    width: 25px;
    height: 25px;
    flex: 0 0 25px;
    cursor: pointer;
    background-color: var(--color-primary-start);
  }

  .sidebar-toggle:focus-visible,
  .primary-cta:focus-visible,
  .logo-link:focus-visible {
    outline: 0.125rem solid var(--color-primary-start);
    outline-offset: 0.1875rem;
  }

  .logo-link {
    position: relative;
    display: flex;
    min-width: 0;
    align-items: center;
    color: inherit;
    font-size: 1.25rem;
    font-weight: 600;
    text-decoration: none;
  }

  .logo-link strong {
    display: flex;
    gap: 0.25rem;
  }

  .logo-link mark {
    padding: 0 0.2rem;
    background-color: var(--color-primary);
    color: var(--color-grey-20);
  }

  .logo-link span {
    color: var(--color-grey-100);
  }

  .logo-link small {
    position: absolute;
    top: 1.5rem;
    left: 4px;
    color: var(--color-grey-100);
    font-size: 0.75rem;
    font-weight: 400;
    line-height: 1.2;
    white-space: nowrap;
  }

  .mobile-logo-icon {
    display: none;
    width: 30px;
    height: 30px;
    flex: 0 0 30px;
    border-radius: var(--radius-4, 8px);
    background: url("@openmates/ui/static/icons/openmates.svg") center / contain no-repeat;
  }

  .primary-cta {
    flex: 0 0 auto;
    max-width: min(15rem, 45vw);
    overflow: hidden;
    padding: var(--spacing-4) var(--spacing-6);
    border: 0;
    border-radius: var(--radius-3);
    background: var(--color-button-primary);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
    color: var(--color-font-button, white);
    cursor: pointer;
    font: inherit;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .primary-cta:hover {
    transform: scale(1.02);
  }

  .primary-cta:active {
    background-color: var(--color-button-primary-pressed);
    box-shadow: none;
    transform: scale(0.98);
  }

  @media (max-width: 730px) {
    .publication-header {
      padding-inline: var(--spacing-8);
    }

    .left-section {
      gap: calc(0.5rem + 10px);
    }

    .logo-link strong,
    .logo-link small {
      display: none;
    }

    .mobile-logo-icon {
      display: block;
    }

    .primary-cta {
      margin-left: auto;
      padding: var(--spacing-4) var(--spacing-5);
      font-size: var(--font-size-small);
    }
  }
</style>
