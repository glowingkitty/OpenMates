<script>
    // Props for user and team information
    export let userProfilePicture = '';  // URL of user's profile picture
    export let teamProfilePicture = '';  // URL of team's profile picture (optional)
</script>

<div class="profile-container">
    <div 
        class="profile-picture"
        style="background-image: url('{userProfilePicture}');"
    ></div>
    
    {#if teamProfilePicture}
        <div 
            class="team-picture"
            style="background-image: url('{teamProfilePicture}');"
        ></div>
    {/if}
</div>

<style>
    .profile-container {
        display: inline-block;
        width: 57px;
        height: 57px;
        background-color: #ffffff;
        border-radius: 50%;
        margin: 0;
    }

    .profile-picture {
        border-radius: 50%;
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }

    .team-picture {
        position: absolute;
        bottom: -2px;
        left: -2px;
        width: 30px;
        height: 30px;
        border-radius: 50%;
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
        background-color: #c6c6c6;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }
</style>
