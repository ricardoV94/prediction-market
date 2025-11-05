/**
 * Runs a live test of `executeTradeCore` against the actual spreadsheet.
 *
 * HOW TO RUN:
 * 1. Open the Apps Script editor.
 * 2. Select "runLiveTradeTest" from the function dropdown in the toolbar.
 * 3. Click "Run".
 * 4. Check the logs (View > Logs) to see the results.
 * 5. Check your "Ledger" and "Markets" sheets for the new entries.
 */
function runLiveTradeTest() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const marketsSheet = spreadsheet.getSheetByName("Markets");
  const ledgerSheet = spreadsheet.getSheetByName("Ledger");

  if (!marketsSheet || !ledgerSheet) {
    console.log(
      "ERROR: Please ensure your spreadsheet has both 'Markets' and 'Ledger' sheets.",
    );
    return;
  }

  // --- Test Configuration ---
  const testUserId = 1;
  const testMarketId = 1;
  const testUserEmail = "live-test@example.com";

  console.log("--- Starting Live Test for executeTradeCore ---");
  console.log(`Using User ID: ${testUserId}, Market ID: ${testMarketId}`);

  // --- Execute a PURCHASE ---
  console.log("\nTesting a PURCHASE of 10 'Yes' shares...");
  const purchaseArgs = {
    userId: testUserId,
    marketId: testMarketId,
    marketStatus: "Open",
    shareType: "Yes",
    quantity: 10,
    totalCost: 50, // A fixed cost for this test
    userEmail: testUserEmail,
  };

  const purchaseResult = executeTradeCore(spreadsheet, purchaseArgs);
  console.log("Purchase Result: " + JSON.stringify(purchaseResult));

  if (purchaseResult.ok) {
    console.log(
      "✅ PURCHASE test PASSED. A new transaction should be in the Ledger.",
    );
  } else {
    console.log("❌ PURCHASE test FAILED: " + purchaseResult.message);
    return; // Stop if purchase fails
  }

  // --- Execute a SALE ---
  console.log("\nTesting a SALE of 5 'Yes' shares...");
  const saleArgs = {
    userId: testUserId,
    marketId: testMarketId,
    marketStatus: "Open",
    shareType: "Yes",
    quantity: -5,
    totalCost: -25, // Negative cost because the user receives money
    userEmail: testUserEmail,
  };

  const saleResult = executeTradeCore(spreadsheet, saleArgs);
  console.log("Sale Result: " + JSON.stringify(saleResult));

  if (saleResult.ok) {
    console.log(
      "✅ SALE test PASSED. A new transaction should be in the Ledger.",
    );
  } else {
    console.log("❌ SALE test FAILED: " + saleResult.message);
  }

  console.log("\n--- Live Test Finished ---");
  console.log(
    "Please check your 'Ledger' and 'Markets' sheets to verify the new rows.",
  );
}

/**
 * A test function to simulate a GET request for the /balance command.
 * This version securely reads the API token from Script Properties.
 */
function testDoGetBalance() {
  // --- 1. Configure the Test Event ---
  // This object simulates the 'e' parameter that doGet receives from a real web request.
  const eventObject = {
    parameter: {
      // SECURE: Reads the token from the global constant, which is loaded from Script Properties.
      token: API_TOKEN,

      // The action you want to test.
      action: "getBalance",

      // The Discord handle or username of the user you want to look up.
      // Change this value to test different users from your 'Users' sheet.
      discordHandle: "Ricardo Vieira",
    },
  };

  // --- 2. Execute the Function and Log the Output ---
  const result = doGet(eventObject).getContent();
  Logger.log(result);
}

function testDoGetTradePreview() {
  // --- 1. Configure the Test Event ---
  // This object simulates the 'e' parameter that doGet receives from a real web request.
  const eventObject = {
    parameter: {
      // SECURE: Reads the token from the global constant, which is loaded from Script Properties.
      token: API_TOKEN,

      // The action you want to test.
      action: "getTradePreview",

      // The Discord handle or username of the user you want to look up.
      // Change this value to test different users from your 'Users' sheet.
      discordHandle: "Ricardo Vieira",

      marketId: 1,
      shareType: "Yes",
      quantity: 15,
    },
  };

  // --- 2. Execute the Function and Log the Output ---
  const result = doGet(eventObject).getContent();
  Logger.log(result);
}
