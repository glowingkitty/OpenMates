/**
 * Teams Specification fixture for reviewing the real fullscreen renderer.
 * Based on the Teams chapters, flows and models, with concise presentation text.
 * Evidence is explicitly illustrative, not a live or verified Check result.
 * No private account, encrypted embed or server operation is involved.
 * Open /dev/preview/embeds/specifications/SpecificationEmbedFullscreen?chrome=0.
 */
import type { SpecificationDocument } from './SpecificationDocument';

const document: SpecificationDocument = {
  title: 'Teams', project: 'OpenMates', category: 'Feature',
  summary: 'Organize teams. Work together on shared chats, projects, tasks and workflows.',
  outcome: 'People can create and join teams and share access to chats, workflows, projects, tasks and plans — separate from their personal data.',
  outcomeReference: { title: 'Team architecture', labels: ['Personal', 'Team'], description: 'Personal and Team contexts remain separate. Authorized members share Team resources through Team-scoped access and encryption.' },
  previewNotice: 'Design preview · proof states are illustrative',
  scope: {
    included: ['Personal and Team contexts stay separate.', 'Members collaborate on shared resources; viewers have read-only access.'],
    excluded: ['Private channels, per-resource permissions and automatic key rotation.', 'Apple implementation in this Teams increment.'],
  },
  chapters: [
    { id: 'team-creation-profile', title: 'Team creation & deletion', introduction: 'Create a Team with its own identity and encryption. Delete it without changing personal resources.', requirementIds: ['openmates.teams.lifecycle.encrypted-profiled', 'openmates.teams.profile-image.safe-parity'], flowIds: ['create-team', 'delete-team', 'profile-image-rejected'], modelIds: ['TeamRecord', 'TeamProfileImage'] },
    { id: 'membership-invitations', title: 'Membership & permissions', introduction: 'Make it clear who can collaborate, manage access and make changes.', requirementIds: ['openmates.teams.membership.role-gated'], flowIds: ['invite-member', 'viewer-mutation-denied'], modelIds: ['TeamMembership'] },
  ],
  requirements: [
    { id: 'openmates.teams.lifecycle.encrypted-profiled', statement: 'Create, update and delete encrypted Teams with their own profile and wrapped Team key. Personal resources remain separate.', appliesTo: ['REST API', 'CLI', 'npm SDK', 'pip SDK', 'Web'], example: 'Create a Team named Studio. It appears in the context switcher. Deleting Studio revokes Team access and returns the device to Personal; personal chats remain unchanged.', proof: { state: 'passed', title: 'Team lifecycle', explanation: 'Illustrative passing evidence for this layout only. No current Check Run has been verified. A real result must cover every required interface and this exact revision.' } },
    { id: 'openmates.teams.profile-image.safe-parity', statement: 'Show a generated or uploaded Team profile image consistently, and reject invalid uploads without replacing the current image.', appliesTo: ['REST API', 'CLI', 'npm SDK', 'pip SDK', 'Web'], example: 'An admin uploads an unsupported file. The upload is rejected with an explanation; the previous Team image remains visible.', proof: { state: 'open', title: 'Team profile image', explanation: 'No current proof. Link a revision-matched Check Run covering valid images, rejected uploads and supported interfaces.' } },
    { id: 'openmates.teams.membership.role-gated', statement: 'Enforce owner, admin, member and viewer permissions. Viewers can read shared resources but cannot change them.', appliesTo: ['REST API', 'CLI', 'npm SDK', 'pip SDK', 'Web'], example: 'A viewer attempts to change the Team name. The request is rejected and the existing name is preserved.', proof: { state: 'stale', title: 'Membership permissions', explanation: 'Illustrative stale proof. A previously passing result is not current evidence after the requirement or tested source changes.' } },
  ],
  flows: [
    { id: 'create-team', title: 'Create a Team', kind: 'user_flow', requiredCheckRefs: ['team-creation-behavior', 'team-creation-design'], steps: ['Open Settings → Teams.', 'Enter a name and optional description.', 'Accept or change the generated profile image.', 'Confirm creation; the creator becomes the owner.', 'Select the Team in the context switcher.'] },
    { id: 'delete-team', title: 'Delete a Team', kind: 'user_flow', steps: ['The owner opens destructive actions.', 'Confirm deletion of this Team.', 'Revoke Team memberships, sources and account access.', 'Return to Personal context; preserve personal resources.'] },
    { id: 'profile-image-rejected', title: 'Profile image rejected', kind: 'edge_case', steps: ['An admin selects an unsupported image.', 'Explain why the upload was rejected.', 'Keep the previous image and allow another selection.'] },
    { id: 'invite-member', title: 'Invite a member', kind: 'user_flow', steps: ['An owner or admin creates an invitation.', 'The recipient opens and accepts the invitation.', 'Authorized membership and encrypted Team access become available.'] },
    { id: 'viewer-mutation-denied', title: 'Viewer tries to edit', kind: 'edge_case', steps: ['A viewer opens a shared resource.', 'A mutation is attempted through an interface.', 'Reject the mutation; retain read access and the original content.'] },
  ],
  linkedChecks: [
    { id: 'team-creation-behavior', title: 'Team creation works', method: 'Deterministic', description: 'Verify creation, context switching and separation from personal resources.', evidence: 'Not run in this preview. A matching Check Run would supply its results, test sources and recording here.' },
    { id: 'team-creation-design', title: 'Team creation matches the approved design', method: 'Human confirmation', description: 'Review the component states, labels and layout against the approved design.', evidence: 'Awaiting review. This illustrative link is not a recorded approval or passing result.' },
  ],
  models: [
    { id: 'TeamRecord', description: 'The encrypted identity of a Team, independent from Personal context.', fields: [{ name: 'team_id', type: 'stable ID', description: 'Identifies this Team.' }, { name: 'encrypted_name', type: 'ciphertext', description: 'Name readable only by authorized clients.' }, { name: 'encrypted_description', type: 'ciphertext · optional', description: 'Private description.' }, { name: 'slug', type: 'public string · optional', description: 'Unique when set; not secret.' }, { name: 'status', type: 'active · archived · deleted', description: 'Team lifecycle state.' }, { name: 'encrypted_profile_image_metadata', type: 'ciphertext', description: 'Default icon/background or uploaded image reference.' }, { name: 'encrypted_billing_profile', type: 'ciphertext · optional', description: 'Private billing profile.' }] },
    { id: 'TeamProfileImage', description: 'A generated or uploaded Team profile image and its authorized reference.', fields: [{ name: 'mode', type: 'generated · uploaded', description: 'How the profile image is provided.' }, { name: 'icon_name', type: 'string · optional', description: 'White icon required for a generated image.' }, { name: 'background_color', type: 'design token or hex color', description: 'Background required for a generated image.' }, { name: 'image_url', type: 'authenticated media URL', description: 'Required for an uploaded image; the raw upload remains private.' }, { name: 'content_safety_status', type: 'pending · accepted · rejected · null', description: 'Image safety outcome.' }] },
    { id: 'TeamMembership', description: 'An account’s role and membership in a Team.', fields: [{ name: 'role', type: 'owner · admin · member · viewer', description: 'Controls the permitted operations.' }, { name: 'status', type: 'active · invited · left · removed', description: 'The membership lifecycle state.' }, { name: 'permission_state', type: 'derived permission summary', description: 'Must match the role and membership status.' }] },
  ],
};

export default { data: { decodedContent: { document } }, onClose: () => window.dispatchEvent(new CustomEvent('specification-preview-close')) };
