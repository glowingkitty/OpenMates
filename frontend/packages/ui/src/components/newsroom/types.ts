export type NewsroomView = 'news' | 'blog' | 'release' | 'blog-post' | 'social-post';

export type NewsroomItemKind = 'release' | 'update' | 'blog' | 'social' | 'coverage';

export type SocialPostPlatform = 'bluesky' | 'instagram' | 'mastodon';

export interface SocialPostLink {
  platform: SocialPostPlatform;
  label: string;
  href: string;
}

export interface NewsroomItem {
  id: string;
  kind: NewsroomItemKind;
  eyebrow: string;
  title: string;
  excerpt: string;
  publishedLabel: string;
  readTime?: string;
  author?: string;
  language?: string;
  socialLinks?: SocialPostLink[];
  mediaShape: 'landscape' | 'portrait' | 'none';
}

export interface NewsroomHero {
  eyebrow: string;
  kicker?: string;
  title: string;
  meta: string;
  actionLabel: string;
}

export interface NewsroomArticleContent {
  byline: string;
  publishedLabel: string;
  intro: string;
  paragraphs: string[];
  promptTitle: string;
  promptBody: string;
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
