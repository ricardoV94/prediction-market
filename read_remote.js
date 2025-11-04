// Set these by going to File > Project properties > Script properties
const SCRIPT_PROPERTIES = PropertiesService.getScriptProperties();
const API_TOKEN = SCRIPT_PROPERTIES.getProperty("API_TOKEN");

function doGet(e) {
  // --- 1. Security Check ---
  const token = e.parameter.token;
  if (token !== API_TOKEN) {
    return ContentService.createTextOutput(
      JSON.stringify({ ok: false, error: "Invalid API token." }),
    ).setMimeType(ContentService.MimeType.JSON);
  }

  // --- 2. Action Routing ---
  const action = e.parameter.action;
  if (action === "getBalance") {
    const discordHandle = e.parameter.discordHandle;
    return handleGetBalance(discordHandle);
  }

  return ContentService.createTextOutput(
    JSON.stringify({ ok: false, error: "Invalid action specified." }),
  ).setMimeType(ContentService.MimeType.JSON);
}

function handleGetBalance(discordHandle) {
  if (!discordHandle) {
    return ContentService.createTextOutput(
      JSON.stringify({ ok: false, error: "Discord handle is required." }),
    ).setMimeType(ContentService.MimeType.JSON);
  }

  try {
    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
    const usersSheet = spreadsheet.getSheetByName("Users");
    const positionsSheet = spreadsheet.getSheetByName("Positions");
    const marketsSheet = spreadsheet.getSheetByName("Markets");

    // --- Step 1: Find User ID and Balance ---
    const usersData = usersSheet.getDataRange().getValues();
    const usersHeaders = usersData.shift();
    const handleIndex = usersHeaders.indexOf("Discord handle"),
      usernameIndex = usersHeaders.indexOf("Username"),
      userIdIndex = usersHeaders.indexOf("User ID"),
      balanceIndex = usersHeaders.indexOf("Current Cash Balance");

    let userRow =
      usersData.find((row) => row[handleIndex] === discordHandle) ||
      usersData.find((row) => row[usernameIndex] === discordHandle);

    if (!userRow) {
      return ContentService.createTextOutput(
        JSON.stringify({
          ok: false,
          error: `User '${discordHandle}' not found.`,
        }),
      ).setMimeType(ContentService.MimeType.JSON);
    }
    const userId = userRow[userIdIndex];
    const balance = userRow[balanceIndex];

    // --- Step 2: Get Market Data ---
    const marketsData = marketsSheet.getDataRange().getValues();
    const marketData = {};
    marketsData.forEach((row) => {
      const marketId = row[0];
      if (marketId) {
        marketData[marketId] = {
          question: row[1],
          liquidity: row[6], // Column G: Liquidity
          pYes: row[10], // Column K: p(Yes)
          totalVolume: row[12], // Column M: Total Volume
        };
      }
    });

    // --- Step 3: Get User Holdings and Costs ---
    const positionsData = positionsSheet.getDataRange().getValues();
    const positionsHeaders = positionsData.shift();
    const posUserIdIndex = positionsHeaders.indexOf("User Id"),
      marketIdIndex = positionsHeaders.indexOf("Market Id"),
      shareTypeIndex = positionsHeaders.indexOf("Share Type"),
      quantityIndex = positionsHeaders.indexOf("SUM of Quantity"),
      totalCostIndex = positionsHeaders.indexOf("SUM of TotalCost");

    const userShares = {};
    positionsData.forEach((row) => {
      if (
        row[posUserIdIndex].toString() === userId.toString() &&
        row[marketIdIndex]
      ) {
        const marketId = row[marketIdIndex];
        const shareType = row[shareTypeIndex];
        const quantity = row[quantityIndex];
        const totalCost = row[totalCostIndex];

        if (quantity > 0) {
          if (!userShares[marketId]) userShares[marketId] = {};
          userShares[marketId][shareType] = {
            quantity: quantity,
            cost: totalCost,
          };
        }
      }
    });

    // --- Step 4: Combine and Format Response ---
    const portfolio = {
      balance: balance,
      holdings: [],
    };

    for (const marketId in marketData) {
      const userHolding = userShares[marketId];
      if (userHolding) {
        const yesData = userHolding["Yes"] || { quantity: 0, cost: 0 };
        const noData = userHolding["No"] || { quantity: 0, cost: 0 };

        portfolio.holdings.push({
          marketId: marketId,
          question: marketData[marketId].question,
          pYes: marketData[marketId].pYes,
          volume: marketData[marketId].totalVolume,
          liquidity: marketData[marketId].liquidity,
          userYes: yesData.quantity,
          userNo: noData.quantity,
          userYesCost: yesData.cost,
          userNoCost: noData.cost,
        });
      }
    }

    return ContentService.createTextOutput(
      JSON.stringify({ ok: true, data: portfolio }),
    ).setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    console.error(`Error in handleGetBalance: ${err}`);
    return ContentService.createTextOutput(
      JSON.stringify({ ok: false, error: "A server-side error occurred." }),
    ).setMimeType(ContentService.MimeType.JSON);
  }
}
