(function () {
  const dataEl = document.getElementById("sticker-data");
  const template = document.getElementById("sticker-template");
  const previewSheet = document.getElementById("sticker-preview");
  const printSheet = document.getElementById("sticker-print-sheet");
  const printArea = document.getElementById("sticker-print-area");
  const previewEmpty = document.getElementById("preview-empty");
  const printButton = document.getElementById("print-stickers");
  const selectAllButton = document.getElementById("select-all-stickers");
  const clearButton = document.getElementById("clear-stickers");
  const checkboxes = document.querySelectorAll(".sticker-select");

  if (!dataEl || !template || !previewSheet || !printSheet) {
    return;
  }

  const stickers = JSON.parse(dataEl.textContent);
  const stickerById = new Map(stickers.map((s) => [s.item_id, s]));

  function createStickerElement(sticker) {
    const node = template.content.firstElementChild.cloneNode(true);
    node.dataset.itemId = sticker.item_id;
    node.querySelector(".sticker-name").textContent = sticker.display_name;
    node.querySelector(".sticker-location").textContent = sticker.location;
    node.querySelector(".sticker-components").textContent = sticker.components_text;
    node.querySelector(".sticker-qr-fit").innerHTML = sticker.qr_svg;
    return node;
  }

  function selectedIds() {
    return [...checkboxes]
      .filter((cb) => cb.checked)
      .map((cb) => cb.dataset.itemId);
  }

  function renderSheet(container, ids) {
    container.replaceChildren();
    for (const itemId of ids) {
      const sticker = stickerById.get(itemId);
      if (sticker) {
        container.appendChild(createStickerElement(sticker));
      }
    }
  }

  function syncPreview() {
    const ids = selectedIds();
    const hasSelection = ids.length > 0;

    if (previewEmpty) {
      previewEmpty.hidden = hasSelection;
    }
    if (printButton) {
      printButton.disabled = !hasSelection;
    }

    renderSheet(previewSheet, ids);
    renderSheet(printSheet, ids);
  }

  checkboxes.forEach((checkbox) => {
    checkbox.addEventListener("change", syncPreview);
  });

  if (selectAllButton) {
    selectAllButton.addEventListener("click", () => {
      checkboxes.forEach((cb) => {
        cb.checked = true;
      });
      syncPreview();
    });
  }

  if (clearButton) {
    clearButton.addEventListener("click", () => {
      checkboxes.forEach((cb) => {
        cb.checked = false;
      });
      syncPreview();
    });
  }

  if (printButton && printArea) {
    printButton.addEventListener("click", () => {
      if (!selectedIds().length) {
        return;
      }
      printArea.hidden = false;
      window.print();
      printArea.hidden = true;
    });
  }

  window.addEventListener("afterprint", () => {
    if (printArea) {
      printArea.hidden = true;
    }
  });

  syncPreview();
})();
