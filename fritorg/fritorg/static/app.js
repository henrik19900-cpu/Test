// Small extras on top of pages that work without JavaScript.

// "Del": the phone's own share sheet, or copy the link where there is none.
for (const button of document.querySelectorAll("[data-share-url]")) {
  const url = button.dataset.shareUrl;
  const title = button.dataset.shareTitle;
  const label = button.querySelector(".share-label");
  if (!navigator.share && !navigator.clipboard) continue;
  button.hidden = false;
  button.addEventListener("click", async () => {
    try {
      if (navigator.share) {
        await navigator.share({ title, url });
      } else {
        await navigator.clipboard.writeText(url);
        if (label) label.textContent = "Lenken er kopiert";
      }
    } catch {
      // The person closed the share sheet, or copying was not allowed.
    }
  });
}
