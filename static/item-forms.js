(function () {
  const ACTION_LABELS = {
    checkout: "Check out",
    checkin: "Check in",
    change_condition: "Update condition",
    reserve: "Reserve",
  };

  const actionBar = document.getElementById("item-action-bar");
  const panel = document.getElementById("item-operation-panel");
  const panelTitle = document.getElementById("item-operation-panel-title");
  const forms = document.querySelectorAll(".operation-form[data-form-type]");

  function syncConditionNotes(condition, notes) {
    if (condition.value === "ok") {
      notes.value = "";
      notes.disabled = true;
      notes.setCustomValidity("");
    } else {
      notes.disabled = false;
    }
  }

  function validateConditionForm(form) {
    const condition = form.querySelector('[name="condition"]');
    const notes = form.querySelector('[name="condition_description"]');
    if (!condition || !notes) {
      return true;
    }

    if (condition.value === "ok") {
      notes.value = "";
      notes.setCustomValidity("");
      return true;
    }

    notes.setCustomValidity("");
    if (!notes.value.trim()) {
      notes.setCustomValidity(
        "Condition notes are required when condition is not OK."
      );
      return false;
    }
    return true;
  }

  function hideAllForms() {
    forms.forEach((form) => {
      form.hidden = true;
    });
  }

  function closePanel() {
    if (!panel) {
      return;
    }
    panel.hidden = true;
    hideAllForms();
    if (actionBar) {
      actionBar.hidden = false;
    }
  }

  function openPanel(action) {
    if (!panel || !panelTitle) {
      return;
    }

    const form = document.querySelector(
      `.operation-form[data-form-type="${action}"]`
    );
    if (!form) {
      return;
    }

    hideAllForms();
    form.hidden = false;
    panelTitle.textContent = ACTION_LABELS[action] || action;
    panel.hidden = false;
    if (actionBar) {
      actionBar.hidden = true;
    }

    const firstInput = form.querySelector("input:not([type='hidden']), select");
    if (firstInput) {
      firstInput.focus();
    }
  }

  document.querySelectorAll(".operation-cancel").forEach((button) => {
    button.addEventListener("click", closePanel);
  });

  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => {
      openPanel(button.dataset.action);
    });
  });

  document.querySelectorAll(".reservation-cancel-form").forEach((form) => {
    const prompt = form.querySelector(".reservation-cancel-prompt");
    const confirm = form.querySelector(".reservation-cancel-confirm");
    const trigger = form.querySelector(".reservation-cancel-trigger");
    const keep = form.querySelector(".reservation-keep");

    if (!prompt || !confirm || !trigger || !keep) {
      return;
    }

    function showConfirm() {
      prompt.hidden = true;
      confirm.hidden = false;
      form.classList.add("is-confirming");
    }

    function hideConfirm() {
      confirm.hidden = true;
      prompt.hidden = false;
      form.classList.remove("is-confirming");
    }

    trigger.addEventListener("click", showConfirm);
    keep.addEventListener("click", hideConfirm);
  });

  forms.forEach((form) => {
    const formType = form.dataset.formType;

    form.addEventListener("submit", (event) => {
      if (!form.checkValidity()) {
        event.preventDefault();
        form.reportValidity();
        return;
      }

      if (formType === "checkin" || formType === "change_condition") {
        if (!validateConditionForm(form)) {
          event.preventDefault();
          form.querySelector('[name="condition_description"]').reportValidity();
        }
      }
    });

    if (formType === "checkin" || formType === "change_condition") {
      const condition = form.querySelector('[name="condition"]');
      const notes = form.querySelector('[name="condition_description"]');
      if (condition && notes) {
        syncConditionNotes(condition, notes);
        condition.addEventListener("change", () => {
          syncConditionNotes(condition, notes);
        });
        notes.addEventListener("input", () => {
          notes.setCustomValidity("");
        });
      }
    }
  });
})();
