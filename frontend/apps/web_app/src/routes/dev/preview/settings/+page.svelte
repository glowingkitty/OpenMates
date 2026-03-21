<!--
    Settings UI Elements Preview — Storybook-like page showing all 13 canonical
    settings UI elements from the Figma design system.

    Accessible at /dev/preview/settings (dev-only, blocked in production).
    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)

    Sections:
    A. SettingsItem variants (5 types from SettingsItem.svelte)
    B. Settings form elements (7 types from settings/elements/)
    C. Search & sort bar (from SearchSortBar.svelte)
-->
<script lang="ts">
	import SettingsItem from '@repo/ui/components/SettingsItem.svelte';
	import SearchSortBar from '@repo/ui/components/settings/SearchSortBar.svelte';
	import {
		SettingsInput,
		SettingsTextarea,
		SettingsDropdown,
		SettingsFileUpload,
		SettingsConsentToggle,
		SettingsQuote,
		SettingsTabs,
		SettingsInfoBox
	} from '@repo/ui/components/settings/elements';

	// --- State for interactive demos ---
	let inputValue = $state('');
	let textareaValue = $state('');
	let dropdownValue = $state('');
	let consentChecked = $state(false);
	let toggleChecked = $state(false);
	let activeTab = $state('tasks');
	let searchQuery = $state('');
	let sortBy = $state('newest');

	const dropdownOptions = [
		{ value: 'option1', label: 'Google Authenticator' },
		{ value: 'option2', label: 'Authy' },
		{ value: 'option3', label: 'Microsoft Authenticator' }
	];

	// Hardcoded "general_knowledge" category gradient for demo purposes.
	// In real usage, callers inside packages/ui can import getCategoryGradientColors()
	// to compute this dynamically (see SettingsShared.svelte for example).
	const genKnowledgeGradientCss = 'linear-gradient(135deg, #4867cd 9.04%, #5a85eb 90.06%)';

	const demoTabs = [
		{ id: 'tasks', icon: 'projectmanagement', count: 4 },
		{ id: 'files', icon: 'files', count: 3 },
		{ id: 'usage', icon: 'usage' }
	];

	const demoTabsMany = [
		{ id: 'tasks', icon: 'projectmanagement', count: 4 },
		{ id: 'files', icon: 'files', count: 3 },
		{ id: 'usage', icon: 'usage' },
		{ id: 'time', icon: 'time', count: 12 },
		{ id: 'chat', icon: 'chat' }
	];

	let activeTabMany = $state('tasks');

	const sortOptions = [
		{ value: 'newest', label: 'Newest' },
		{ value: 'name_asc', label: 'Name (A-Z)' },
		{ value: 'name_desc', label: 'Name (Z-A)' }
	];

	/** Tab content mapping for the 3-tab demo */
	const tabContent: Record<string, string> = {
		tasks: 'You have 4 open tasks. Complete "Update profile picture" to earn bonus credits.',
		files: 'You have 3 recently uploaded files: report.pdf, photo.jpg, notes.md.',
		usage: 'This month you used 12,450 credits across 23 chats and 4 API calls.'
	};

	/** Tab content for the 5-tab scrollable demo */
	const tabContentMany: Record<string, string> = {
		tasks: 'Active tasks: 4 pending review items.',
		files: 'Recent files: 3 documents uploaded this week.',
		usage: 'Monthly usage: 12,450 / 50,000 credits.',
		time: 'Time tracking: 12 hours logged across 3 projects.',
		chat: 'Chat activity: 23 conversations this month.'
	};

	// Theme toggle
	let isDark = $state(false);

	function toggleTheme() {
		isDark = !isDark;
		document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
	}
</script>

<div class="preview-page" class:dark={isDark}>
	<!-- Header -->
	<header class="preview-header">
		<h1>Settings UI Elements</h1>
		<div class="header-actions">
			<a
				href="https://www.figma.com/design/PzgE78TVxG0eWuEeO6o8ve/Website?node-id=4944-31418"
				target="_blank"
				rel="noopener noreferrer"
				class="figma-link"
			>
				Open in Figma
			</a>
			<button class="theme-toggle" onclick={toggleTheme}>
				{isDark ? 'Light' : 'Dark'} Mode
			</button>
		</div>
	</header>

	<!-- Preview container (mimics settings panel width) -->
	<div class="preview-container">
		<!-- ============================================= -->
		<!-- SECTION A: SettingsItem Variants (existing)   -->
		<!-- ============================================= -->
		<section class="element-section">
			<h2 class="section-title">A. SettingsItem Variants</h2>
			<p class="section-description">
				These 5 element types are all handled by the existing <code>SettingsItem.svelte</code> component.
			</p>

			<!-- 1. Subsettings menu link -->
			<div class="element-block">
				<div class="element-header">
					<h3>1. Subsettings menu link</h3>
					<span class="element-tag existing">SettingsItem type="submenu"</span>
				</div>
				<p class="element-purpose">
					Always used if a click on the item will open another sub settings menu. Icon has OpenMates
					primary gradient, text has gradient color.
				</p>
				<div class="element-demo">
					<SettingsItem type="submenu" icon="chat" title="Chat" onClick={() => {}} />
					<SettingsItem type="submenu" icon="billing" title="Billing & Usage" onClick={() => {}} />
				</div>
			</div>

			<!-- 2. Settings item with toggle -->
			<div class="element-block">
				<div class="element-header">
					<h3>2. Settings item with toggle</h3>
					<span class="element-tag existing">SettingsItem hasToggle=true</span>
				</div>
				<p class="element-purpose">
					Always used if a click on the item will trigger a state change. Toggle element on the
					right side.
				</p>
				<div class="element-demo">
					<SettingsItem
						type="quickaction"
						icon="subsetting_icon incognito"
						title="Incognito"
						hasToggle={true}
						checked={toggleChecked}
						onClick={() => {
							toggleChecked = !toggleChecked;
						}}
					/>
				</div>
			</div>

			<!-- 3. Clickable action -->
			<div class="element-block">
				<div class="element-header">
					<h3>3. Clickable action</h3>
					<span class="element-tag existing">SettingsItem type="quickaction"</span>
				</div>
				<p class="element-purpose">
					Always used if a click on the item will trigger an action (e.g. Logout).
				</p>
				<div class="element-demo">
					<SettingsItem
						type="quickaction"
						icon="subsetting_icon logout"
						title="Logout"
						onClick={() => alert('Logout clicked')}
					/>
				</div>
			</div>

			<!-- 4. Settings item/entry with value -->
			<div class="element-block">
				<div class="element-header">
					<h3>4. Settings item/entry with value</h3>
					<span class="element-tag existing">SettingsItem + subtitle + hasModifyButton</span>
				</div>
				<p class="element-purpose">
					Used when clicking opens a sub settings menu for selecting one of multiple options. Shows
					current value as grey subtitle below the title. Right side: edit button, download button,
					or credits counter with coin icon.
				</p>
				<div class="element-demo">
					<!-- App settings entry: icon colored with app-specific gradient -->
					<SettingsItem
						type="quickaction"
						icon="secrets"
						iconColor="var(--color-app-secrets)"
						title="2FA App"
						subtitleBottom="Google Authenticator"
						hasModifyButton={true}
						onClick={() => {}}
					/>
					<!-- App settings entry: icon SVG colored with app gradient -->
					<SettingsItem
						type="quickaction"
						icon="travel"
						iconColor="var(--color-app-travel)"
						title="London"
						subtitleBottom="Mar 29 – Apr 6"
						hasModifyButton={true}
						onClick={() => {}}
					/>
					<!-- Download entry: icon SVG colored with app gradient, download button on right -->
					<SettingsItem
						type="quickaction"
						icon="legal"
						iconColor="var(--color-app-legal)"
						title="2025-03-13"
						subtitleBottom="10 EUR"
						rightActionIcon="download"
						onClick={() => {}}
					/>
					<!-- Chat entry with credits: category icon in category gradient color -->
					<SettingsItem
						type="submenu"
						icon="chat"
						iconBackground="none"
						iconColor={genKnowledgeGradientCss}
						title="Legality of Ad-skipping Plugins"
						creditsDisplay="120"
						onClick={() => {}}
					/>
				</div>
			</div>

			<!-- 5. Settings subheading -->
			<div class="element-block">
				<div class="element-header">
					<h3>5. Settings subheading</h3>
					<span class="element-tag existing">SettingsItem type="heading"</span>
				</div>
				<p class="element-purpose">
					Non-clickable section separator. Icon has gradient background, text is plain black/grey.
				</p>
				<div class="element-demo">
					<SettingsItem type="heading" icon="chat" title="Chat" />
					<SettingsItem type="heading" icon="privacy" title="Privacy" />
				</div>
			</div>
		</section>

		<!-- ============================================= -->
		<!-- SECTION B: New Form Components                -->
		<!-- ============================================= -->
		<section class="element-section">
			<h2 class="section-title">B. Settings Form Elements</h2>
			<p class="section-description">
				These 7 element types are new shared components in <code>settings/elements/</code>.
			</p>

			<!-- 6. Consent toggle -->
			<div class="element-block">
				<div class="element-header">
					<h3>6. Consent toggle</h3>
					<span class="element-tag new">SettingsConsentToggle</span>
				</div>
				<p class="element-purpose">
					Toggle on LEFT side with consent text. Important parts highlighted with gradient. User
					must toggle to confirm before proceeding.
				</p>
				<div class="element-demo">
					<SettingsConsentToggle
						bind:checked={consentChecked}
						consentText="I accept that the device will have full access to my account (until I revoke the session via the settings menu)."
						highlightedParts={['full access to my account', 'revoke the session']}
					/>
					<div class="state-display">checked: {consentChecked}</div>
				</div>
			</div>

			<!-- 7. Input field - Short text -->
			<div class="element-block">
				<div class="element-header">
					<h3>7. Input field - Short text</h3>
					<span class="element-tag new">SettingsInput</span>
				</div>
				<p class="element-purpose">
					Always used for titles and other short text inputs. Follows after a Settings subheading.
				</p>
				<div class="element-demo">
					<SettingsItem type="heading" icon="app" title="Device" />
					<SettingsInput bind:value={inputValue} placeholder="Enter a device name" />
					<div class="state-display">value: "{inputValue}"</div>
				</div>
				<div class="element-demo">
					<h4 class="variant-label">Disabled variant</h4>
					<SettingsInput
						value="Read-only value"
						placeholder="Enter a device name"
						disabled={true}
					/>
				</div>
			</div>

			<!-- 8. Input field - Multi line text -->
			<div class="element-block">
				<div class="element-header">
					<h3>8. Input field - Multi line text</h3>
					<span class="element-tag new">SettingsTextarea</span>
				</div>
				<p class="element-purpose">
					Always used for multi-line text input fields. Follows after a Settings subheading.
				</p>
				<div class="element-demo">
					<SettingsTextarea bind:value={textareaValue} placeholder="Enter a description." />
					<div class="state-display">length: {textareaValue.length} chars</div>
				</div>
			</div>

			<!-- 9. Input field - Dropdown -->
			<div class="element-block">
				<div class="element-header">
					<h3>9. Input field - Dropdown</h3>
					<span class="element-tag new">SettingsDropdown</span>
				</div>
				<p class="element-purpose">
					Always used for dropdown selections. Follows after a Settings subheading.
				</p>
				<div class="element-demo">
					<SettingsDropdown
						bind:value={dropdownValue}
						placeholder="Select an option"
						options={dropdownOptions}
					/>
					<div class="state-display">selected: "{dropdownValue}"</div>
				</div>
			</div>

			<!-- 10. Input field - File upload -->
			<div class="element-block">
				<div class="element-header">
					<h3>10. Input field - File upload</h3>
					<span class="element-tag new">SettingsFileUpload</span>
				</div>
				<p class="element-purpose">
					Always used for uploading a file. Shows supported file types in label text. Uses files.svg
					icon with OpenMates gradient.
				</p>
				<div class="element-demo">
					<SettingsFileUpload
						accept=".zip,.yaml,.yml"
						label="Select ZIP or YAML file"
						onFileSelected={(file) => alert(`Selected: ${file.name}`)}
					/>
				</div>
			</div>

			<!-- 11. Quoted text -->
			<div class="element-block">
				<div class="element-header">
					<h3>11. Quoted text</h3>
					<span class="element-tag new">SettingsQuote</span>
				</div>
				<p class="element-purpose">
					Always used for quoted text, examples, or prompts. Can be grouped in a horizontal
					scrollable container. Optionally clickable. Text is centered.
				</p>
				<div class="element-demo">
					<div class="quote-scroll-group">
						<SettingsQuote
							text="Can you give me some career advice?"
							onClick={() => alert('Quote clicked - copy to input')}
						/>
						<SettingsQuote
							text="Write a short story about a robot learning to paint."
							onClick={() => alert('Quote clicked - copy to input')}
						/>
						<SettingsQuote text="Help me plan a weekend trip to Berlin." />
					</div>
				</div>
			</div>

			<!-- 12. Tabs -->
			<div class="element-block">
				<div class="element-header">
					<h3>12. Tabs</h3>
					<span class="element-tag new">SettingsTabs</span>
				</div>
				<p class="element-purpose">
					Icon-only tabs with animated sliding gradient pill. 4 or fewer tabs share width equally.
					Inactive icons are grey, active icon is white. Hover shows gradient at 50% opacity.
				</p>
				<div class="element-demo">
					<h4 class="variant-label">3 tabs (equal width, icon-only)</h4>
					<SettingsTabs tabs={demoTabs} bind:activeTab />
					<div class="tab-content-panel">
						{tabContent[activeTab] || ''}
					</div>
					<div class="state-display">active: "{activeTab}"</div>
				</div>
				<div class="element-demo">
					<h4 class="variant-label">5 tabs (scrollable, custom gradient)</h4>
					<SettingsTabs
						tabs={demoTabsMany}
						bind:activeTab={activeTabMany}
						gradientStart="#a84647"
						gradientEnd="#f16e6f"
					/>
					<div class="tab-content-panel">
						{tabContentMany[activeTabMany] || ''}
					</div>
					<div class="state-display">active: "{activeTabMany}"</div>
				</div>
			</div>
		</section>

		<!-- 13. Info Box -->
		<div class="element-block">
			<div class="element-header">
				<h3>13. Info Box</h3>
				<span class="element-tag new">SettingsInfoBox</span>
			</div>
			<p class="element-purpose">
				Reusable message box for info, success, error, and warning states. White pill card
				with colored left accent and type-appropriate icon.
			</p>
			<div class="element-demo">
				<h4 class="variant-label">Info (default)</h4>
				<SettingsInfoBox type="info">This feature requires an internet connection to sync your data.</SettingsInfoBox>
			</div>
			<div class="element-demo">
				<h4 class="variant-label">Success</h4>
				<SettingsInfoBox type="success">Your subscription has been confirmed successfully.</SettingsInfoBox>
			</div>
			<div class="element-demo">
				<h4 class="variant-label">Error</h4>
				<SettingsInfoBox type="error">Something went wrong. Please try again later.</SettingsInfoBox>
			</div>
			<div class="element-demo">
				<h4 class="variant-label">Warning</h4>
				<SettingsInfoBox type="warning">You can cancel your subscription at any time from your account settings.</SettingsInfoBox>
			</div>
		</div>

		<!-- ============================================= -->
		<!-- SECTION C: Search & Sort Bar                  -->
		<!-- ============================================= -->
		<section class="element-section">
			<h2 class="section-title">C. Search & Sort Bar</h2>
			<p class="section-description">
				Search input + sort icon using native OS <code>&lt;select&gt;</code> dropdown. Figma node
				<code>5040-64488</code>.
			</p>

			<div class="element-block">
				<div class="element-header">
					<h3>13. Search & sort</h3>
					<span class="element-tag new">SearchSortBar</span>
				</div>
				<p class="element-purpose">
					Search input (based on short text input with search icon). Sort button: sort.svg icon
					only, on click opens native OS dropdown via hidden &lt;select&gt;.
				</p>
				<div class="element-demo">
					<SearchSortBar bind:searchQuery bind:sortBy searchPlaceholder="Search" {sortOptions} />
					<div class="state-display">search: "{searchQuery}" | sort: "{sortBy}"</div>
				</div>
			</div>
		</section>
	</div>
</div>

<style>
	.preview-page {
		min-height: 100vh;
		background: var(--color-grey-10, #f9f9f9);
		padding: 2rem;
		font-family:
			'Lexend Deca Variable',
			-apple-system,
			BlinkMacSystemFont,
			'Segoe UI',
			Roboto,
			sans-serif;
	}

	.preview-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 2rem;
		max-width: 32rem;
		margin-left: auto;
		margin-right: auto;
	}

	.preview-header h1 {
		font-size: 1.5rem;
		font-weight: 700;
		color: var(--color-grey-100, #000);
		margin: 0;
	}

	.header-actions {
		display: flex;
		gap: 0.75rem;
		align-items: center;
	}

	.figma-link {
		font-size: 0.8125rem;
		font-weight: 600;
		color: var(--color-primary-start, #4867cd);
		text-decoration: none;
	}

	.figma-link:hover {
		text-decoration: underline;
	}

	.theme-toggle {
		padding: 0.375rem 0.75rem;
		border: 0.0625rem solid var(--color-grey-30, #e3e3e3);
		border-radius: 0.5rem;
		background: var(--color-grey-0, #fff);
		color: var(--color-grey-100, #000);
		font-size: 0.8125rem;
		font-weight: 500;
		cursor: pointer;
	}

	.preview-container {
		max-width: 32rem;
		margin: 0 auto;
	}

	.element-section {
		margin-bottom: 3rem;
	}

	.section-title {
		font-size: 1.25rem;
		font-weight: 700;
		color: var(--color-grey-100, #000);
		margin: 0 0 0.5rem;
		padding-bottom: 0.5rem;
		border-bottom: 0.125rem solid var(--color-grey-30, #e3e3e3);
	}

	.section-description {
		font-size: 0.875rem;
		color: var(--color-grey-60, #888);
		margin: 0 0 1.5rem;
	}

	.section-description code {
		background: var(--color-grey-20, #f3f3f3);
		padding: 0.125rem 0.375rem;
		border-radius: 0.25rem;
		font-size: 0.8125rem;
	}

	.element-block {
		margin-bottom: 2rem;
		padding: 1.25rem;
		background: var(--color-grey-20, #f3f3f3);
		border-radius: 0.75rem;
	}

	.element-header {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		margin-bottom: 0.5rem;
		flex-wrap: wrap;
	}

	.element-header h3 {
		font-size: 1rem;
		font-weight: 700;
		color: var(--color-grey-100, #000);
		margin: 0;
	}

	.element-tag {
		font-size: 0.6875rem;
		font-weight: 600;
		padding: 0.125rem 0.5rem;
		border-radius: 1rem;
		white-space: nowrap;
	}

	.element-tag.existing {
		background: var(--color-grey-30, #e3e3e3);
		color: var(--color-grey-70, #666);
	}

	.element-tag.new {
		background: #d4edda;
		color: #155724;
	}

	.element-purpose {
		font-size: 0.8125rem;
		color: var(--color-grey-60, #888);
		margin: 0 0 1rem;
		line-height: 1.4;
	}

	.element-demo {
		background: var(--color-grey-20, #f3f3f3);
		border-radius: 0.5rem;
		padding: 0.5rem 0;
	}

	.element-demo + .element-demo {
		margin-top: 1rem;
		padding-top: 1rem;
		border-top: 0.0625rem solid var(--color-grey-30, #e3e3e3);
	}

	.variant-label {
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--color-grey-60, #888);
		margin: 0 0 0.5rem 0.625rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.state-display {
		font-size: 0.75rem;
		font-family: 'SF Mono', 'Monaco', 'Inconsolata', monospace;
		color: var(--color-grey-50, #a6a6a6);
		padding: 0.5rem 0.625rem 0;
	}

	.quote-scroll-group {
		display: flex;
		gap: 0.75rem;
		overflow-x: auto;
		padding: 0.5rem 0.625rem;
		-webkit-overflow-scrolling: touch;
		scrollbar-width: none;
	}

	.quote-scroll-group::-webkit-scrollbar {
		display: none;
	}

	/* Ensure quotes don't shrink in scroll container */
	.quote-scroll-group :global(.settings-quote) {
		flex-shrink: 0;
		width: 14rem;
	}

	/* Tab content panel — overlaps bottom half of tabs for visual connection */
	.tab-content-panel {
		background: var(--color-grey-10, #f9f9f9);
		border-radius: 0.75rem;
		margin-top: -1.4rem;
		padding: 2.4rem 0.625rem 0.5rem;
		font-size: 0.875rem;
		color: var(--color-grey-70, #666);
		line-height: 1.4;
	}
</style>
