function onEdit(e) {
  const spreadsheet = e.source;
  const sheet = spreadsheet.getActiveSheet();

  // Handle trade events
  if (
    e.value === "TRUE" &&
    e.range.getColumn() === 1 &&
    sheet.getName().startsWith("Trade")
  ) {
    const eRangeA1Notation = e.range.getA1Notation();
    // const sheetNameBang = sheet.getName() + "!";
    // if (spreadsheet.getRangeByName(sheetNameBang + "TradeExecuteTrade").getA1Notation() === eRangeA1Notation){
    if (eRangeA1Notation == "A17") {
      e.range.setValue("FALSE");
      executeTrade(spreadsheet, sheet, e.user.getEmail());
    }
    // else if (spreadsheet.getRangeByName(sheetNameBang + "TradeClearForm").getA1Notation() === eRangeA1Notation){
    else if (eRangeA1Notation == "A20") {
      e.range.setValue("FALSE");
      clearTradeForm(spreadsheet, sheet);
    }
  }

  // Handle trade execution on Trade sheets
  // Column F (Status)
  else if (e.range.getColumn() === 6 && sheet.getName() === "Markets") {
    handleMarketStatusChange(
      spreadsheet,
      sheet,
      e.range.getRow(),
      e.value,
      e.oldValue,
      e.user.getEmail(),
    );
  }
}

function clearTradeForm(spreadsheet, sheet) {
  // const sheetNameBang = sheet.getName() + '!'

  // Clear content ranges
  sheet
    .getRangeList([
      "A3",
      "A7",
      "A11",
      "B17",
    ])
    .clearContent();

  // Set quantity to zero
  spreadsheet.getRange("A14").setValue(0);
  // spreadsheet.getRangeByName(sheetNameBang + 'TradeQuantity').setValue(0);
}

function setStatusMessage(spreadsheet, message, isError = false) {
  // spreadsheet.getRangeByName(sheetNameBang + 'TradeMessageStatus').getA1Notation(),
  const statusCell = spreadsheet.getRange("B17");
  statusCell.setValue(message);
  if (isError) {
    statusCell.setFontColor("#ff0000"); // Red for errors
  } else {
    statusCell.setFontColor("#008000"); // Green for success
  }
}

function executeTrade(spreadsheet, sheet, userEmail) {
  spreadsheet.getRange("B17").clearContent();

  const userId = spreadsheet.getRange("B3").getValue();
  const marketId = spreadsheet.getRange("B7").getValue();
  const marketStatus = spreadsheet.getRange("D7").getValue();
  const shareType = spreadsheet.getRange("A11").getValue();
  const quantity = spreadsheet.getRange("A14").getValue();
  const totalCost = spreadsheet.getRange("B14").getValue();
  const balance = spreadsheet.getRange("C3").getValue();

  // Validation
  if (!userId) {
    setStatusMessage(spreadsheet, "Please select User", true);
    return;
  }
  if (!marketId) {
    setStatusMessage(spreadsheet, "Please select Market", true);
    return;
  }
  if (marketStatus !== "Open") {
    setStatusMessage(spreadsheet, "Selected market is not open", true);
    return;
  }
  if (shareType !== "Yes" && shareType !== "No") {
    setStatusMessage(spreadsheet, "Please select valid Share type", true);
    return;
  }

  if (typeof quantity !== "number" || isNaN(quantity)) {
    setStatusMessage(
      spreadsheet,
      "Please select a valid number of shares",
      true,
    );
    return;
  }
  if (quantity == 0) {
    setStatusMessage(spreadsheet, "Zero shares traded. Nothing to do", false);
    return;
  } else if (quantity < 0) {
    // const relevantBalanceShares = (shareType === 'Yes') ?
    //   spreadsheet.getRangeByName(sheetNameBang + 'TradeUserYesShares').getValue()
    //   : spreadsheet.getRangeByName(sheetNameBang + 'TradeUserNoShares').getValue();
    const relevantBalanceShares =
      shareType === "Yes"
        ? sheet.getRange("I8").getValue()
        : sheet.getRange("J8").getValue();
    if (quantity < -relevantBalanceShares) {
      setStatusMessage(
        spreadsheet,
        "Cannot sell more shares than owned " + relevantBalanceShares,
        true,
      );
      return;
    }
  }
  if (typeof totalCost !== "number" || isNaN(totalCost)) {
    setStatusMessage(spreadsheet, "Cost must be a finite number", true);
    return;
  }
  if (totalCost > 0 && totalCost > balance) {
    setStatusMessage(
      spreadsheet,
      "Insufficient balance to complete this trade",
      true,
    );
    return;
  }

  // setStatusMessage(spreadsheet, 'Wait while executing trade!', false);
  spreadsheet.getRange("A14").setValue(0);

  // Record transaction with all required fields
  const transactions = [
    {
      timestamp: new Date(),
      userId: userId,
      userEmail: userEmail,
      marketId: marketId,
      shareType: shareType,
      quantity: quantity,
      totalCost: totalCost,
      prevBalance: balance,
      transactionType: "user trade",
    },
  ];

  recordTransactionsBatch(spreadsheet, transactions);
  setStatusMessage(spreadsheet, "Trade executed successfully!", false);
}

/**
 * Optimized batch transaction recording function
 * Records multiple transactions in a single API call while tracking balance changes
 */
function recordTransactionsBatch(spreadsheet, transactions) {
  if (!transactions || transactions.length === 0) return;

  const transactionsSheet = spreadsheet.getSheetByName("Ledger");

  // Get current state
  const lastRow = transactionsSheet.getLastRow();
  let nextId = 1;
  if (lastRow > 1) {
    const prevId = transactionsSheet.getRange(lastRow, 1).getValue();
    nextId = (typeof prevId === "number" && !isNaN(prevId)) ? prevId + 1 : lastRow;
  }

  // Track user balances across transactions
  const userBalanceTracker = new Map();
  const uniqueUserIds = [...new Set(transactions.map((t) => t.userId))];
  const initialBalances = getCurrentUserBalancesBatch(spreadsheet, uniqueUserIds);
  for (const [userId, balance] of initialBalances) userBalanceTracker.set(userId, balance);

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
      batchData[0].length
    );
    range.setValues(batchData);
  }
}

function handleMarketStatusChange(
  spreadsheet,
  marketSheet,
  row,
  newStatus,
  oldStatus,
  userEmail,
) {
  const marketId = marketSheet.getRange(row, 1).getValue(); // Column A (Market ID)

  if (!marketId) return;

  // Check if market is being resolved
  if (
    (newStatus === "Resolved Yes" || newStatus === "Resolved No") &&
    oldStatus !== newStatus
  ) {
    if (!(oldStatus === "Open" || oldStatus === "Closed")) {
      // First unresolve market
      unresolveMarket(spreadsheet, marketId, newStatus, userEmail);
    }
    // Resolve unresolved market
    resolveMarket(spreadsheet, marketId, newStatus, userEmail);
  }

  // Check if market is being unresolved
  else if (
    (oldStatus === "Resolved Yes" || oldStatus === "Resolved No") &&
    (newStatus === "Open" || newStatus === "Closed")
  ) {
    unresolveMarket(spreadsheet, marketId, newStatus, userEmail);
  }
}

function resolveMarket(spreadsheet, marketId, resolution, userEmail) {
  SpreadsheetApp.getUi().alert("Resolving market " + marketId);
  const userPositions = calculateUserPositions(spreadsheet, marketId);

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

function calculateUserPositions(spreadsheet, marketId) {
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

function getCurrentUserBalance(spreadsheet, userId) {
  const balances = getCurrentUserBalancesBatch(spreadsheet, [userId]);
  return balances.get(userId) || 0;
}

/**
 * Efficiently get current balances for multiple users in a single pass
 * @param {Spreadsheet} spreadsheet - The spreadsheet object
 * @param {Array} userIds - Array of user IDs to get balances for
 * @returns {Map} Map of userId -> current balance
 */
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
