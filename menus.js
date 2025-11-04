/**
 * @OnlyCurrentDoc
 */

function onOpen() {
  const ui = SpreadsheetApp.getUi();

  // Create the "Market Analysis" menu
  ui.createMenu("Market Analysis")
    .addItem("Generate Market Details", "createMarketDetailSheetUI")
    .addToUi();

  // Create the "Discord Updates" menu
  ui.createMenu("Discord Updates")
    .addItem("Update Open Markets", "updateOpenMarkets")
    .addItem("Update Closed Markets", "updateClosedMarkets")
    .addToUi();
}
