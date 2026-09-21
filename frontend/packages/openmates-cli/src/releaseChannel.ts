const RELEASES_URL = "https://api.github.com/repos/glowingkitty/OpenMates/releases?per_page=100";
const EXACT_RELEASE_TAG = /^v(\d+)\.(\d+)\.(\d+)$/;

type GitHubRelease = {
  draft?: boolean;
  tag_name?: string;
};

export function selectLatestStableReleaseTag(payload: unknown): string {
  if (!Array.isArray(payload)) throw new Error("GitHub returned invalid release metadata.");
  const candidates = payload.flatMap((item): Array<{ tag: string; version: number[] }> => {
    if (!item || typeof item !== "object") return [];
    const release = item as GitHubRelease;
    if (release.draft !== false || typeof release.tag_name !== "string") return [];
    const match = EXACT_RELEASE_TAG.exec(release.tag_name);
    return match
      ? [{ tag: release.tag_name, version: match.slice(1).map((part) => Number(part)) }]
      : [];
  });
  candidates.sort((left, right) => {
    for (let index = 0; index < 3; index += 1) {
      const difference = right.version[index] - left.version[index];
      if (difference !== 0) return difference;
    }
    return 0;
  });
  if (!candidates[0]) {
    throw new Error("No verified stable OpenMates release is published on GitHub.");
  }
  return candidates[0].tag;
}

export async function resolveStableImageTag(
  fetcher: typeof fetch = fetch,
): Promise<string> {
  let response: Response;
  try {
    response = await fetcher(RELEASES_URL, {
      headers: {
        Accept: "application/vnd.github+json",
        "User-Agent": "openmates-cli",
      },
      signal: AbortSignal.timeout(15_000),
    });
  } catch (error) {
    throw new Error(
      `Could not resolve the stable OpenMates release from GitHub: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
  if (!response.ok) {
    throw new Error(`Could not resolve the stable OpenMates release from GitHub (HTTP ${response.status}).`);
  }
  return selectLatestStableReleaseTag(await response.json());
}
