// A short welcome shown on the first visit (and from Help): what the map
// shows and the five things to try first. Remembered per browser.

const SEEN_KEY = "co2-routing-welcome-seen";

const STEPS = [
  ["The map", "Coloured cells are the <b>cost surface</b>: green is cheap to build through, red is expensive, " +
    "grey or empty is blocked. Switch the 35 underlying layers on and off in <b>Map layers</b> on the left."],
  ["Routes", "The <b>Routes</b> tab lists the cheapest route from each CO₂ source to its best storage site. " +
    "Click one to zoom to it and see its <b>corridor</b>: the band where an almost-as-good route could run."],
  ["Why is it expensive here?", "Press <b>Explain cost under the mouse</b> (top left of the map) and move the mouse. " +
    "You see which layers, distances and people make up the cost of each place."],
  ["Change the model", "Open <b>Model settings</b>, change a weight or turn a layer into a barrier, and press " +
    "<b>Run</b>. All routes are recalculated in about 10–20 seconds and drawn in orange next to the published ones."],
  ["Learn and rebuild", "The <b>Learn</b> tab has the wiki (why every weight was chosen, with references), " +
    "one-click experiments, and a step-by-step guide to building the same model in <b>ArcGIS Pro ModelBuilder</b>."],
];

function seen() {
  try {
    return localStorage.getItem(SEEN_KEY) === "1";
  } catch {
    return false;
  }
}

function markSeen() {
  try {
    localStorage.setItem(SEEN_KEY, "1");
  } catch {
    // Storage blocked: the welcome may show again next visit, which is harmless.
  }
}

export function showWelcome({ openLearn } = {}) {
  let dialog = document.getElementById("welcome-dialog");
  if (!dialog) {
    dialog = document.createElement("dialog");
    dialog.id = "welcome-dialog";
    dialog.className = "welcome-dialog";
    dialog.innerHTML = `
      <h2>Welcome</h2>
      <p class="muted">Least-cost CO₂ pipeline routing in Denmark, built from open data.
        Every assumption can be changed and recalculated in your browser.</p>
      <ol class="welcome-steps">${STEPS.map(([title, text]) =>
        `<li><strong>${title}${/[?!.]$/.test(title) ? "" : "."}</strong> ${text}</li>`).join("")}</ol>
      <div class="button-row">
        <button type="button" class="primary" data-action="close">Start exploring</button>
        <button type="button" data-action="learn">Show me the experiments</button>
      </div>
      <p class="muted small">You can open this again from Model settings → Help.</p>`;
    dialog.addEventListener("click", (event) => {
      const action = event.target.dataset?.action;
      if (!action) return;
      markSeen();
      dialog.close();
      if (action === "learn" && openLearn) openLearn();
    });
    dialog.addEventListener("cancel", markSeen);
    document.body.append(dialog);
  }
  dialog.showModal();
}

export function showWelcomeOnFirstVisit(options) {
  if (!seen()) showWelcome(options);
}
