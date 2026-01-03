export type PriceResult =
  | { price: string; currencyCode: string; title: string }
  | 'NOT FOUND';

export interface PriceLookupResponse {
  results: PriceResult[];
}