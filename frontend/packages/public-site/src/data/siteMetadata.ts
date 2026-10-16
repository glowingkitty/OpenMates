import languages from './languages.json';

export const supportedLanguages: Array<{code: string; name: string; nativeName?: string; rtl?: boolean}> = languages.languages;

export const socialLinks: Array<{label: string; href: string; iconUrl: string}> = [
  { label: 'GitHub', href: 'https://github.com/glowingkitty/OpenMates', iconUrl: '/icons/github.svg' },
  { label: 'Bluesky', href: 'https://bsky.app/profile/openmates.bsky.social', iconUrl: '/icons/bluesky.svg' },
  { label: 'Mastodon', href: 'https://mastodon.social/@OpenMates', iconUrl: '/icons/mastodon.svg' },
  { label: 'Discord', href: 'https://discord.gg/bHtkxZB5cc', iconUrl: '/icons/discord.svg' },
  { label: 'Instagram', href: 'https://instagram.com/openmates_official', iconUrl: '/icons/instagram.svg' },
  { label: 'Pixelfed', href: 'https://pixelfed.social/@openmates', iconUrl: '/icons/pixelfed.svg' },
  { label: 'Meetup', href: 'https://www.meetup.com/openmates-meetup-group/', iconUrl: '/icons/meetup.svg' },
  { label: 'Signal', href: 'https://signal.group/#CjQKIOlYZ63Rz7sibDjQ680wO1a0NcKxtfL0in2BA6Yvbr82EhDNd6GJYtaPfHn4BFcsETQq', iconUrl: '/icons/signal.svg' }
];

export const signalGroupUrl = 'https://signal.group/#CjQKIOlYZ63Rz7sibDjQ680wO1a0NcKxtfL0in2BA6Yvbr82EhDNd6GJYtaPfHn4BFcsETQq';
