export type NewsroomView = 'news' | 'blog' | 'release' | 'blog-post' | 'social-post';

export type NewsroomItemKind = 'release' | 'update' | 'blog' | 'social' | 'coverage';

export type SocialPostPlatform = 'bluesky' | 'instagram' | 'mastodon';

export interface SocialPostLink {
  platform: SocialPostPlatform;
  label: string;
  href: string;
}

export interface NewsroomMediaSource {
  url: string;
  type: 'image' | 'video';
  alt: string;
  posterUrl?: string;
}

export interface NewsroomItem {
  id: string;
  kind: NewsroomItemKind;
  eyebrow: string;
  title: string;
  excerpt: string;
  bodyText?: string;
  publishedLabel: string;
  readTime?: string;
  author?: string;
  language?: string;
  socialLinks?: SocialPostLink[];
  media?: NewsroomMediaSource;
  mediaShape: 'landscape' | 'portrait' | 'none';
}

export interface NewsroomHero {
  eyebrow: string;
  kicker?: string;
  title: string;
  meta: string;
  actionLabel: string;
  media?: NewsroomMediaSource;
}

export interface NewsroomArticleContent {
  byline: string;
  publishedLabel: string;
  intro: string;
  paragraphs?: string[];
  bodyHtml?: string;
  media?: NewsroomMediaSource[];
  promptTitle?: string;
  promptBody?: string;
}

export interface NewsroomSurfaceData {
  brand: string;
  newsLabel: string;
  blogLabel: string;
  openAppLabel: string;
  tryItLabel: string;
  searchLabel: string;
  latestNewsLabel: string;
  latestBlogLabel: string;
  socialLabel: string;
  coverageLabel: string;
  morePostsLabel: string;
  relatedLabel: string;
  pressKitLabel: string;
  pressInquiryLabel: string;
  subscribeLabel: string;
  followLabel: string;
  emptyStateLabel: string;
  showAllLabel: string;
  copyLabel: string;
  previousMediaLabel: string;
  nextMediaLabel: string;
  articleMediaLabel: string;
  closeSocialLabel: string;
  originalPostNavLabel: string;
  releaseContactLabel: string;
  blogContactLabel: string;
  heroNews: NewsroomHero;
  heroBlog: NewsroomHero;
  newsItems: NewsroomItem[];
  blogItems: NewsroomItem[];
  socialItems: NewsroomItem[];
  coverageItems: NewsroomItem[];
  releaseArticle: NewsroomArticleContent;
  blogArticle: NewsroomArticleContent;
}

export interface NewsroomAction {
  type:
    | 'open-item'
    | 'open-app'
    | 'try-feature'
    | 'press-kit'
    | 'press-inquiry'
    | 'subscribe-news';
  itemId?: string;
}
