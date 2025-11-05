/**
 * @OnlyCurrentDoc
 */

function createMarketDetailSheetUI() {
  const ui = SpreadsheetApp.getUi();
  const result = ui.prompt(
    "Generate Market Details",
    "Enter Market ID:",
    ui.ButtonSet.OK_CANCEL,
  );

  const button = result.getSelectedButton();
  const text = result.getResponseText();

  if (button == ui.Button.OK) {
    const marketId = parseInt(text, 10);
    if (isNaN(marketId) || marketId <= 0) {
      ui.alert(
        "Invalid Market ID",
        "Please enter a valid number.",
        ui.ButtonSet.OK,
      );
      return;
    }
    generateMarketDetailSheet(marketId);
  }
}

function generateMarketDetailSheet(marketId) {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const ledgerSheet = spreadsheet.getSheetByName("Ledger");
  const usersSheet = spreadsheet.getSheetByName("Users");
  const marketsSheet = spreadsheet.getSheetByName("Markets");

  if (!ledgerSheet || !usersSheet || !marketsSheet) {
    SpreadsheetApp.getUi().alert(
      "Required sheets (Ledger, Users, or Markets) not found.",
    );
    return;
  }

  // --- Create a map of User ID to Username ---
  const userMap = {};
  if (usersSheet) {
    const usersData = usersSheet.getDataRange().getValues();
    for (let i = 1; i < usersData.length; i++) {
      const userId = usersData[i][0];
      const username = usersData[i][1];
      if (userId && username) {
        userMap[userId] = username;
      }
    }
  }

  // --- Get market-specific info (Question and Liquidity) ---
  let marketQuestion = `Market ID ${marketId}`; // Default title
  let b = 100; // Default liquidity parameter
  let creationDate = null;
  let closeDate = null;
  if (marketsSheet) {
    const marketsData = marketsSheet.getDataRange().getValues();
    const marketInfoRow = marketsData
      .slice(1)
      .find((row) => row[0] == marketId);
    if (marketInfoRow) {
      if (marketInfoRow[1]) {
        // Assuming Question is in Column B
        marketQuestion = marketInfoRow[1];
      }
      creationDate = marketInfoRow[2] ? new Date(marketInfoRow[2]) : null; // Column C
      closeDate = marketInfoRow[3] ? new Date(marketInfoRow[3]) : null; // Column D
      const marketLiquidity = marketInfoRow[6]; // Assuming Liquidity is in Column G
      if (typeof marketLiquidity === "number" && !isNaN(marketLiquidity)) {
        b = marketLiquidity;
      }
    }
  }

  const data = ledgerSheet.getDataRange().getValues();
  const marketTransactions = data.slice(1).filter((row) => row[3] == marketId);

  if (marketTransactions.length === 0) {
    SpreadsheetApp.getUi().alert(
      `No transactions found for Market ID ${marketId}.`,
    );
    return;
  }

  // Create or clear the market detail sheet
  const sheetName = `Market_${marketId}_details`;
  let detailSheet = spreadsheet.getSheetByName(sheetName);
  if (detailSheet) {
    detailSheet.clear();
    const charts = detailSheet.getCharts();
    charts.forEach((chart) => detailSheet.removeChart(chart));
  } else {
    detailSheet = spreadsheet.insertSheet(sheetName);
  }
  spreadsheet.setActiveSheet(detailSheet);

  // --- 1. User Positions ---
  const positions = {};
  marketTransactions.forEach((row) => {
    const userId = row[2];
    const shareType = row[5];
    const quantity = row[6];

    if (!positions[userId]) {
      positions[userId] = { yesShares: 0, noShares: 0 };
    }

    if (shareType === "Yes") {
      positions[userId].yesShares += quantity;
    } else if (shareType === "No") {
      positions[userId].noShares += quantity;
    }
  });

  const positionData = [["User ID", "Username", "Yes Shares", "No Shares"]];
  for (const userId in positions) {
    positionData.push([
      userId,
      userMap[userId] || "N/A", // Get username from map
      positions[userId].yesShares,
      positions[userId].noShares,
    ]);
  }

  detailSheet.getRange("A1").setValue("User Positions");
  detailSheet.getRange("A1").setFontWeight("bold");
  detailSheet.getRange(2, 1, positionData.length, 4).setValues(positionData);
  detailSheet.autoResizeColumns(1, 4);

  // --- 2. Price History (LMSR) ---
  let q_y = 0;
  let q_n = 0;

  const priceHistoryData = [
    [
      "Timestamp",
      "User",
      "Trade",
      "Yes Price (0-100)",
      "No Price (0-100)",
      "Total Yes Shares",
      "Total No Shares",
    ],
  ];

  // Initial state before any trades
  // Initial state at market creation
  const initialPrice = 50;
  if (creationDate) {
    priceHistoryData.push([
      creationDate,
      "N/A",
      "Initial State",
      initialPrice,
      100 - initialPrice,
      0,
      0,
    ]);
  } else if (marketTransactions.length > 0) {
    // Fallback if no creation date is found
    const firstTimestamp = new Date(marketTransactions[0][1]);
    firstTimestamp.setSeconds(firstTimestamp.getSeconds() - 1);
    priceHistoryData.push([
      firstTimestamp,
      "N/A",
      "Initial State",
      initialPrice,
      100 - initialPrice,
      0,
      0,
    ]);
  }

  marketTransactions.forEach((row) => {
    const timestamp = row[1];
    const userId = row[2];
    const shareType = row[5];
    const quantity = row[6];
    const username = userMap[userId] || `ID: ${userId}`;
    const tradeDescription = `${quantity > 0 ? "Bought" : "Sold"} ${Math.abs(quantity)} ${shareType}`;

    if (shareType === "Yes") {
      q_y += quantity;
    } else if (shareType === "No") {
      q_n += quantity;
    }

    const priceYes = Math.round(
      (100 * Math.exp(q_y / b)) / (Math.exp(q_y / b) + Math.exp(q_n / b)),
    );
    const priceNo = 100 - priceYes;

    priceHistoryData.push([
      timestamp,
      username,
      tradeDescription,
      priceYes,
      priceNo,
      q_y,
      q_n,
    ]);
  });

  const priceHistoryHeaderRow = positionData.length + 3;
  detailSheet.getRange(priceHistoryHeaderRow, 1).setValue("Price History");
  detailSheet.getRange(priceHistoryHeaderRow, 1).setFontWeight("bold");
  detailSheet
    .getRange(priceHistoryHeaderRow + 1, 1, priceHistoryData.length, 7)
    .setValues(priceHistoryData);
  detailSheet.autoResizeColumns(1, 7);

  // --- 3. Prepare Daily Data for Chart ---
  const dailyClosingPrices = new Map();
  priceHistoryData.slice(1).forEach((row) => {
    const timestamp = new Date(row[0]);
    const dateKey = timestamp.toISOString().split("T")[0];
    // Store the date object, yes price, and no price. Overwrites earlier entries for the same day.
    dailyClosingPrices.set(dateKey, [new Date(dateKey), row[3], row[4]]);
  });

  const dailyChartData = [["Date", "Yes Price", "No Price"]];
  if (priceHistoryData.length > 1) {
    const firstDate = new Date(priceHistoryData[1][0]);
    firstDate.setHours(0, 0, 0, 0);

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    let endDate = today;
    if (closeDate) {
      const prospectiveEndDate = new Date(closeDate);
      if (prospectiveEndDate < today) {
        endDate = prospectiveEndDate;
      }
    }
    endDate.setHours(0, 0, 0, 0);

    let last_yes_price = 50;
    let last_no_price = 50;

    for (
      let d = new Date(firstDate);
      d <= endDate;
      d.setDate(d.getDate() + 1)
    ) {
      const dateKey = d.toISOString().split("T")[0];
      if (dailyClosingPrices.has(dateKey)) {
        const row = dailyClosingPrices.get(dateKey);
        last_yes_price = row[1];
        last_no_price = row[2];
        dailyChartData.push(row);
      } else {
        dailyChartData.push([new Date(d), last_yes_price, last_no_price]);
      }
    }
  }

  // Place daily data on the sheet for the chart to use (e.g., in column J)
  const dailyChartDataRange = detailSheet.getRange(
    priceHistoryHeaderRow + 1,
    27, // Column AA (27th column)
    dailyChartData.length,
    3,
  );
  dailyChartDataRange.setValues(dailyChartData);

  // Apply specific formats to the columns
  dailyChartDataRange
    .offset(0, 0, dailyChartData.length, 1)
    .setNumberFormat("yyyy-mm-dd"); // Date column
  dailyChartDataRange
    .offset(0, 1, dailyChartData.length, 2)
    .setNumberFormat("0"); // Price columns

  // --- 4. Create Price Chart ---
  // Calculate padding for the right side of the chart to prevent label clipping.
  // We'll add 4% of the total date range to the end.
  const chartBuilder = detailSheet
    .newChart()
    .setChartType(Charts.ChartType.AREA)
    .addRange(dailyChartDataRange.offset(0, 0, dailyChartData.length, 1))
    .addRange(dailyChartDataRange.offset(0, 1, dailyChartData.length, 1))
    .addRange(dailyChartDataRange.offset(0, 2, dailyChartData.length, 1))
    .setPosition(2, 9, 0, 0) // Positioning the chart to the right of the tables
    .setOption("title", `Daily Closing Price: ${marketQuestion}`)
    .setOption("hAxis.title", "Date")
    .setOption("vAxis.format", "percent")
    .setOption("isStacked", "percent")
    .setOption("area", { isStepped: true })
    .setOption("colors", ["#4285F4", "#EA4335"])
    .setOption("legend", { position: "top" })
    .setOption("useFirstColumnAsDomain", true)
    .setOption("series", {
      0: { labelInLegend: "Yes Price" },
      1: { labelInLegend: "No Price" },
    });

  detailSheet.insertChart(chartBuilder.build());

  // --- 5. Add Note ---
  const lastContentRow = priceHistoryHeaderRow + priceHistoryData.length;
  const noteRow = lastContentRow + 2; // Add some space below the table
  detailSheet
    .getRange(noteRow, 1)
    .setValue(
      "Note: This is not updated in real time, you must go Market Analysis > Generate Market Analysis > Insert Market Id",
    );

  SpreadsheetApp.getUi().alert(
    `Successfully generated details for Market ID ${marketId}.`,
  );
}
