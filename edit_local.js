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
  sheet.getRangeList(["A3", "A7", "A11", "B17"]).clearContent();

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
  // UI wrapper: reads inputs from the Trade sheet, delegates to core, updates UI status.
  spreadsheet.getRange("B17").clearContent();

  const userId = spreadsheet.getRange("B3").getValue();
  const marketId = spreadsheet.getRange("B7").getValue();
  const marketStatus = spreadsheet.getRange("D7").getValue();
  const shareType = spreadsheet.getRange("A11").getValue();
  const quantity = spreadsheet.getRange("A14").getValue();
  const totalCost = spreadsheet.getRange("B14").getValue();

  // Check if totalCost matches expected totalCost
  // It may have changed if someone did a transaction just now
  const marketData = getMarketData(spreadsheet, marketId);
  if (!marketData) {
    setStatusMessage(
      spreadsheet,
      "Could not get Market Data for validation",
      true,
    );
    return;
  }

  const expectedCost = computeCost(
    marketData.liquidity,
    marketData.yesShares,
    marketData.noShares,
    shareType,
    quantity,
  );
  if (totalCost != expectedCost) {
    // Allow 1% error for float point shenanigans
    if (Math.abs(totalCost - expectedCost) / expectedCost > 0.01) {
      setStatusMessage(
        spreadsheet,
        `total cost ${totalCost} does not match expected ${expectedCost}`,
        true,
      );
      return;
    }
  }

  const result = executeTradeCore(spreadsheet, {
    userId,
    marketId,
    marketStatus,
    shareType,
    quantity,
    totalCost,
    userEmail,
  });

  if (result.ok) {
    // Reset quantity in the UI to match previous behavior
    spreadsheet.getRange("A14").setValue(0);
    setStatusMessage(spreadsheet, result.message, false);
  } else {
    setStatusMessage(spreadsheet, result.message || "Trade failed", true);
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
