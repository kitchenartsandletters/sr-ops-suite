/**
 * Runs when the add-on is installed.
 */
function onInstall(e) {
  onOpen(e);
}

/**
 * Runs when the document is opened.
 */
function onOpen(e) {
  const menu = SpreadsheetApp.getUi().createAddonMenu();
  
  // This ensures the menu item is created even if the user 
  // hasn't fully authorized the script yet.
  menu.addItem('Inject Shopify List Prices', 'injectShopifyListPrices');
  menu.addToUi();
}

function getConfig_() {
  const props = PropertiesService.getScriptProperties();
  const endpoint = props.getProperty('RAILWAY_ENDPOINT_URL');
  const secret = props.getProperty('SHARED_SECRET');
  if (!endpoint || !secret) {
    throw new Error('Missing configuration: Please set RAILWAY_ENDPOINT_URL and SHARED_SECRET in Script Properties.');
  }
  return { endpoint, secret };
}

function onOpen(e) {
  SpreadsheetApp.getUi()
    .createAddonMenu()
    .addItem('Inject Shopify List Prices', 'injectShopifyListPrices')
    .addToUi();
}

function injectShopifyListPrices() {
  library_injectListPrices();
}

function library_injectListPrices() {
  const { endpoint: RAILWAY_ENDPOINT_URL, secret: SHARED_SECRET } = getConfig_();
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const data = sheet.getDataRange().getValues();

  let isbnCol = -1;
  let listPriceCol = -1;

  // Detect header row with ISBN and List Price columns (case-insensitive)
  for (let row = 0; row < data.length; row++) {
    for (let col = 0; col < data[row].length; col++) {
      const cellVal = String(data[row][col]).toLowerCase();
      if (cellVal === 'isbn') isbnCol = col;
      if (cellVal === 'list price') listPriceCol = col;
    }
    if (isbnCol !== -1 && listPriceCol !== -1) {
      var headerRow = row;
      break;
    }
  }

  const ui = SpreadsheetApp.getUi();

  if (isbnCol === -1 || listPriceCol === -1) {
    ui.alert('Could not find both "ISBN" and "List Price" headers.');
    return;
  }

  const isbnsToLookup = [];
  const rowsToUpdate = [];

  // Collect ISBNs from rows below header where List Price cell is empty
  for (let r = headerRow + 1; r < data.length; r++) {
    const listPriceCell = data[r][listPriceCol];
    if (listPriceCell === '' || listPriceCell === null) {
      let isbnRaw = data[r][isbnCol];
      if (isbnRaw !== '' && isbnRaw !== null) {
        // Normalize ISBN: trim and remove hyphens
        const isbnNormalized = String(isbnRaw).trim().replace(/-/g, '');
        if (isbnNormalized !== '') {
          isbnsToLookup.push(isbnNormalized);
          rowsToUpdate.push(r);
        }
      }
    }
  }

  if (isbnsToLookup.length === 0) {
    ui.alert('No rows found with empty List Price and valid ISBN.');
    return;
  }

  // Prepare POST request
  const payload = JSON.stringify({ isbns: isbnsToLookup });
  const options = {
    method: 'post',
    contentType: 'application/json',
    headers: {
      'X-ISBN-PRICE-SECRET': SHARED_SECRET
    },
    payload: payload,
    muteHttpExceptions: true
  };

  let response;
  try {
    response = UrlFetchApp.fetch(RAILWAY_ENDPOINT_URL, options);
  } catch (e) {
    ui.alert('Error fetching prices: ' + e.message);
    return;
  }

  if (response.getResponseCode() !== 200) {
    ui.alert('Failed to fetch prices: HTTP ' + response.getResponseCode());
    return;
  }

  let json;
  try {
    json = JSON.parse(response.getContentText());
  } catch (e) {
    ui.alert('Invalid JSON response from server.');
    return;
  }

  if (!json.results || !Array.isArray(json.results)) {
    ui.alert('Unexpected response format from server.');
    return;
  }

  // Write prices or "NOT FOUND" into List Price cells
  for (let i = 0; i < rowsToUpdate.length; i++) {
    const rowIndex = rowsToUpdate[i];
    const price = json.results[i];
    if (price && typeof price === 'object' && price.hasOwnProperty('price')) {
      sheet.getRange(rowIndex + 1, listPriceCol + 1).setValue(price.price);
    } else {
      sheet.getRange(rowIndex + 1, listPriceCol + 1).setValue('NOT FOUND');
    }
  }

  SpreadsheetApp.getActiveSpreadsheet().toast('List Prices updated for ' + rowsToUpdate.length + ' rows.', 'Publisher Tools');
}