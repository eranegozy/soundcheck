(function () {
  const forms = document.querySelectorAll(".operation-form[data-form-type]");
  if (!forms.length) {
    return;
  }

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
