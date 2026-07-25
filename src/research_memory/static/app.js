document.addEventListener("DOMContentLoaded", () => {
  const tabButtons = document.querySelectorAll(".tab-button");
  tabButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const target = button.dataset.tab;
      tabButtons.forEach((item) => item.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
      button.classList.add("active");
      document.getElementById(`tab-${target}`)?.classList.add("active");
    });
  });

  document.querySelectorAll(".drop-zone input[type=file]").forEach((input) => {
    input.addEventListener("change", () => {
      const label = input.closest(".drop-zone");
      const strong = label?.querySelector("strong");
      if (!strong) return;
      const count = input.files?.length || 0;
      strong.textContent = count ? `${count} PDF${count === 1 ? "" : "s"} selected` : "Choose one or more PDFs";
    });
  });

  document.querySelectorAll("form[action*='/delete'], form[action*='/remove']").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm("Remove this item? The original PDF file will not be deleted.")) {
        event.preventDefault();
      }
    });
  });

  document.querySelectorAll(".flash").forEach((flash) => {
    if (flash.classList.contains("warning") || flash.classList.contains("error")) return;
    window.setTimeout(() => {
      flash.style.opacity = "0";
      flash.style.transition = "opacity .3s ease";
      window.setTimeout(() => flash.remove(), 350);
    }, 5000);
  });
});
