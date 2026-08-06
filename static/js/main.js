/**
 * BDC Vocabulary — Minimal JavaScript Enhancements
 *
 * No frameworks. Vanilla JS only.
 */

document.addEventListener("DOMContentLoaded", function () {
    setupComplexitySlider();
    setupMasterAllButton();
    setupQuizSubmission();
    setupDetailsPersistence();
});

// ---- Complexity slider live value display ----
function setupComplexitySlider() {
    const slider = document.querySelector('input[name="sentence_complexity"]');
    const display = document.getElementById("complexity-value");
    if (!slider || !display) return;

    slider.addEventListener("input", function () {
        display.textContent = this.value;
    });
}

// ---- "Master All" button confirmation ----
function setupMasterAllButton() {
    const masterAllBtn = document.querySelector('button[name="action"][value="master_all"]');
    if (!masterAllBtn) return;

    masterAllBtn.addEventListener("click", function (e) {
        const confirmed = confirm(
            "Mark ALL hit words as mastered?\n\n" +
            "This will move all words to your mastered list."
        );
        if (!confirmed) {
            e.preventDefault();
        }
    });
}

// ---- Quiz form: disable submit after click (prevent double submission) ----
function setupQuizSubmission() {
    const quizForm = document.querySelector('form[action*="quiz/submit"]');
    if (!quizForm) return;

    quizForm.addEventListener("submit", function () {
        const submitBtn = quizForm.querySelector('button[type="submit"]:not([name="skip"])');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = "Submitting...";
        }
    });
}

// ---- Persist <details> open/close state via localStorage ----
function setupDetailsPersistence() {
    const detailsEls = document.querySelectorAll("details[data-persist]");
    detailsEls.forEach(function (details) {
        const key = details.getAttribute("data-persist");

        // Restore saved state
        const saved = localStorage.getItem(key);
        if (saved !== null) {
            details.open = saved === "true";
        }

        // Save state on toggle
        details.addEventListener("toggle", function () {
            localStorage.setItem(key, details.open ? "true" : "false");
        });
    });
}
