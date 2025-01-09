<button 
    class="clickable-icon icon_search top-button left" 
    aria-label="Search"
></button>
<button 
    class="clickable-icon icon_filter top-button center" 
    aria-label="Filter"
></button>
<button 
    class="clickable-icon icon_close top-button right" 
    aria-label="Close"
></button>

<style>
    /* Position buttons in the top bar */
    .top-button {
        position: absolute;
        top: 20px;
    }

    .top-button.left {
        left: 20px;
    }

    .top-button.center {
        left: 50%;
        transform: translateX(-50%); /* Center the button horizontally */
    }

    .top-button.right {
        right: 20px;
    }
</style>