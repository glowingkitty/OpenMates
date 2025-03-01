<script lang="ts">
  import { onMount } from 'svelte';
  // -------------------------------------------------------------------
  // Import the UI components used by the hero header
  // -------------------------------------------------------------------
  import { Icon, AnimatedChatExamples, WaitingList, AppIconGrid } from '@repo/ui';
  import { text } from '@repo/ui';

  // Local reactive variable to store the current app state
  let currentApp = '';

  // Define icon grids based on the original layout
  const leftIconGrid = [
    ['videos', 'health', 'web'],
    ['calendar', 'nutrition', 'language'],
    ['plants', 'fitness', 'shipping'],
    ['shopping', 'jobs', 'books'],
    ['study', 'home', 'tv'],
    ['weather', 'events', 'legal'],
    ['travel', 'photos', 'maps']
  ];
  const rightIconGrid = [
    ['finance', 'business', 'files'],
    ['code', 'pcbdesign', 'audio'],
    ['mail', 'socialmedia', 'messages'],
    ['hosting', 'diagrams', 'news'],
    ['notes', 'whiteboards', 'projectmanagement'],
    ['design', 'publishing', 'pdfeditor'],
    ['slides', 'sheets', 'docs']
  ];


  // Helper function to capitalize the first letter of a string
  function capitalize(str: string): string {
    return str.charAt(0).toUpperCase() + str.slice(1);
  }

  // Log when the component mounts for debugging purposes
  onMount(() => {
      console.log("HeroHeader component mounted");
  });
</script>

<!-- -------------------------------------------------------------------
     Hero header section markup moved from the page.
     It includes the icon grid, title (with conditional icon),
     platform information, and the chat demo.
----------------------------------------------------------------------- -->
<section class="hero-header">
  <!-- Left icon grid for visual decoration -->
  <AppIconGrid iconGrid={leftIconGrid} shifted="columns"/>

  <!-- Center area containing headings, platform details, and chat example -->
  <div class="center-space">
    <div class="center-content">
      <h1 class="text-center">
        {#if currentApp}
          <span class="app-title">
            <!-- The visually hidden text helps with copy selection -->
            <span class="visually-hidden">{capitalize(currentApp)} </span>
            <Icon name={currentApp} type="app" size="67.98px" />
            {$text('team_mates.text')}
          </span>
        {:else}
          {$text('digital_team_mates.text')}
        {/if}
        <mark><br>{@html $text('for_all_of_us.text')}</mark>
      </h1>
      <p class="text-center platform-text">
        {$text('platforms.via.text')}
        <span class="platform-wrapper">
          <span class="visually-hidden">{@html $text('platforms.web.text')}, </span>
          <span class="small-icon icon_web"></span>
        </span>
        <span class="platform-wrapper">
          <span class="visually-hidden">{@html $text('platforms.mattermost.text')}, </span>
          <span class="small-icon icon_mattermost"></span>
        </span>
        <span class="platform-wrapper">
          <span class="visually-hidden">{@html $text('platforms.discord.text')}</span>
          <span class="small-icon icon_discord"></span>
        </span>
        {$text('platforms.and_more.text')}
      </p>
      <div class="chat-container header">
        <!-- Bind the local variable "currentApp" to update on chat events -->
        <AnimatedChatExamples bind:currentApp={currentApp} />
      </div>
      <!-- Display the waiting list component -->
      <WaitingList/>
    </div>
  </div>

  <!-- Right icon grid for visual decoration -->
  <AppIconGrid iconGrid={rightIconGrid} shifted="columns" />
</section>

<style>
  /* -------------------------------------------------------------------
     Main container styles for the hero header - Updated for better mobile support
  ----------------------------------------------------------------------- */
  .hero-header {
      background-color: var(--color-grey-20);
      width: 100%;
      padding: 2rem 0;
      display: flex;
      justify-content: center;
      align-items: center;
      overflow: hidden;
      position: relative;
      -webkit-mask-image: linear-gradient(to bottom, black, black 85%, transparent);
      mask-image: linear-gradient(to bottom, black, black 85%, transparent);
      /* Remove fixed vh height and use min-height instead */
      min-height: min(90vh, 845px);
  }

  /* -------------------------------------------------------------------
     Styles for centering and spacing the content
  ----------------------------------------------------------------------- */
  .center-space {
      display: flex;
      align-items: flex-start;
      justify-content: center;
      padding-top: 2rem;
      margin-bottom: 80px;
  }

  .center-content {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0.75rem;
      width: 100%;
      max-width: 1200px;
      margin: 0 auto;
  }

  .center-content h1,
  .center-content p {
      margin: 0;
  }

  /* -------------------------------------------------------------------
     Styling for the app title and icon
  ----------------------------------------------------------------------- */
  .app-title {
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      position: relative;
      vertical-align: middle;
      margin: 0;
      padding: 0;
  }

  /* Ensure the icon within the title is aligned properly */
  .app-title :global(.icon) {
      display: inline-flex;
      align-items: center;
      margin: 0;
      padding: 0;
      vertical-align: middle;
  }

  /* -------------------------------------------------------------------
     Styles for hidden text, used for accessibility and proper selection
  ----------------------------------------------------------------------- */
  .visually-hidden {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
  }

  /* -------------------------------------------------------------------
     Platform information text styling
  ----------------------------------------------------------------------- */
  .platform-text {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-size: 1.1rem;
      color: #8A8A8A;
      margin-bottom: -0.5rem;
  }

  .platform-wrapper {
      display: inline-flex;
      align-items: center;
      position: relative;
  }

  /* -------------------------------------------------------------------
     Chat container styling and fade effect at the bottom
  ----------------------------------------------------------------------- */
  .chat-container {
      position: relative;
      height: 400px;
      width: 100%;
      max-width: 800px;
      overflow: hidden;
      margin: 20px 0;
  }

  .chat-container.header {
      height: 280px;
      /* Apply a fading mask effect to the bottom of the chat container */
      -webkit-mask-image: linear-gradient(to bottom, black, black calc(100% - 40px), transparent);
      mask-image: linear-gradient(to bottom, black, black calc(100% - 40px), transparent);
  }

  /* -------------------------------------------------------------------
     Responsive adjustments for mobile devices - Updated
  ----------------------------------------------------------------------- */
  @media (max-width: 767px) {
      .hero-header {
          position: relative;
          /* Adjust padding to ensure content is visible */
          padding-top: 4rem;
          /* Set a smaller minimum height for mobile */
          min-height: min(100dvh, 700px);
      }

      .center-space {
          /* Ensure content starts from the top on mobile */
          padding-top: 0;
      }

      .chat-container.header {
          /* Adjust height for better mobile display */
          height: 250px;
      }
  }

  @media (max-width: 600px) {
      .hero-header {
          padding-top: 3rem;
          /* Further reduce minimum height for very small screens */
          min-height: min(100dvh, 600px);
      }
  }

  /* -------------------------------------------------------------------
     Dark mode: adjust icon styling
  ----------------------------------------------------------------------- */
  :global([data-theme="dark"]) .small-icon.icon_web {
      filter: invert(0.6);
  }
</style> 