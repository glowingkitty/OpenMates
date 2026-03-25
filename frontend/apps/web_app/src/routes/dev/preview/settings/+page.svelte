<!--
    Settings UI Elements Preview — Storybook-like page showing all 29 canonical
    settings UI elements from the Figma design system.

    Accessible at /dev/preview/settings (dev-only, blocked in production).
    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)

    Sections:
    A. SettingsItem variants (5 types from SettingsItem.svelte)
    B. Settings form elements (8 types from settings/elements/)
    C. Search & sort bar (from SearchSortBar.svelte)
    D. Action buttons (SettingsButton, SettingsButtonGroup)
    E. Feedback & status (SettingsProgressBar, SettingsLoadingState, SettingsBadge)
    F. Data display (SettingsCard, SettingsDetailRow, SettingsBalanceDisplay, SettingsCodeBlock)
    G. Confirmation & navigation (SettingsConfirmBlock, SettingsPageHeader, SettingsAvatar, SettingsCheckboxList)
    H. Layout primitives (SettingsDivider, SettingsGradientLink, SettingsPageContainer)
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
		SettingsInfoBox,
		SettingsButton,
		SettingsButtonGroup,
		SettingsProgressBar,
		SettingsLoadingState,
		SettingsBadge,
		SettingsCard,
		SettingsDetailRow,
		SettingsBalanceDisplay,
		SettingsCodeBlock,
		SettingsConfirmBlock,
		SettingsPageHeader,
		SettingsAvatar,
		SettingsCheckboxList,
		SettingsDivider,
		SettingsGradientLink,
		SettingsPageContainer
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

	// --- State for Section D–H demos ---
	let confirmDangerChecked = $state(false);
	let checkboxOptions = $state([
		{ id: 'chats', label: 'Chat History', description: '23 conversations', icon: 'chat', checked: true },
		{ id: 'files', label: 'Uploaded Files', description: '12 files, 45 MB', icon: 'files', checked: true },
		{ id: 'settings', label: 'Account Settings', description: 'Preferences and configuration', icon: 'settings', checked: false }
	]);

	const demoRecoveryCodes = `A1B2-C3D4-E5F6
G7H8-I9J0-K1L2
M3N4-O5P6-Q7R8
S9T0-U1V2-W3X4
Y5Z6-A7B8-C9D0`;

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

		<!-- ============================================= -->
		<!-- SECTION D: Action Buttons                     -->
		<!-- ============================================= -->
		<section class="element-section">
			<h2 class="section-title">D. Action Buttons</h2>
			<p class="section-description">
				Button and button-group components from <code>settings/elements/</code>.
			</p>

			<!-- 14. SettingsButton -->
			<div class="element-block">
				<div class="element-header">
					<h3>14. Button</h3>
					<span class="element-tag new">SettingsButton</span>
				</div>
				<p class="element-purpose">
					Action button in 4 variants (primary, danger, secondary, ghost) and 2 sizes (md, sm).
					Supports disabled, loading, and fullWidth states.
				</p>
				<div class="element-demo">
					<h4 class="variant-label">All variants (md)</h4>
					<div style="display: flex; gap: 0.5rem; flex-wrap: wrap; padding: 0.5rem 0.625rem;">
						<SettingsButton variant="primary" onClick={() => alert('Primary clicked')}>Primary</SettingsButton>
						<SettingsButton variant="danger" onClick={() => alert('Danger clicked')}>Danger</SettingsButton>
						<SettingsButton variant="secondary" onClick={() => alert('Secondary clicked')}>Secondary</SettingsButton>
						<SettingsButton variant="ghost" onClick={() => alert('Ghost clicked')}>Ghost</SettingsButton>
					</div>
				</div>
				<div class="element-demo">
					<h4 class="variant-label">Small size (sm)</h4>
					<div style="display: flex; gap: 0.5rem; flex-wrap: wrap; padding: 0.5rem 0.625rem;">
						<SettingsButton variant="primary" size="sm">Small Primary</SettingsButton>
						<SettingsButton variant="secondary" size="sm">Small Secondary</SettingsButton>
					</div>
				</div>
				<div class="element-demo">
					<h4 class="variant-label">Disabled & loading</h4>
					<div style="display: flex; gap: 0.5rem; flex-wrap: wrap; padding: 0.5rem 0.625rem;">
						<SettingsButton variant="primary" disabled={true}>Disabled</SettingsButton>
						<SettingsButton variant="primary" loading={true}>Loading...</SettingsButton>
					</div>
				</div>
				<div class="element-demo">
					<h4 class="variant-label">Full width</h4>
					<div style="padding: 0.5rem 0.625rem;">
						<SettingsButton variant="primary" fullWidth={true}>Full Width Button</SettingsButton>
					</div>
				</div>
			</div>

			<!-- 15. SettingsButtonGroup -->
			<div class="element-block">
				<div class="element-header">
					<h3>15. Button Group</h3>
					<span class="element-tag new">SettingsButtonGroup</span>
				</div>
				<p class="element-purpose">
					Groups buttons with configurable alignment: left, center, right, or space-between.
				</p>
				<div class="element-demo">
					<h4 class="variant-label">align="right" (default)</h4>
					<SettingsButtonGroup align="right">
						<SettingsButton variant="ghost" onClick={() => {}}>Cancel</SettingsButton>
						<SettingsButton variant="primary" onClick={() => {}}>Save</SettingsButton>
					</SettingsButtonGroup>
				</div>
				<div class="element-demo">
					<h4 class="variant-label">align="space-between"</h4>
					<SettingsButtonGroup align="space-between">
						<SettingsButton variant="danger" onClick={() => {}}>Delete</SettingsButton>
						<SettingsButton variant="primary" onClick={() => {}}>Confirm</SettingsButton>
					</SettingsButtonGroup>
				</div>
			</div>
		</section>

		<!-- ============================================= -->
		<!-- SECTION E: Feedback & Status                  -->
		<!-- ============================================= -->
		<section class="element-section">
			<h2 class="section-title">E. Feedback & Status</h2>
			<p class="section-description">
				Progress bars, loading states, and badges from <code>settings/elements/</code>.
			</p>

			<!-- 16. SettingsProgressBar -->
			<div class="element-block">
				<div class="element-header">
					<h3>16. Progress Bar</h3>
					<span class="element-tag new">SettingsProgressBar</span>
				</div>
				<p class="element-purpose">
					Horizontal progress indicator in 3 variants: default, warning, success.
					Optionally shows label and percentage text.
				</p>
				<div class="element-demo">
					<h4 class="variant-label">Default (65%)</h4>
					<div style="padding: 0.5rem 0.625rem;">
						<SettingsProgressBar value={65} label="Storage" showPercent={true} />
					</div>
				</div>
				<div class="element-demo">
					<h4 class="variant-label">Warning (90%)</h4>
					<div style="padding: 0.5rem 0.625rem;">
						<SettingsProgressBar value={90} variant="warning" label="Credits" showPercent={true} />
					</div>
				</div>
				<div class="element-demo">
					<h4 class="variant-label">Success (100%)</h4>
					<div style="padding: 0.5rem 0.625rem;">
						<SettingsProgressBar value={100} variant="success" />
					</div>
				</div>
			</div>

			<!-- 17. SettingsLoadingState -->
			<div class="element-block">
				<div class="element-header">
					<h3>17. Loading State</h3>
					<span class="element-tag new">SettingsLoadingState</span>
				</div>
				<p class="element-purpose">
					Placeholder states for loading, empty data, and generation-in-progress scenarios.
				</p>
				<div class="element-demo">
					<h4 class="variant-label">Spinner</h4>
					<SettingsLoadingState variant="spinner" text="Loading sessions..." />
				</div>
				<div class="element-demo">
					<h4 class="variant-label">Empty</h4>
					<SettingsLoadingState variant="empty" text="No passkeys found" hint="Add a passkey to secure your account" />
				</div>
				<div class="element-demo">
					<h4 class="variant-label">Generating</h4>
					<SettingsLoadingState variant="generating" text="Generating recovery key..." />
				</div>
			</div>

			<!-- 18. SettingsBadge -->
			<div class="element-block">
				<div class="element-header">
					<h3>18. Badge</h3>
					<span class="element-tag new">SettingsBadge</span>
				</div>
				<p class="element-purpose">
					Small status labels in 5 variants: info, success, warning, danger, neutral.
				</p>
				<div class="element-demo">
					<div style="display: flex; gap: 0.5rem; flex-wrap: wrap; padding: 0.5rem 0.625rem;">
						<SettingsBadge variant="info" text="Synced" />
						<SettingsBadge variant="success" text="Active" />
						<SettingsBadge variant="warning" text="Expiring" />
						<SettingsBadge variant="danger" text="Revoked" />
						<SettingsBadge variant="neutral" text="Draft" />
					</div>
				</div>
			</div>
		</section>

		<!-- ============================================= -->
		<!-- SECTION F: Data Display                       -->
		<!-- ============================================= -->
		<section class="element-section">
			<h2 class="section-title">F. Data Display</h2>
			<p class="section-description">
				Cards, detail rows, balance display, and code blocks from <code>settings/elements/</code>.
			</p>

			<!-- 19. SettingsCard + SettingsDetailRow -->
			<div class="element-block">
				<div class="element-header">
					<h3>19. Card with Detail Rows</h3>
					<span class="element-tag new">SettingsCard</span>
					<span class="element-tag new">SettingsDetailRow</span>
				</div>
				<p class="element-purpose">
					Card container with optional variant (default, highlighted, current).
					SettingsDetailRow renders label-value pairs inside cards.
				</p>
				<div class="element-demo">
					<h4 class="variant-label">Default card</h4>
					<div style="padding: 0.5rem 0.625rem;">
						<SettingsCard>
							<SettingsDetailRow label="Device" value="MacBook Pro" />
							<SettingsDetailRow label="IP Address" value="192.168.1.xxx" muted={true} />
							<SettingsDetailRow label="Last Active" value="2 hours ago" />
						</SettingsCard>
					</div>
				</div>
				<div class="element-demo">
					<h4 class="variant-label">Highlighted card</h4>
					<div style="padding: 0.5rem 0.625rem;">
						<SettingsCard variant="highlighted" highlightColor="var(--color-primary-start, #4867cd)">
							<SettingsDetailRow label="Plan" value="Pro" highlight={true} />
							<SettingsDetailRow label="Renewal" value="Apr 15, 2026" />
						</SettingsCard>
					</div>
				</div>
				<div class="element-demo">
					<h4 class="variant-label">Current card</h4>
					<div style="padding: 0.5rem 0.625rem;">
						<SettingsCard variant="current">
							<SettingsDetailRow label="Session" value="This device" highlight={true} />
							<SettingsDetailRow label="Browser" value="Chrome 125" />
						</SettingsCard>
					</div>
				</div>
			</div>

			<!-- 20. SettingsBalanceDisplay -->
			<div class="element-block">
				<div class="element-header">
					<h3>20. Balance Display</h3>
					<span class="element-tag new">SettingsBalanceDisplay</span>
				</div>
				<p class="element-purpose">
					Large-format balance/credit counter with icon and label.
				</p>
				<div class="element-demo">
					<div style="padding: 0.5rem 0.625rem;">
						<SettingsBalanceDisplay amount="1,250" label="Credits remaining" icon="coin" />
					</div>
				</div>
			</div>

			<!-- 21. SettingsCodeBlock -->
			<div class="element-block">
				<div class="element-header">
					<h3>21. Code Block</h3>
					<span class="element-tag new">SettingsCodeBlock</span>
				</div>
				<p class="element-purpose">
					Monospace code display with optional copy button and max height.
					Useful for recovery codes, API keys, or configuration snippets.
				</p>
				<div class="element-demo">
					<div style="padding: 0.5rem 0.625rem;">
						<SettingsCodeBlock code={demoRecoveryCodes} copyable={true} maxHeight="8rem" />
					</div>
				</div>
			</div>
		</section>

		<!-- ============================================= -->
		<!-- SECTION G: Confirmation & Navigation          -->
		<!-- ============================================= -->
		<section class="element-section">
			<h2 class="section-title">G. Confirmation & Navigation</h2>
			<p class="section-description">
				Page headers, confirm blocks, avatars, and checkbox lists from <code>settings/elements/</code>.
			</p>

			<!-- 22. SettingsPageHeader -->
			<div class="element-block">
				<div class="element-header">
					<h3>22. Page Header</h3>
					<span class="element-tag new">SettingsPageHeader</span>
				</div>
				<p class="element-purpose">
					Top-of-page title with optional description text. Used at the start of settings sub-pages.
				</p>
				<div class="element-demo">
					<SettingsPageHeader
						title="Export Account Data"
						description="Download a copy of your data including chats, settings, and uploaded files."
					/>
				</div>
			</div>

			<!-- 23. SettingsConfirmBlock -->
			<div class="element-block">
				<div class="element-header">
					<h3>23. Confirm Block</h3>
					<span class="element-tag new">SettingsConfirmBlock</span>
				</div>
				<p class="element-purpose">
					Confirmation checkbox with warning text. Used before destructive or important actions.
					Available in danger and warning variants.
				</p>
				<div class="element-demo">
					<h4 class="variant-label">Danger variant</h4>
					<SettingsConfirmBlock
						variant="danger"
						warningText="This action cannot be undone. All your data will be permanently deleted."
						confirmLabel="I understand and want to delete my account"
						bind:checked={confirmDangerChecked}
					/>
					<div class="state-display">checked: {confirmDangerChecked}</div>
				</div>
				<div class="element-demo">
					<h4 class="variant-label">Warning variant</h4>
					<SettingsConfirmBlock
						variant="warning"
						warningText="Changing your email will require re-verification. You will be logged out of all devices."
						confirmLabel="I want to change my email address"
					/>
				</div>
			</div>

			<!-- 24. SettingsAvatar -->
			<div class="element-block">
				<div class="element-header">
					<h3>24. Avatar</h3>
					<span class="element-tag new">SettingsAvatar</span>
				</div>
				<p class="element-purpose">
					User avatar in 3 sizes (sm, md, lg). Shows placeholder initials when no image is provided.
					Optionally editable with an edit overlay.
				</p>
				<div class="element-demo">
					<h4 class="variant-label">Placeholder (lg)</h4>
					<div style="padding: 0.5rem 0.625rem;">
						<SettingsAvatar size="lg" placeholder="OM" />
					</div>
				</div>
				<div class="element-demo">
					<h4 class="variant-label">With image (md)</h4>
					<div style="padding: 0.5rem 0.625rem;">
						<SettingsAvatar src="https://api.dicebear.com/7.x/avataaars/svg?seed=OpenMates" size="md" />
					</div>
				</div>
			</div>

			<!-- 25. SettingsCheckboxList -->
			<div class="element-block">
				<div class="element-header">
					<h3>25. Checkbox List</h3>
					<span class="element-tag new">SettingsCheckboxList</span>
				</div>
				<p class="element-purpose">
					List of checkboxes with labels, descriptions, and icons. Options are bindable for
					two-way state updates. Useful for bulk selection (export, permissions, etc.).
				</p>
				<div class="element-demo">
					<SettingsCheckboxList bind:options={checkboxOptions} />
					<div class="state-display">
						selected: {checkboxOptions.filter(o => o.checked).map(o => o.id).join(', ') || 'none'}
					</div>
				</div>
			</div>
		</section>

		<!-- ============================================= -->
		<!-- SECTION H: Layout Primitives                  -->
		<!-- ============================================= -->
		<section class="element-section">
			<h2 class="section-title">H. Layout Primitives</h2>
			<p class="section-description">
				Dividers, gradient links, and page container from <code>settings/elements/</code>.
			</p>

			<!-- 26. SettingsDivider -->
			<div class="element-block">
				<div class="element-header">
					<h3>26. Divider</h3>
					<span class="element-tag new">SettingsDivider</span>
				</div>
				<p class="element-purpose">
					Horizontal separator in 3 spacing sizes (sm, md, lg). Used between logical groups
					of settings elements.
				</p>
				<div class="element-demo">
					<div style="padding: 0.5rem 0.625rem;">
						<p style="margin: 0; font-size: 0.8125rem; color: var(--color-grey-60, #888);">Content above (sm spacing)</p>
						<SettingsDivider spacing="sm" />
						<p style="margin: 0; font-size: 0.8125rem; color: var(--color-grey-60, #888);">Content between (md spacing)</p>
						<SettingsDivider spacing="md" />
						<p style="margin: 0; font-size: 0.8125rem; color: var(--color-grey-60, #888);">Content between (lg spacing)</p>
						<SettingsDivider spacing="lg" />
						<p style="margin: 0; font-size: 0.8125rem; color: var(--color-grey-60, #888);">Content below</p>
					</div>
				</div>
			</div>

			<!-- 27. SettingsGradientLink -->
			<div class="element-block">
				<div class="element-header">
					<h3>27. Gradient Link</h3>
					<span class="element-tag new">SettingsGradientLink</span>
				</div>
				<p class="element-purpose">
					Text link styled with the OpenMates primary gradient. Can be a standard href link
					or a click-handler button.
				</p>
				<div class="element-demo">
					<div style="display: flex; flex-direction: column; gap: 0.75rem; padding: 0.5rem 0.625rem;">
						<SettingsGradientLink href="#">View Privacy Policy</SettingsGradientLink>
						<SettingsGradientLink onClick={() => alert('Download started')}>Download Invoice</SettingsGradientLink>
					</div>
				</div>
			</div>

			<!-- 28. SettingsPageContainer -->
			<div class="element-block">
				<div class="element-header">
					<h3>28. Page Container</h3>
					<span class="element-tag new">SettingsPageContainer</span>
				</div>
				<p class="element-purpose">
					Top-level wrapper that constrains settings page content to a max width (narrow, default,
					wide). This preview page itself uses its own container, so a nested demo is shown below.
				</p>
				<div class="element-demo">
					<SettingsPageContainer maxWidth="narrow">
						<p style="margin: 0; font-size: 0.8125rem; color: var(--color-grey-60, #888); text-align: center;">
							This content is inside a <code>SettingsPageContainer</code> with <code>maxWidth="narrow"</code>.
						</p>
					</SettingsPageContainer>
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
