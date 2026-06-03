(function () {
  const dataEl = document.getElementById("inventory-data");
  const listEl = document.getElementById("inventory-list");
  const statusEl = document.getElementById("inventory-status");
  const emptyEl = document.getElementById("inventory-empty");
  const searchEl = document.getElementById("filter-q");
  const categoryEl = document.getElementById("filter-category");
  const locationEl = document.getElementById("filter-location");
  const sortEl = document.getElementById("filter-sort");
  const orderEl = document.getElementById("filter-order");
  const clearEl = document.getElementById("clear-filters");

  if (!dataEl || !listEl) {
    return;
  }

  const allItems = JSON.parse(dataEl.textContent);
  const SORT_FIELDS = ["display_name", "category", "location"];

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
    const field = SORT_FIELDS.includes(sortEl.value) ? sortEl.value : "display_name";
    const desc = orderEl.value === "desc";
    const sorted = [...items];
    sorted.sort((a, b) => {
      const cmp = String(a[field]).localeCompare(String(b[field]), undefined, {
        sensitivity: "base",
      });
      return desc ? -cmp : cmp;
    });
    return sorted;
  }

  function createItemRow(item) {
    const li = document.createElement("li");
    li.className = "inventory-item";

    const thumbWrap = document.createElement("div");
    thumbWrap.className = "inventory-thumb-wrap";

    const img = document.createElement("img");
    img.className = "inventory-thumb";
    img.src = item.image_url;
    img.alt = item.display_name;
    thumbWrap.appendChild(img);

    const summary = document.createElement("div");
    summary.className = "inventory-summary";

    const name = document.createElement("span");
    name.className = "inventory-name";
    name.textContent = item.display_name;

    const category = document.createElement("span");
    category.className = "inventory-meta";
    category.textContent = item.category;

    const location = document.createElement("span");
    location.className = "inventory-meta";
    location.textContent = item.location;

    summary.append(name, category, location);
    li.append(thumbWrap, summary);
    return li;
  }

  function updateStatus(shown, total) {
    if (shown === total) {
      statusEl.textContent = `${total} item${total === 1 ? "" : "s"}`;
    } else {
      statusEl.textContent = `Showing ${shown} of ${total} items`;
    }
  }

  function render() {
    const filtered = sortItems(filterItems());
    listEl.replaceChildren(...filtered.map(createItemRow));
    updateStatus(filtered.length, allItems.length);
    emptyEl.hidden = filtered.length > 0;
    listEl.hidden = filtered.length === 0;
  }

  function clearFilters() {
    searchEl.value = "";
    categoryEl.value = "";
    locationEl.value = "";
    sortEl.value = "display_name";
    orderEl.value = "asc";
    render();
  }

  fillSelect(categoryEl, distinct("category"), "All categories");
  fillSelect(locationEl, distinct("location"), "All locations");

  searchEl.addEventListener("input", render);
  categoryEl.addEventListener("change", render);
  locationEl.addEventListener("change", render);
  sortEl.addEventListener("change", render);
  orderEl.addEventListener("change", render);
  clearEl.addEventListener("click", clearFilters);

  render();
})();
