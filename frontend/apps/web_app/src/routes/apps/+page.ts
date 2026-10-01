/** Forward readable Apps URLs into the persistent root workspace shell. */
import { redirect } from '@sveltejs/kit';
import { buildAppsWorkspaceHash } from '@repo/ui/utils/appsWorkspaceRoute';

export function load({ url }: { url: URL }) {
  const query = url.searchParams.toString();
  throw redirect(307, `/${buildAppsWorkspaceHash(query ? `apps&${query}` : 'apps')}`);
}
