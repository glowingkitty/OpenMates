-- Bounded account/app library scans and chatless graph child lookup.
CREATE INDEX IF NOT EXISTS embeds_apps_personal_catalog_idx
    ON public.embeds (hashed_user_id, app_id, created_at DESC, embed_id DESC)
    WHERE hashed_team_id IS NULL AND workspace_origin IN ('web_apps', 'chat');

CREATE INDEX IF NOT EXISTS embeds_apps_team_catalog_idx
    ON public.embeds (hashed_team_id, app_id, created_at DESC, embed_id DESC)
    WHERE hashed_team_id IS NOT NULL AND workspace_origin IN ('web_apps', 'chat');

CREATE INDEX IF NOT EXISTS embeds_apps_root_graph_idx
    ON public.embeds (root_embed_id, embed_id)
    WHERE root_embed_id IS NOT NULL;
