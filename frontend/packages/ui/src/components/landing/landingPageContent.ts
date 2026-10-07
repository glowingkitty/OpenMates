/** A published event, news item, or blog post supplied by the landing route. */
export interface LandingPublication {
  id: string;
  title: string;
  description?: string;
  href: string;
  image?: string;
  label?: string;
}
