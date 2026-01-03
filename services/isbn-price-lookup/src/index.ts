import express from 'express';
import type { Request, Response } from 'express';

const app = express();
app.use(express.json());

const {
  SHOP_URL,
  SHOPIFY_ACCESS_TOKEN,
  SHOPIFY_API_VERSION,
  ISBN_PRICE_LOOKUP_SHARED_SECRET,
  PORT,
} = process.env;

if (!SHOP_URL || !SHOPIFY_ACCESS_TOKEN || !SHOPIFY_API_VERSION || !ISBN_PRICE_LOOKUP_SHARED_SECRET) {
  console.error('Missing required environment variables.');
  process.exit(1);
}

function normalizeIsbn(isbn: string): string {
  return isbn.trim().replace(/-/g, '');
}

function chunkArray<T>(arr: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let i = 0; i < arr.length; i += size) {
    chunks.push(arr.slice(i, i + size));
  }
  return chunks;
}

async function queryShopify(isbns: string[]) {
  const query = `
    query productVariantsByBarcodes($barcodes: [String!]!) {
      productVariants(first: 50, query: $barcodes) {
        edges {
          node {
            barcode
            price
            product {
              title
            }
          }
        }
      }
    }
  `;

  // Shopify GraphQL does not support querying variants by barcode list directly.
  // Instead, we will build a query string that searches variants by barcode using the query parameter.
  // The query param accepts a string that can contain barcode:barcode1 OR barcode:barcode2 ...
  // We'll build this string accordingly.

  // Build query string for barcodes
  const barcodeQuery = isbns.map(isbn => `barcode:${isbn}`).join(' OR ');

  const graphqlQuery = `
    {
      productVariants(first: 50, query: "${barcodeQuery}") {
        edges {
          node {
            barcode
            price
            product {
              title
            }
          }
        }
      }
    }
  `;

  const response = await fetch(`https://${SHOP_URL}/admin/api/${SHOPIFY_API_VERSION}/graphql.json`, {
    method: 'POST',
    headers: new Headers({
      'X-Shopify-Access-Token': SHOPIFY_ACCESS_TOKEN as string,
      'Content-Type': 'application/json',
    }),
    body: JSON.stringify({ query: graphqlQuery }),
  });

  if (!response.ok) {
    throw new Error(`Shopify API error: ${response.status} ${response.statusText}`);
  }
  const json = await response.json();
  if (json.errors) {
    throw new Error(`Shopify API returned errors: ${JSON.stringify(json.errors)}`);
  }
  return json.data.productVariants.edges.map((edge: any) => edge.node);
}

app.post('/isbn/prices', async (req: Request, res: Response): Promise<void> => {
  try {
    const secret = req.header('X-ISBN-PRICE-SECRET');
    if (secret !== ISBN_PRICE_LOOKUP_SHARED_SECRET) {
      res.status(401).json({ error: 'Unauthorized' });
      return;
    }

    const { isbns } = req.body;
    if (!Array.isArray(isbns)) {
      res.status(400).json({ error: 'Invalid request body: isbns must be an array' });
      return;
    }

    // Normalize ISBNs
    const normalizedIsbns = isbns.map(normalizeIsbn);

    // Batch them max 50 per batch
    const batches = chunkArray(normalizedIsbns, 50);

    const resultsMap: Record<string, { price: string; currencyCode: string; title: string } | 'NOT FOUND'> = {};

    for (const batch of batches) {
      const variants = await queryShopify(batch);
      // Map barcode to variant info
      const variantMap: Record<string, any> = {};
      for (const variant of variants) {
        variantMap[variant.barcode] = variant;
      }
      for (const isbn of batch) {
        if (variantMap[isbn]) {
          const v = variantMap[isbn];
          resultsMap[isbn] = {
            price: v.price,
            currencyCode: "USD",
            title: v.product.title,
          };
        } else {
          resultsMap[isbn] = 'NOT FOUND';
        }
      }
    }

    // Return results in the same order as input
    const responseData = normalizedIsbns.map(isbn => resultsMap[isbn]);

    res.json({ results: responseData });
  } catch (error: any) {
    console.error(error);
    res.status(500).json({ error: 'Internal Server Error' });
  }
});

app.get('/health', (_req: Request, res: Response) => {
  res.json({ status: 'ok' });
});

app.listen(PORT, () => {
  console.log(`Server listening on port ${PORT}`);
});
