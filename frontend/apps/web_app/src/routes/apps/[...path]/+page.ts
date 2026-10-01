/** Preserve deep app, skill and detail paths when opening the root shell. */
import { redirect } from '@sveltejs/kit';
import { buildAppsWorkspaceHash } from '@repo/ui/utils/appsWorkspaceRoute';

export function load({ params, url }: { params: { path?: string }; url: URL }) {
  const query = url.searchParams.toString();
  const path = `apps/${params.path ?? ''}${query ? `&${query}` : ''}`;
  throw redirect(307, `/${buildAppsWorkspaceHash(path)}`);
}
