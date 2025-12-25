<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiEndpoint, apiEndpoints } from '../../config/api';
    import Avatar from '../common/Avatar.svelte';
    
    // Props using Svelte 5 runes
    let { 
        username = '',
        is_admin = false,
        avatarUrl = ''
    }: {
        username?: string;
        is_admin?: boolean;
        avatarUrl?: string;
    } = $props();
    let isLoggingOut = false;
    let showUserMenu = false;

    onMount(() => {
        // Get the username from localStorage if not provided
        if (!username) {
            username = localStorage.getItem('user_display_name') || '';
        }
        
        // Close the menu when clicking outside
        function handleClickOutside(event: MouseEvent) {
            if (showUserMenu) {
                const target = event.target as HTMLElement;
                const userMenu = document.querySelector('.user-menu');
                const avatarContainer = document.querySelector('.avatar-container');
                
                if (userMenu && 
                    avatarContainer && 
                    !userMenu.contains(target) && 
                    !avatarContainer.contains(target)) {
                    showUserMenu = false;
                }
            }
        }
        
        document.addEventListener('click', handleClickOutside);
        
        return () => {
            document.removeEventListener('click', handleClickOutside);
        };
    });
    
    function toggleUserMenu() {
        showUserMenu = !showUserMenu;
    }
    
    async function logout() {
        try {
            isLoggingOut = true;
            
            // Call the logout endpoint
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.logout), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                credentials: 'include'
            });
            
            if (response.ok) {
                // Clear local storage
                localStorage.removeItem('user_display_name');
                
                // Redirect to login page
                window.location.href = '/login';
            } else {
                console.error('Error logging out:', response.statusText);
            }
        } catch (error) {
            console.error('Error logging out:', error);
        } finally {
            isLoggingOut = false;
        }
    }
    
    async function logoutAll() {
        try {
            isLoggingOut = true;
            
            // Call the logout all endpoint
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.logoutAll), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                credentials: 'include'
            });
            
            if (response.ok) {
                // Clear local storage
                localStorage.removeItem('user_display_name');
                
                // Redirect to login page
                window.location.href = '/login';
            } else {
                console.error('Error logging out all sessions:', response.statusText);
            }
        } catch (error) {
            console.error('Error logging out all sessions:', error);
        } finally {
            isLoggingOut = false;
        }
    }
</script>

<nav class="navbar">
    <div class="navbar-left">
        <a href="/" class="logo">
            <img src="/logo.svg" alt="Logo" />
        </a>
    </div>
    
    <div class="navbar-right">
        {#if username}
            <div class="avatar-container" onclick={toggleUserMenu}>
                <Avatar username={username} imageUrl={avatarUrl} size="small" />
                <span class="username">{username}</span>
                <div class="clickable-icon icon_chevron_down"></div>
            </div>
            
            {#if showUserMenu}
                <div class="user-menu" transition:slide={{ duration: 150 }}>
                    <div class="menu-header">
                        <Avatar username={username} imageUrl={avatarUrl} size="medium" />
                        <div class="user-info">
                            <div class="menu-username">{username}</div>
                            {#if is_admin}
                                <div class="admin-badge">{$text('common.admin.text')}</div>
                            {/if}
                        </div>
                    </div>
                    
                    <div class="menu-items">
                        <a href="/settings/profile" class="menu-item">
                            <div class="clickable-icon icon_settings"></div>
                            <span>{$text('settings.settings.text')}</span>
                        </a>
                        
                        <button class="menu-item" onclick={logout} disabled={isLoggingOut}>
                            <div class="clickable-icon icon_logout"></div>
                            <span>{$text('settings.logout.text')}</span>
                        </button>
                        
                        <button class="menu-item" onclick={logoutAll} disabled={isLoggingOut}>
                            <div class="clickable-icon icon_logout_all"></div>
                            <span>{$text('settings.logout_all.text')}</span>
                        </button>
                    </div>
                </div>
            {/if}
        {:else}
            <a href="/login" class="login-button">
                {$text('login.login_button.text')}
            </a>
            <a href="/signup" class="signup-button">
                {$text('signup.sign_up.text')}
            </a>
        {/if}
    </div>
</nav>

<style>
    .navbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0 24px;
        height: 64px;
        background-color: var(--color-background);
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        position: relative;
        z-index: 100;
    }
    
    .navbar-left, .navbar-right {
        display: flex;
        align-items: center;
    }
    
    .logo img {
        height: 32px;
    }
    
    .avatar-container {
        display: flex;
        align-items: center;
        cursor: pointer;
        padding: 6px 12px;
        border-radius: 20px;
        transition: background-color 0.2s;
    }
    
    .avatar-container:hover {
        background-color: var(--color-hover-background);
    }
    
    .username {
        margin: 0 8px;
        font-size: 14px;
        font-weight: 500;
    }
    
    .user-menu {
        position: absolute;
        top: 60px;
        right: 24px;
        width: 240px;
        background-color: var(--color-background);
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        overflow: hidden;
        z-index: 200;
    }
    
    .menu-header {
        display: flex;
        align-items: center;
        padding: 16px;
        border-bottom: 1px solid var(--color-border);
    }
    
    .user-info {
        margin-left: 12px;
    }
    
    .menu-username {
        font-weight: 500;
        margin-bottom: 4px;
    }
    
    .admin-badge {
        font-size: 12px;
        background-color: var(--color-primary);
        color: white;
        padding: 2px 6px;
        border-radius: 4px;
        display: inline-block;
    }
    
    .menu-items {
        padding: 8px 0;
    }
    
    .menu-item {
        display: flex;
        align-items: center;
        padding: 8px 16px;
        color: var(--color-text);
        text-decoration: none;
        transition: background-color 0.2s;
        cursor: pointer;
        border: none;
        background: none;
        width: 100%;
        text-align: left;
        font-size: 14px;
    }
    
    .menu-item:hover {
        background-color: var(--color-hover-background);
    }
    
    .menu-item span {
        margin-left: 12px;
    }
    
    .login-button, .signup-button {
        padding: 8px 16px;
        border-radius: 4px;
        font-size: 14px;
        font-weight: 500;
        text-decoration: none;
        margin-left: 8px;
    }
    
    .login-button {
        color: var(--color-text);
    }
    
    .signup-button {
        background-color: var(--color-primary);
        color: white;
    }
</style>
