<!--
    Settings Server Statistics Component

    Displays global server statistics for admins.
    Shows daily stats for last 30 days and monthly stats for last 12 months.
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import { getApiEndpoint, text } from '@repo/ui';
    import { fade } from 'svelte/transition';

    interface StatsRecord {
        id: string;
        date?: string;
        year_month?: string;
        new_users_registered: number;
        new_users_finished_signup: number;
        income_eur_cents: number;
        credits_sold: number;
        credits_used: number;
        messages_sent: number;
        chats_created: number;
        embeds_created?: number;
        liability_total: number;
        active_subscriptions: number;
        total_regular_users: number;
        created_at: string;
        updated_at: string;
    }

    // State
    let isLoading = $state(true);
    let error = $state<string | null>(null);
    let dailyHistory = $state<StatsRecord[]>([]);
    let monthlyHistory = $state<StatsRecord[]>([]);
    let currentStats = $state<Partial<StatsRecord>>({});

    /**
     * Load server statistics from server
     */
    async function loadStats() {
        try {
            isLoading = true;
            error = null;

            const response = await fetch(getApiEndpoint('/v1/admin/server-stats'), {
                credentials: 'include'
            });

            if (!response.ok) {
                if (response.status === 403) {
                    error = 'Admin privileges required to view server statistics.';
                } else {
                    error = 'Failed to load server statistics.';
                }
                return;
            }

            const data = await response.json();
            currentStats = data.current || {};
            dailyHistory = data.daily_history || [];
            monthlyHistory = data.monthly_history || [];

        } catch (err) {
            console.error('Error loading stats:', err);
            error = 'Failed to connect to server.';
        } finally {
            isLoading = false;
        }
    }

    /**
     * Format currency (cents to EUR)
     */
    function formatCurrency(cents: number = 0): string {
        return (cents / 100).toLocaleString('en-US', {
            style: 'currency',
            currency: 'EUR'
        });
    }

    /**
     * Format date for display
     */
    function formatDate(dateStr: string): string {
        if (!dateStr) return '';
        try {
            const date = new Date(dateStr);
            return date.toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric'
            });
        } catch {
            return dateStr;
        }
    }

    /**
     * Format month for display
     */
    function formatMonth(monthStr: string): string {
        if (!monthStr) return '';
        try {
            const [year, month] = monthStr.split('-');
            const date = new Date(parseInt(year), parseInt(month) - 1);
            return date.toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'long'
            });
        } catch {
            return monthStr;
        }
    }

    onMount(() => {
        loadStats();
    });
</script>

<div class="server-stats" in:fade={{ duration: 300 }}>
    <div class="header">
        <h2>{$text('settings.server_stats.title.text')}</h2>
        <p>{$text('settings.server_stats.description.text')}</p>
    </div>

    {#if isLoading}
        <div class="loading">
            <div class="spinner"></div>
            <p>{$text('settings.server_stats.loading.text')}</p>
        </div>
    {:else if error}
        <div class="error">
            <div class="error-icon">⚠️</div>
            <p>{error}</p>
            <button onclick={loadStats} class="btn btn-primary">{$text('settings.server_stats.try_again.text')}</button>
        </div>
    {:else}
        <!-- Current Snapshots -->
        <div class="stats-grid">
            <div class="stat-card">
                <span class="stat-label">{$text('settings.server_stats.total_users.text')}</span>
                <span class="stat-value">{currentStats.total_regular_users || 0}</span>
                <span class="stat-sublabel">{$text('settings.server_stats.total_users_sub.text')}</span>
            </div>
            <div class="stat-card">
                <span class="stat-label">{$text('settings.server_stats.active_subscriptions.text')}</span>
                <span class="stat-value">{currentStats.active_subscriptions || 0}</span>
                <span class="stat-sublabel">{$text('settings.server_stats.active_subscriptions_sub.text')}</span>
            </div>
            <div class="stat-card">
                <span class="stat-label">{$text('settings.server_stats.total_liability.text')}</span>
                <span class="stat-value">{formatCurrency(currentStats.liability_total)}</span>
                <span class="stat-sublabel">{$text('settings.server_stats.total_liability_sub.text')}</span>
            </div>
        </div>

        <!-- Latest Day Activity -->
        <div class="section">
            <h3>{$text('settings.server_stats.latest_activity.text', { date: currentStats.date || 'N/A' })}</h3>
            <div class="activity-grid">
                <div class="activity-item">
                    <span class="label">{$text('settings.server_stats.new_registrations.text')}</span>
                    <span class="value">{currentStats.new_users_registered || 0}</span>
                </div>
                <div class="activity-item">
                    <span class="label">{$text('settings.server_stats.finished_signup.text')}</span>
                    <span class="value">{currentStats.new_users_finished_signup || 0}</span>
                </div>
                <div class="activity-item">
                    <span class="label">{$text('settings.server_stats.income.text')}</span>
                    <span class="value">{formatCurrency(currentStats.income_eur_cents)}</span>
                </div>
                <div class="activity-item">
                    <span class="label">{$text('settings.server_stats.credits_sold.text')}</span>
                    <span class="value">{currentStats.credits_sold || 0}</span>
                </div>
                <div class="activity-item">
                    <span class="label">{$text('settings.server_stats.credits_used.text')}</span>
                    <span class="value">{currentStats.credits_used || 0}</span>
                </div>
                <div class="activity-item">
                    <span class="label">{$text('settings.server_stats.messages_sent.text')}</span>
                    <span class="value">{currentStats.messages_sent || 0}</span>
                </div>
                <div class="activity-item">
                    <span class="label">{$text('settings.server_stats.chats_created.text')}</span>
                    <span class="value">{currentStats.chats_created || 0}</span>
                </div>
            </div>
        </div>

        <!-- History Tables -->
        <div class="section">
            <div class="tabs">
                <button class="tab-btn active">{$text('settings.server_stats.daily_history.text')}</button>
            </div>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>{$text('settings.server_stats.date.text')}</th>
                            <th>{$text('settings.server_stats.new_users.text')}</th>
                            <th>{$text('settings.server_stats.signup_fin.text')}</th>
                            <th>{$text('settings.server_stats.income.text')}</th>
                            <th>{$text('settings.server_stats.credits_sold.text')}</th>
                            <th>{$text('settings.server_stats.credits_used.text')}</th>
                            <th>{$text('settings.server_stats.messages.text')}</th>
                            <th>{$text('settings.server_stats.chats.text')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {#each dailyHistory as day}
                            <tr>
                                <td>{formatDate(day.date || '')}</td>
                                <td>{day.new_users_registered}</td>
                                <td>{day.new_users_finished_signup}</td>
                                <td>{formatCurrency(day.income_eur_cents)}</td>
                                <td>{day.credits_sold}</td>
                                <td>{day.credits_used}</td>
                                <td>{day.messages_sent}</td>
                                <td>{day.chats_created}</td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
            </div>
        </div>

        <div class="section">
            <div class="tabs">
                <button class="tab-btn active">{$text('settings.server_stats.monthly_history.text')}</button>
            </div>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>{$text('settings.server_stats.month.text')}</th>
                            <th>{$text('settings.server_stats.new_users.text')}</th>
                            <th>{$text('settings.server_stats.signup_fin.text')}</th>
                            <th>{$text('settings.server_stats.income.text')}</th>
                            <th>{$text('settings.server_stats.credits_sold.text')}</th>
                            <th>{$text('settings.server_stats.credits_used.text')}</th>
                            <th>{$text('settings.server_stats.messages.text')}</th>
                            <th>{$text('settings.server_stats.chats.text')}</th>
                            <th>{$text('settings.server_stats.embeds.text')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {#each monthlyHistory as month}
                            <tr>
                                <td>{formatMonth(month.year_month || '')}</td>
                                <td>{month.new_users_registered}</td>
                                <td>{month.new_users_finished_signup}</td>
                                <td>{formatCurrency(month.income_eur_cents)}</td>
                                <td>{month.credits_sold}</td>
                                <td>{month.credits_used}</td>
                                <td>{month.messages_sent}</td>
                                <td>{month.chats_created}</td>
                                <td>{month.embeds_created || 0}</td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
            </div>
        </div>
    {/if}
</div>

<style>
    .server-stats {
        padding: 1.5rem;
        max-width: 1200px;
        margin: 0 auto;
    }

    .header {
        margin-bottom: 2rem;
        padding-bottom: 1rem;
        border-bottom: 1px solid var(--color-border);
    }

    .header h2 {
        margin: 0;
        color: var(--color-text-primary);
    }

    .header p {
        margin: 0.5rem 0 0;
        color: var(--color-text-secondary);
    }

    .stats-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
        gap: 1.5rem;
        margin-bottom: 2.5rem;
    }

    .stat-card {
        background: var(--color-background-secondary);
        border: 1px solid var(--color-border);
        border-radius: 12px;
        padding: 1.5rem;
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }

    .stat-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    }

    .stat-label {
        font-size: 0.9rem;
        color: var(--color-text-secondary);
        margin-bottom: 0.5rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    .stat-value {
        font-size: 2rem;
        font-weight: 700;
        color: var(--color-primary);
        margin-bottom: 0.25rem;
    }

    .stat-sublabel {
        font-size: 0.8rem;
        color: var(--color-text-tertiary);
    }

    .section {
        margin-bottom: 3rem;
    }

    .section h3 {
        margin: 0 0 1.5rem;
        font-size: 1.25rem;
        color: var(--color-text-primary);
        border-left: 4px solid var(--color-primary);
        padding-left: 1rem;
    }

    .activity-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
        gap: 1rem;
        background: var(--color-background-tertiary);
        padding: 1.5rem;
        border-radius: 12px;
        border: 1px solid var(--color-border);
    }

    .activity-item {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
    }

    .activity-item .label {
        font-size: 0.85rem;
        color: var(--color-text-secondary);
    }

    .activity-item .value {
        font-size: 1.1rem;
        font-weight: 600;
        color: var(--color-text-primary);
    }

    .table-container {
        width: 100%;
        overflow-x: auto;
        background: var(--color-background-secondary);
        border: 1px solid var(--color-border);
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
    }

    table {
        width: 100%;
        border-collapse: collapse;
        text-align: left;
        font-size: 0.9rem;
    }

    th {
        background: var(--color-background-tertiary);
        padding: 1rem;
        font-weight: 600;
        color: var(--color-text-primary);
        border-bottom: 2px solid var(--color-border);
        white-space: nowrap;
    }

    td {
        padding: 1rem;
        color: var(--color-text-secondary);
        border-bottom: 1px solid var(--color-border);
        white-space: nowrap;
    }

    tr:last-child td {
        border-bottom: none;
    }

    tr:hover td {
        background: var(--color-background-tertiary);
        color: var(--color-text-primary);
    }

    .tabs {
        margin-bottom: 1rem;
        display: flex;
        gap: 1rem;
    }

    .tab-btn {
        background: none;
        border: none;
        padding: 0.5rem 1rem;
        font-size: 1rem;
        font-weight: 600;
        color: var(--color-text-secondary);
        cursor: pointer;
        border-bottom: 2px solid transparent;
        transition: all 0.2s ease;
    }

    .tab-btn.active {
        color: var(--color-primary);
        border-bottom: 2px solid var(--color-primary);
    }

    .loading, .error {
        text-align: center;
        padding: 3rem;
    }

    .spinner {
        width: 3rem;
        height: 3rem;
        border: 4px solid var(--color-border);
        border-top: 4px solid var(--color-primary);
        border-radius: 50%;
        animation: spin 1s linear infinite;
        margin: 0 auto 1rem;
    }

    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }

    .btn {
        padding: 0.6rem 1.2rem;
        border-radius: 8px;
        font-weight: 600;
        cursor: pointer;
        border: none;
        transition: all 0.2s ease;
    }

    .btn-primary {
        background: var(--color-primary);
        color: white;
    }

    .btn-primary:hover {
        background: var(--color-primary-dark);
        transform: translateY(-1px);
    }

    @media (max-width: 768px) {
        .server-stats {
            padding: 1rem;
        }
        
        .stats-grid {
            grid-template-columns: 1fr;
        }
        
        .activity-grid {
            grid-template-columns: 1fr 1fr;
        }
    }
</style>
