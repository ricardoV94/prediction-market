/**
 * @OnlyCurrentDoc
 */
function setDiscordWebhookUrl(url) {
  PropertiesService.getScriptProperties().setProperty(
    "DISCORD_WEBHOOK_URL",
    url,
  );
}

function checkStoredWebhookUrl() {
  const webhookUrl = PropertiesService.getScriptProperties().getProperty(
    "DISCORD_WEBHOOK_URL",
  );
  if (webhookUrl) {
    Logger.log("Stored URL: " + webhookUrl);
  } else {
    Logger.log("No Webhook URL is currently stored in Script Properties.");
  }
}

function formatDate(dateString) {
  if (!dateString) return "";
  const date = new Date(dateString);
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const year = date.getFullYear();
  return `${day}-${month}-${year}`;
}

function updateMarkets(threadId, filterFunction, sortFunction) {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName("Markets");
  if (!sheet) {
    SpreadsheetApp.getUi().alert("Markets sheet not found.");
    return;
  }

  const data = sheet.getDataRange().getValues();
  const markets = data.slice(1).map((row, index) => ({
    row: row,
    rowIndex: index + 2,
  }));

  const filteredMarkets = markets.filter((market) =>
    filterFunction(market.row),
  );

  // Sort the filtered markets
  if (sortFunction) {
    filteredMarkets.sort(sortFunction);
  }

  Logger.log(`Updating ${filteredMarkets.length} / ${markets.length} markets`);

  if (filteredMarkets.length === 0) {
    SpreadsheetApp.getUi().alert(`No markets to report`);
    return;
  }

  const spreadsheetUrl = spreadsheet.getUrl();

  const embeds = filteredMarkets.map((marketInfo) => {
    const market = marketInfo.row;
    const rowIndex = marketInfo.rowIndex;

    const status = market[5];
    const pYes = market[10];
    let color;

    if (status === "Resolved Yes") {
      color = 0x0000ff; // Bright Blue
    } else if (status === "Resolved No") {
      color = 0xff0000; // Bright Red
    } else {
      // Open markets
      if (pYes < 20) {
        color = 0xff0000; // Bright Red
      } else if (pYes < 40) {
        color = 0xffcccb; // Light Red
      } else if (pYes <= 60) {
        color = 0x808080; // Gray
      } else if (pYes <= 80) {
        color = 0xadd8e6; // Light Blue
      } else {
        color = 0x0000ff; // Bright Blue
      }
    }

    const fields = [
      { name: "Status", value: status, inline: true },
      { name: "P(Yes)", value: `${pYes.toFixed(0)}%`, inline: true },
      { name: "Volume", value: Math.round(market[12]), inline: true },
    ];

    const detailSheetName = `Market_${market[0]}_details`;
    const detailSheet = spreadsheet.getSheetByName(detailSheetName);
    let marketUrl = `${spreadsheetUrl}#gid=${sheet.getSheetId()}&range=A${rowIndex}`;
    if (detailSheet) {
      marketUrl = `${spreadsheetUrl}#gid=${detailSheet.getSheetId()}`;
    }

    return {
      title: `${market[1]} (#${market[0]})`,
      url: marketUrl,
      color: color,
      fields: fields,
    };
  });

  const today = formatDate(new Date());

  // 1. Send the preface message to the thread
  const prefacePayload = {
    content: `--- **Updated on ${today}** ---`,
  };
  notifyDiscord(prefacePayload, threadId);
  Utilities.sleep(1000); // Pause for 1 second

  // 2. Send all embeds to the same thread in batches of 10
  for (let i = 0; i < embeds.length; i += 10) {
    const batch = embeds.slice(i, i + 10);
    const embedPayload = {
      embeds: batch,
    };
    notifyDiscord(embedPayload, threadId);
    Utilities.sleep(1000); // Pause for 1 second
  }
}

function updateOpenMarkets() {
  const openMarketsThreadId = "1434935418230407270";
  const openFilter = (market) => {
    const status = market[5];
    return status === "Open";
  };
  const openSort = (a, b) => b.row[10] - a.row[10]; // Sort by P(Yes) descending
  updateMarkets(openMarketsThreadId, openFilter, openSort);
}

function updateClosedMarkets() {
  const closedMarketsThreadId = "1434963412453949612";
  const closedFilter = (market) => {
    const status = market[5];
    return status === "Resolved Yes" || status === "Resolved No";
  };
  const closedSort = (a, b) => new Date(b.row[7]) - new Date(a.row[7]); // Sort by resolved date descending
  updateMarkets(closedMarketsThreadId, closedFilter, closedSort);
}

function notifyDiscord(payload, threadId, threadName) {
  let webhookUrl = PropertiesService.getScriptProperties().getProperty(
    "DISCORD_WEBHOOK_URL",
  );
  if (!webhookUrl) {
    SpreadsheetApp.getUi().alert("Discord webhook URL not set.");
    return;
  }

  const params = {};
  if (threadId) {
    params.thread_id = threadId;
  }
  if (threadName) {
    params.thread_name = threadName;
  }

  if (Object.keys(params).length > 0) {
    const queryString = Object.keys(params)
      .map((key) => `${key}=${encodeURIComponent(params[key])}`)
      .join("&");
    webhookUrl += `?${queryString}`;
  }

  const options = {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    muteHttpExceptions: false,
  };

  console.log(payload);
  // UrlFetchApp.fetch(webhookUrl, options);
}
