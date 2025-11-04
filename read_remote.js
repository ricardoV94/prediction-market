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

  if (action === "getTradePreview") {
    return handleGetTradePreview(e.parameter);
  }

  return ContentService.createTextOutput(
    JSON.stringify({ ok: false, error: "Invalid action specified." }),
  ).setMimeType(ContentService.MimeType.JSON);
}

function _findUser(usersSheet, discordHandle) {
  const usersData = usersSheet.getDataRange().getValues();
  const usersHeaders = usersData.shift();
  const handleIndex = usersHeaders.indexOf("Discord handle");
  const usernameIndex = usersHeaders.indexOf("Username");

  const userRow =
    usersData.find(
      (row) => row[handleIndex] && row[handleIndex] === discordHandle,
    ) ||
    usersData.find(
      (row) => row[usernameIndex] && row[usernameIndex] === discordHandle,
    );

  if (!userRow) return null;

  const user = {};
  usersHeaders.forEach((header, i) => {
    // Sanitize header to be a valid key
    const key = header.replace(/\s+/g, "");
    user[key] = userRow[i];
  });
  return {
    userId: user["UserID"],
    balance: user["CurrentCashBalance"],
  };
}

function _findMarket(marketsSheet, marketId) {
  const marketsData = marketsSheet.getDataRange().getValues();
  const marketsHeaders = marketsData.shift();
  const marketIdIndex = 0; // The first column is always "Market ID"

  const marketRow = marketsData.find(
    (row) =>
      row[marketIdIndex] &&
      row[marketIdIndex].toString() === marketId.toString(),
  );

  if (!marketRow) return null;

  const market = {};
  marketsHeaders.forEach((header, i) => {
    const key = header.replace(/\s+/g, ""); // Sanitize header
    market[key] = marketRow[i];
  });

  return {
    question: market["Question"],
    long_description: market["DetailedCriteria"],
    status: market["Status"],
    liquidity: market["Liquidity"],
    pYes: market["YesPrice"],
    yesShares: market["YesShares"],
    noShares: market["NoShares"],
    volume: market["Volume"],
  };
}

function _getUserHoldings(positionsSheet, userId, marketId) {
  const positionsData = positionsSheet.getDataRange().getValues();
  const positionsHeaders = positionsData.shift();
  const posUserIdIndex = positionsHeaders.indexOf("User Id");
  const marketIdIndex = positionsHeaders.indexOf("Market Id");
  const shareTypeIndex = positionsHeaders.indexOf("Share Type");
  const quantityIndex = positionsHeaders.indexOf("SUM of Quantity");

  const holdings = { userYes: 0, userNo: 0 };

  positionsData.forEach((row) => {
    if (
      row[posUserIdIndex] &&
      row[posUserIdIndex].toString() === userId.toString() &&
      row[marketIdIndex] &&
      row[marketIdIndex].toString() === marketId.toString()
    ) {
      const shareType = row[shareTypeIndex];
      const quantity = row[quantityIndex];
      if (shareType === "Yes") {
        holdings.userYes = quantity;
      } else if (shareType === "No") {
        holdings.userNo = quantity;
      }
    }
  });
  return holdings;
}

function handleGetTradePreview(params) {
  const { discordHandle, marketId, shareType, quantity: quantityStr } = params;
  const quantity = Number(quantityStr);

  if (!discordHandle || !marketId || !shareType || isNaN(quantity)) {
    return ContentService.createTextOutput(
      JSON.stringify({
        ok: false,
        error:
          "Missing required parameters: discordHandle, marketId, shareType, quantity.",
      }),
    ).setMimeType(ContentService.MimeType.JSON);
  }

  try {
    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
    const usersSheet = spreadsheet.getSheetByName("Users");
    const marketsSheet = spreadsheet.getSheetByName("Markets");
    const positionsSheet = spreadsheet.getSheetByName("Positions");

    // 1. Get User and Market Data
    const user = _findUser(usersSheet, discordHandle);
    if (!user) {
      return ContentService.createTextOutput(
        JSON.stringify({
          ok: false,
          error: `User '${discordHandle}' not found.`,
        }),
      ).setMimeType(ContentService.MimeType.JSON);
    }

    const market = _findMarket(marketsSheet, marketId);
    if (!market) {
      return ContentService.createTextOutput(
        JSON.stringify({
          ok: false,
          error: `Market with ID '${marketId}' not found.`,
        }),
      ).setMimeType(ContentService.MimeType.JSON);
    }

    const holdings = _getUserHoldings(positionsSheet, user.userId, marketId);

    // 2. Simulate Trade by calling the pure function
    // This function is globally available from market_func.js
    const simulation = simulateTrade(
      market.liquidity,
      market.yesShares,
      market.noShares,
      shareType,
      quantity,
    );

    // 3. Format Response
    const preview = {
      user: {
        id: user.userId,
        discordHandle: discordHandle,
        balance: user.balance,
      },
      market: {
        id: marketId,
        description: market.question,
        long_description: market.long_description,
        status: market.status,
        liquidity: market.liquidity,
        pYes: market.pYes,
        pNo: 100 - market.pYes,
        yesShares: market.yesShares,
        noShares: market.noShares,
        volume: market.volume,
      },
      userHoldings: {
        yesShares: holdings.userYes,
        noShares: holdings.userNo,
      },
      trade: {
        shareType: shareType,
        quantity: quantity,
        cost: simulation.cost,
      },
      simulation: {
        newPYes: simulation.newYesPrice,
        newPNo: simulation.newNoPrice,
        newBalance: user.balance - simulation.cost,
      },
    };

    return ContentService.createTextOutput(
      JSON.stringify({ ok: true, data: preview }),
    ).setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    console.error(`Error in handleGetTradePreview: ${err.stack}`);
    return ContentService.createTextOutput(
      JSON.stringify({ ok: false, error: "A server-side error occurred." }),
    ).setMimeType(ContentService.MimeType.JSON);
  }
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
    const user = _findUser(usersSheet, discordHandle);
    if (!user) {
      return ContentService.createTextOutput(
        JSON.stringify({
          ok: false,
          error: `User '${discordHandle}' not found.`,
        }),
      ).setMimeType(ContentService.MimeType.JSON);
    }

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
    const posUserIdIndex = positionsHeaders.indexOf("User Id");
    const marketIdIndex = positionsHeaders.indexOf("Market Id");
    const shareTypeIndex = positionsHeaders.indexOf("Share Type");
    const quantityIndex = positionsHeaders.indexOf("SUM of Quantity");
    const totalCostIndex = positionsHeaders.indexOf("SUM of TotalCost");

    const userShares = {};
    positionsData.forEach((row) => {
      if (
        row[posUserIdIndex] &&
        row[posUserIdIndex].toString() === user.userId.toString() &&
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
      userId: user.userId,
      balance: user.balance,
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
    console.error(`Error in handleGetBalance: ${err.stack}`);
    return ContentService.createTextOutput(
      JSON.stringify({ ok: false, error: "A server-side error occurred." }),
    ).setMimeType(ContentService.MimeType.JSON);
  }
}
