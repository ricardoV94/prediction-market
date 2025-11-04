function getUserPositions(spreadsheet, marketId) {
  const ledgerSheet = spreadsheet.getSheetByName("Ledger");
  const data = ledgerSheet.getDataRange().getValues();
  const positions = {};

  // Skip header row (index 0)
  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    // const transactionMarketId = row[3]; // Column D (Market Id)

    // Skip resolution transactions when calculating positions
    if (row[3] == marketId) {
      const userId = row[2]; // Column C (User Id)
      // const shareType = row[5]; // Column F (Share Type)
      // const quantity = row[6]; // Column G (Quantity)

      if (!positions[userId]) {
        positions[userId] = {
          yesShares: 0,
          noShares: 0,
        };
      }

      if (row[5] === "Yes") {
        positions[userId].yesShares += row[6];
      } else {
        positions[userId].noShares += row[6];
      }
    }
  }

  return positions;
}

function getUserPositionForMarket(spreadsheet, userId, marketId) {
  const positions = getUserPositions(spreadsheet, marketId);
  const pos = positions[userId];
  return pos || { yesShares: 0, noShares: 0 };
}

function getCurrentUserBalance(spreadsheet, userId) {
  const balances = getCurrentUserBalancesBatch(spreadsheet, [userId]);
  return balances.get(userId) || 0;
}

function getCurrentUserBalancesBatch(spreadsheet, userIds) {
  const ledgerSheet = spreadsheet.getSheetByName("Ledger");
  const data = ledgerSheet.getDataRange().getValues();
  const balances = new Map();

  // Initialize all users with default balance of 10k
  userIds.forEach((userId) => balances.set(userId, 10000));

  // Work backwards through ledger to find most recent balance for each user
  const foundUsers = new Set();
  let nMissingUsers = userIds.length;
  for (let i = data.length - 1; i >= 1; i--) {
    const row = data[i];
    const userId = row[2]; // Column C (User Id)

    if (userIds.includes(userId) && !foundUsers.has(userId)) {
      balances.set(userId, row[9]); // Column J (newBalance)
      foundUsers.add(userId);
      nMissingUsers--;
    }

    if (nMissingUsers === 0) {
      // Found the last balance of all users
      break;
    }
  }

  return balances;
}

function getMarketData(spreadsheet, marketId) {
  const sheet = spreadsheet.getSheetByName("Markets");
  if (!sheet) return null;
  const values = sheet.getDataRange().getValues(); // assumes header row
  for (let i = 1; i < values.length; i++) {
    const row = values[i];
    if (String(row[0]) === String(marketId)) {
      return {
        status: row[5], // Column F (Status)
        liquidity: row[6], // Column G (Liquidity)
        yesShares: Number(row[8] || 0), // Column I (Yes Shares)
        noShares: Number(row[9] || 0), // Column J (No Shares)
      };
    }
  }
  return null;
}

function computeCost(liquidity, yesShares, noShares, shareType, quantity) {
  // Compute LMSR cost for a trade

  if (liquidity <= 0) return NaN; // Avoid division by zero

  // Current score
  const currentScore = Math.log(
    Math.exp(yesShares / liquidity) + Math.exp(noShares / liquidity),
  );

  // New shares after trade
  const newYes = shareType === "Yes" ? yesShares + quantity : yesShares;
  const newNo = shareType === "No" ? noShares + quantity : noShares;

  // New score
  const newScore = Math.log(
    Math.exp(newYes / liquidity) + Math.exp(newNo / liquidity),
  );

  // Cost = (newScore - currentScore) * liquidity
  const cost = (newScore - currentScore) * liquidity * 100;

  // Rounded to 2 decimals
  return Math.round(cost * 100) / 100;
}

function recordTransactionsBatch(spreadsheet, transactions) {
  /**
   * Optimized batch transaction recording function
   * Records multiple transactions in a single API call while tracking balance changes
   */
  if (!transactions || transactions.length === 0) return;

  const transactionsSheet = spreadsheet.getSheetByName("Ledger");

  // Get current state
  const lastRow = transactionsSheet.getLastRow();
  let nextId = 1;
  if (lastRow > 1) {
    const prevId = transactionsSheet.getRange(lastRow, 1).getValue();
    nextId =
      typeof prevId === "number" && !isNaN(prevId) ? prevId + 1 : lastRow;
  }

  // Track user balances across transactions
  const userBalanceTracker = new Map();
  const uniqueUserIds = [...new Set(transactions.map((t) => t.userId))];
  const initialBalances = getCurrentUserBalancesBatch(
    spreadsheet,
    uniqueUserIds,
  );
  for (const [userId, balance] of initialBalances)
    userBalanceTracker.set(userId, balance);

  const batchData = [];

  for (let i = 0; i < transactions.length; i++) {
    const t = transactions[i];
    const currentBalance = userBalanceTracker.get(t.userId);
    const newBalance = currentBalance - t.totalCost;

    userBalanceTracker.set(t.userId, newBalance);

    const row = [
      nextId + i,
      t.timestamp,
      t.userId,
      t.marketId,
      t.userEmail,
      t.shareType,
      t.quantity,
      t.totalCost,
      currentBalance,
      newBalance,
      t.transactionType,
    ];
    batchData.push(row);
  }

  // Write to sheet
  if (batchData.length === 1) {
    transactionsSheet.appendRow(batchData[0]);
  } else {
    const range = transactionsSheet.getRange(
      lastRow + 1,
      1,
      batchData.length,
      batchData[0].length,
    );
    range.setValues(batchData);
  }
}

function executeTradeCore(
  spreadsheet,
  {
    userId,
    marketId,
    marketStatus, // "Open" required
    shareType, // "Yes" or "No"
    quantity, // positive buy, negative sell
    totalCost, // signed total cost for the trade (positive cost reduces balance)
    userEmail, // info to record for audit/logging
  },
) {
  // Core trade executor: no UI cell reads/writes. Safe to call from bot/webhook.

  // Validate basic required inputs
  if (!userId) {
    return { ok: false, message: "Please select User" };
  }
  if (!marketId) {
    return { ok: false, message: "Please select Market" };
  }
  if (marketStatus !== "Open") {
    return { ok: false, message: "Selected market is not open" };
  }
  if (shareType !== "Yes" && shareType !== "No") {
    return { ok: false, message: "Please select valid Share type" };
  }

  if (typeof quantity !== "number" || isNaN(quantity)) {
    return { ok: false, message: "Please select a valid number of shares" };
  }
  if (quantity === 0) {
    return { ok: true, message: "Zero shares traded. Nothing to do" };
  }

  if (typeof totalCost !== "number" || !isFinite(totalCost)) {
    return { ok: false, message: "Cost must be a finite number" };
  }

  // Validate selling does not exceed owned shares
  if (quantity < 0) {
    const pos = getUserPositionForMarket(spreadsheet, userId, marketId);
    const relevantBalanceShares =
      shareType === "Yes" ? pos.yesShares : pos.noShares;

    if (-quantity > relevantBalanceShares) {
      return {
        ok: false,
        message: "Cannot sell more shares than owned " + relevantBalanceShares,
      };
    }
  }

  // Check user balance for positive cost
  const balance = getCurrentUserBalance(spreadsheet, userId);
  if (totalCost > 0 && totalCost > balance) {
    return {
      ok: false,
      message: "Insufficient balance to complete this trade",
    };
  }

  // Record transaction
  const transactions = [
    {
      timestamp: new Date(),
      userId,
      userEmail,
      marketId,
      shareType,
      quantity,
      totalCost,
      transactionType: "user trade",
    },
  ];

  recordTransactionsBatch(spreadsheet, transactions);
  return { ok: true, message: "Trade executed successfully!" };
}

function resolveMarket(spreadsheet, marketId, resolution, userEmail) {
  SpreadsheetApp.getUi().alert("Resolving market " + marketId);
  const userPositions = getUserPositions(spreadsheet, marketId);

  const transactions = [];
  const timestamp = new Date();

  // Prepare all transactions for batch processing
  for (const [userId, position] of Object.entries(userPositions)) {
    if (position.yesShares > 0) {
      const redemptionValue =
        resolution === "Resolved Yes" ? position.yesShares * 100 : 0;

      transactions.push({
        timestamp: timestamp,
        userId: parseInt(userId),
        userEmail: userEmail,
        marketId: marketId,
        shareType: "Yes",
        quantity: -position.yesShares,
        totalCost: -redemptionValue, // Negative because it's a payout
        transactionType: resolution.toLowerCase(),
      });
    }

    if (position.noShares > 0) {
      const redemptionValue =
        resolution === "Resolved No" ? position.noShares * 100 : 0;

      transactions.push({
        timestamp: timestamp,
        userId: parseInt(userId),
        userEmail: userEmail,
        marketId: marketId,
        shareType: "No",
        quantity: -position.noShares,
        totalCost: -redemptionValue, // Negative because it's a payout
        transactionType: resolution.toLowerCase(),
      });
    }
  }

  // Record all transactions in a single batch operation
  if (transactions.length > 0) {
    recordTransactionsBatch(spreadsheet, transactions);
  }
}

function unresolveMarket(spreadsheet, marketId, newStatus, userEmail) {
  const ledgerSheet = spreadsheet.getSheetByName("Ledger");
  const data = ledgerSheet.getDataRange().getValues();

  // Work backwards through transactions to find the most recent resolution for each user+shareType
  const processedKeys = new Set();
  const resolutionTransactions = [];

  // Start from the last row and work backwards (skip header row)
  for (let i = data.length - 1; i >= 1; i--) {
    const row = data[i];
    const transactionMarketId = row[3]; // Column D (Market Id)
    const transactionType = row[10]; // Column K (Transaction Type)

    if (
      transactionMarketId == marketId &&
      (transactionType === "resolved yes" || transactionType === "resolved no")
    ) {
      const userId = row[2];
      const shareType = row[5];
      const key = `${userId}-${shareType}`;

      // Skip if we've already found a more recent transaction for this user+shareType
      if (processedKeys.has(key)) {
        continue;
      }

      // Mark this combination as processed
      processedKeys.add(key);

      // Store the transaction to reverse
      resolutionTransactions.push({
        userId: userId,
        shareType: shareType,
        quantity: row[6], // This was negative during resolution
        totalCost: row[7], // This was negative during resolution (payout)
        transactionType: transactionType,
      });
    }
  }

  // Prepare batch transactions for reversal
  const transactions = [];
  const timestamp = new Date();

  for (const transaction of resolutionTransactions) {
    transactions.push({
      timestamp: timestamp,
      userId: transaction.userId,
      userEmail: userEmail,
      marketId: marketId,
      shareType: transaction.shareType,
      quantity: -transaction.quantity, // Restore shares (was negative, now positive)
      totalCost: -transaction.totalCost, // Remove payout (was negative, now positive to deduct)
      transactionType: "unresolve",
    });
  }

  // Record all reversal transactions in a single batch operation
  if (transactions.length > 0) {
    recordTransactionsBatch(spreadsheet, transactions);
  }
}
