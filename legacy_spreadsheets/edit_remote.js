function jsonResponse(obj, statusCode) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(
    ContentService.MimeType.JSON,
  );
}

function doPost(e) {
  try {
    const props = PropertiesService.getScriptProperties();
    const expected = props.getProperty("API_TOKEN"); // Set via Project Settings
    const params = e.parameter || {};
    const body =
      e.postData && e.postData.contents ? JSON.parse(e.postData.contents) : {};

    const token = params.token || body.token;
    if (!expected || token !== expected) {
      return jsonResponse({ ok: false, error: "unauthorized" });
    }

    const spreadsheet = SpreadsheetApp.getActive();

    const userId = body.userId ?? params.userId;
    const marketId = body.marketId ?? params.marketId;
    const shareType = body.shareType ?? params.shareType; // "Yes" or "No"
    const quantityRaw = body.quantity ?? params.quantity;
    const userEmail = body.userEmail ?? params.userEmail ?? "external";

    // Validate required inputs
    if (!userId || isNaN(Number(userId))) {
      return jsonResponse({
        ok: false,
        error: "Invalid or missing userId: must be a number",
      });
    }
    if (!marketId || isNaN(Number(marketId))) {
      return jsonResponse({
        ok: false,
        error: "Invalid or missing marketId: must be a number",
      });
    }
    if (shareType !== "Yes" && shareType !== "No") {
      return jsonResponse({
        ok: false,
        error: "Invalid shareType: must be 'Yes' or 'No'",
      });
    }
    if (quantityRaw === undefined || isNaN(Number(quantityRaw))) {
      return jsonResponse({
        ok: false,
        error: "Invalid or missing quantity: must be a number",
      });
    }

    const quantity = Number(quantityRaw);

    // Get market data
    const marketData = getMarketData(spreadsheet, marketId);
    if (!marketData) {
      return jsonResponse({
        ok: false,
        error: "Market not found or invalid marketId",
      });
    }

    const totalCost = computeCost(
      marketData.liquidity,
      marketData.yesShares,
      marketData.noShares,
      shareType,
      quantity,
    );

    const result = executeTradeCore(spreadsheet, {
      userId: Number(userId),
      marketId: Number(marketId),
      marketStatus: marketData.status,
      shareType,
      quantity,
      totalCost,
      userEmail,
    });

    const httpCode = result.ok ? 200 : 400;
    return jsonResponse(result, httpCode);
  } catch (err) {
    return jsonResponse({
      ok: false,
      error: String((err && err.message) || err),
    });
  }
}
