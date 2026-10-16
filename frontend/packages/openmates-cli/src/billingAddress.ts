/** Optional invoice recipient address, scoped to one Personal or Team billing context. */
export interface BuyerAddress {
  name: string;
  street_line_1: string;
  street_line_2?: string | null;
  postal_code: string;
  city: string;
  region?: string | null;
  country: string;
  vat_id?: string | null;
}
