"""Regression guard for Teams settings-only web placement.

Teams V1 must not reintroduce a top-level `/teams` workspace route or a
workspace navigation tab. Web team management belongs under Settings, and
profile-menu context switching owns Personal/team selection.
"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def read_repo(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


# contract-test: direct surface=gui.web assertions=teams.workspace.surface-parity
def test_teams_has_no_top_level_workspace_route_or_export() -> None:
    route_dir = PROJECT_ROOT / "frontend/apps/web_app/src/routes/teams"
    route_files = [path for path in route_dir.rglob("*") if path.is_file()] if route_dir.exists() else []
    assert route_files == []
    assert not (
        PROJECT_ROOT / "frontend/packages/ui/src/components/teams/TeamsWorkspacePage.svelte"
    ).exists()
    assert "TeamsWorkspacePage" not in read_repo("frontend/packages/ui/index.ts")


# contract-test: direct surface=gui.web assertions=teams.workspace.surface-parity
def test_teams_workspace_navigation_tab_is_absent() -> None:
    header = read_repo("frontend/packages/ui/src/components/Header.svelte")
    assert "teams-nav-link" not in header
    assert "href: '/teams'" not in header
    assert 'href: "/teams"' not in header
    assert "isTeamsRoute" not in header


# contract-test: direct surface=gui.web assertions=teams.workspace.surface-parity
def test_teams_settings_route_is_registered() -> None:
    routes = read_repo("frontend/packages/ui/src/components/settings/settingsRoutes.ts")
    settings = read_repo("frontend/packages/ui/src/components/Settings.svelte")
    assert "import SettingsTeams" in routes
    assert "teams: SettingsTeams" in routes
    assert "teams/{teamId}" in routes
    assert "SettingsTeams" in settings


# contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
def test_profile_team_loading_is_feature_gated_and_logout_safe() -> None:
    settings = read_repo("frontend/packages/ui/src/components/Settings.svelte")
    assert "!get(authStore).isAuthenticated || !isTeamsFeatureEnabled()" in settings
    assert "refreshGeneration !== profileTeamsRefreshGeneration" in settings
    assert "profileTeamsRefreshGeneration += 1" in settings
    assert "$featureAvailabilityStore.disabledById?.['platform:teams'] !== true" in settings
