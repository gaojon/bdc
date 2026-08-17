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
    setupWordTooltips();
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

// ---- Article word hover tooltips (word-bank info on highlighted words) ----
function setupWordTooltips() {
    const dataEl = document.getElementById("word-tooltip-data");
    if (!dataEl) return;

    let glossary;
    try {
        glossary = JSON.parse(dataEl.textContent);
    } catch (e) {
        return;
    }
    if (!glossary || Object.keys(glossary).length === 0) return;

    const articleEl = document.querySelector("article");
    if (!articleEl) return;

    // Coarse pointer = touch device (iPhone/tablet): no hover, use tap instead.
    const isTouch = window.matchMedia
        ? window.matchMedia("(pointer: coarse)").matches
        : false;

    const tip = document.createElement("div");
    tip.id = "word-tooltip";
    tip.setAttribute("role", "tooltip");
    document.body.appendChild(tip);

    let currentSpan = null;

    function esc(s) {
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function hideTip() {
        tip.style.display = "none";
    }

    function showTip(span) {
        const data = glossary[span.textContent.trim().toLowerCase()];
        if (!data) return;

        let html = '<div class="wt-word">' + esc(data.word);
        if (data.pron) {
            html += ' <span class="wt-pron">' + esc(data.pron) + "</span>";
        }
        html += "</div>";
        if (data.pos) {
            html += '<div class="wt-pos">' + esc(data.pos) + "</div>";
        }
        if (data.english_definition) {
            html += '<div class="wt-en">' + esc(data.english_definition) + "</div>";
        }
        if (data.definition) {
            html += '<div class="wt-cn">' + esc(data.definition) + "</div>";
        }
        if (data.examples) {
            html += '<div class="wt-ex">' + esc(data.examples) + "</div>";
        }
        if (data.synonyms || data.antonyms) {
            html += '<div class="wt-syn">';
            if (data.synonyms) {
                html += '<span style="color:#059669;">⇧ ' + esc(data.synonyms) + "</span>";
            }
            if (data.synonyms && data.antonyms) html += " ";
            if (data.antonyms) {
                html += '<span style="color:#dc2626;">⇩ ' + esc(data.antonyms) + "</span>";
            }
            html += "</div>";
        }

        tip.innerHTML = html;
        tip.style.display = "block";

        if (isTouch) {
            // Touch: pin the tooltip to the top-center of the viewport so the
            // finger never covers it. Cap its height so long entries scroll.
            tip.style.maxWidth = "90vw";
            tip.style.maxHeight = "70vh";
            tip.style.overflowY = "auto";
            tip.style.top = "10px";
            tip.style.left = "50%";
            tip.style.transform = "translateX(-50%)";
        } else {
            // Desktop: position just above the word, flipping below if no room.
            tip.style.maxWidth = "320px";
            tip.style.maxHeight = "";
            tip.style.overflowY = "";
            tip.style.transform = "none";
            const rect = span.getBoundingClientRect();
            const tipW = tip.offsetWidth;
            const tipH = tip.offsetHeight;
            let top = rect.top - tipH - 8;
            if (top < 4) top = rect.bottom + 8;
            const left = Math.min(Math.max(4, rect.left), window.innerWidth - tipW - 8);
            tip.style.top = top + "px";
            tip.style.left = left + "px";
        }
    }

    if (isTouch) {
        // Tap a highlighted word to toggle the tooltip; tap elsewhere to close.
        document.addEventListener("click", function (e) {
            const span = e.target.closest(".word-target");
            if (span) {
                if (currentSpan === span) {
                    currentSpan = null;
                    hideTip();
                } else {
                    currentSpan = span;
                    showTip(span);
                }
            } else {
                currentSpan = null;
                hideTip();
            }
        });
    } else {
        articleEl.addEventListener("mouseover", function (e) {
            const span = e.target.closest(".word-target");
            if (span && span !== currentSpan) {
                currentSpan = span;
                showTip(span);
            } else if (!span) {
                currentSpan = null;
                hideTip();
            }
        });
    }

    // Hide when the page scrolls or resizes: fixed positioning goes stale.
    window.addEventListener("scroll", hideTip, { passive: true });
    window.addEventListener("resize", hideTip);
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
