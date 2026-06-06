(function () {
  const dataEl = document.getElementById("inventory-data");
  const listEl = document.getElementById("inventory-list");
  const statusEl = document.getElementById("inventory-status");
  const searchEl = document.getElementById("filter-q");
  const categoryEl = document.getElementById("filter-category");
  const locationEl = document.getElementById("filter-location");
  const sortButtons = document.querySelectorAll(".th-sort");

  if (!dataEl || !listEl) {
    return;
  }

  const allItems = JSON.parse(dataEl.textContent);
  const SORT_FIELDS = ["display_name", "category", "location"];
  let sortField = "display_name";
  let sortDesc = false;

  function distinct(field) {
    return [...new Set(allItems.map((item) => item[field]))].sort((a, b) =>
      a.localeCompare(b)
    );
  }

  function fillSelect(select, values, placeholder) {
    select.appendChild(new Option(placeholder, ""));
    for (const value of values) {
      select.appendChild(new Option(value, value));
    }
  }

  function matchesSearch(item, query) {
    if (!query) {
      return true;
    }
    const haystack =
      `${item.display_name} ${item.brand} ${item.model} ${item.category}`.toLowerCase();
    return haystack.includes(query);
  }

  function filterItems() {
    const category = categoryEl.value;
    const location = locationEl.value;
    const query = searchEl.value.trim().toLowerCase();

    return allItems.filter((item) => {
      if (category && item.category !== category) {
        return false;
      }
      if (location && item.location !== location) {
        return false;
      }
      return matchesSearch(item, query);
    });
  }

  function sortItems(items) {
    const field = SORT_FIELDS.includes(sortField) ? sortField : "display_name";
    const sorted = [...items];
    sorted.sort((a, b) => {
      const cmp = String(a[field]).localeCompare(String(b[field]), undefined, {
        sensitivity: "base",
      });
      return sortDesc ? -cmp : cmp;
    });
    return sorted;
  }

  function updateSortIndicators() {
    sortButtons.forEach((button) => {
      const field = button.dataset.sort;
      const indicator = button.querySelector(".sort-indicator");
      const active = field === sortField;
      button.classList.toggle("th-sort--active", active);
      if (!indicator) {
        return;
      }
      if (!active) {
        indicator.textContent = "";
        return;
      }
      indicator.textContent = sortDesc ? " ↓" : " ↑";
    });
  }

  function createBadge(text, className) {
    const badge = document.createElement("span");
    badge.className = `badge ${className}`;
    badge.textContent = text;
    return badge;
  }

  function createBadges(item) {
    const badges = document.createElement("div");
    badges.className = "badge-row";

    const custodyClass = item.is_past_due
      ? "badge-custody badge-custody-checked_out badge-past-due"
      : `badge-custody badge-custody-${item.custody}`;
    badges.appendChild(createBadge(item.custody_label, custodyClass));

    if (item.condition && item.condition !== "ok") {
      badges.appendChild(
        createBadge(
          item.condition_label,
          `badge-condition badge-condition-${item.condition}`
        )
      );
    }
    if (item.has_reservation) {
      badges.appendChild(createBadge("Reserved", "badge-reserved"));
    }
    return badges;
  }

  function createItemRow(item) {
    const row = document.createElement("tr");
    row.className = "inventory-row";
    row.tabIndex = 0;
    row.addEventListener("click", () => {
      window.location.href = item.item_url;
    });
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        window.location.href = item.item_url;
      }
    });

    const itemCell = document.createElement("td");
    itemCell.className = "inventory-cell-item";

    const itemInner = document.createElement("div");
    itemInner.className = "inventory-item-inner";

    const thumbWrap = document.createElement("div");
    thumbWrap.className = "inventory-thumb-wrap";

    const img = document.createElement("img");
    img.className = "inventory-thumb";
    img.src = item.image_url;
    img.alt = item.display_name;
    thumbWrap.appendChild(img);

    const textCol = document.createElement("div");
    textCol.className = "inventory-item-text";

    const name = document.createElement("span");
    name.className = "inventory-name";
    name.textContent = item.display_name;

    textCol.append(name, createBadges(item));
    itemInner.append(thumbWrap, textCol);
    itemCell.appendChild(itemInner);

    const categoryCell = document.createElement("td");
    categoryCell.className = "inventory-cell-category";
    categoryCell.textContent = item.category;

    const locationCell = document.createElement("td");
    locationCell.className = "inventory-cell-location";
    locationCell.textContent = item.location;

    row.append(itemCell, categoryCell, locationCell);
    return row;
  }

  function updateStatus(shown, total) {
    if (shown === total) {
      statusEl.textContent = `${total} item${total === 1 ? "" : "s"}`;
    } else {
      statusEl.textContent = `Showing ${shown} of ${total} items`;
    }
  }

  function createEmptyRow() {
    const row = document.createElement("tr");
    row.className = "inventory-empty-row";

    const cell = document.createElement("td");
    cell.colSpan = 3;
    cell.className = "inventory-empty-cell";
    cell.textContent = "No items match your filters.";
    row.appendChild(cell);
    return row;
  }

  function render() {
    const filtered = sortItems(filterItems());
    if (filtered.length === 0) {
      listEl.replaceChildren(createEmptyRow());
    } else {
      listEl.replaceChildren(...filtered.map(createItemRow));
    }
    updateStatus(filtered.length, allItems.length);
    updateSortIndicators();
  }

  function handleSortClick(field) {
    if (sortField === field) {
      sortDesc = !sortDesc;
    } else {
      sortField = field;
      sortDesc = false;
    }
    render();
  }

  fillSelect(categoryEl, distinct("category"), "All");
  fillSelect(locationEl, distinct("location"), "All");

  searchEl.addEventListener("input", render);
  categoryEl.addEventListener("change", render);
  locationEl.addEventListener("change", render);

  sortButtons.forEach((button) => {
    button.addEventListener("click", () => {
      handleSortClick(button.dataset.sort);
    });
  });

  render();
})();
