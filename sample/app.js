/* Sample behaviour: role view switching, the state specimen, and opening the disclaimer.
   Classic script: no modules, no network, no storage. Without JavaScript every view stays visible. */
(function () {
  "use strict";

  var VIEWS = ["koordinator", "pacient", "lekar", "mdt", "specimen"];
  var DEFAULT_VIEW = "koordinator";
  var current = null;

  function isView(id) {
    return VIEWS.indexOf(id) !== -1;
  }

  function hashId() {
    return window.location.hash.replace("#", "");
  }

  function viewFromQuery() {
    var match = /[?&]role=([a-z]+)/.exec(window.location.search);
    return match && isView(match[1]) ? match[1] : DEFAULT_VIEW;
  }

  function showView(id, moveFocus) {
    var views = document.querySelectorAll("[data-view]");
    var links = document.querySelectorAll("[data-view-link]");
    var i;
    current = id;
    for (i = 0; i < views.length; i += 1) {
      views[i].hidden = views[i].getAttribute("data-view") !== id;
    }
    for (i = 0; i < links.length; i += 1) {
      if (links[i].getAttribute("data-view-link") === id) {
        links[i].setAttribute("aria-current", "page");
      } else {
        links[i].removeAttribute("aria-current");
      }
    }
    if (moveFocus) {
      var heading = document.querySelector("[data-view='" + id + "'] h1");
      if (heading) { heading.focus(); }
    }
  }

  function openDisclaimerIfTargeted() {
    if (hashId() === "o-ukazce") {
      var details = document.querySelector("#o-ukazce details");
      if (details) { details.open = true; }
    }
  }

  /* Only recognised role hashes change the view. Other fragments (#obsah, #o-ukazce)
     keep the current view; an empty fragment (back to the start) falls back to ?role=. */
  function onHashChange() {
    var id = hashId();
    if (isView(id)) {
      if (id !== current) { showView(id, true); }
    } else if (id === "") {
      showView(viewFromQuery(), true);
    }
    openDisclaimerIfTargeted();
  }

  function initStates() {
    var switcher = document.querySelector("[data-state-switch]");
    if (!switcher) { return; }
    var panes = document.querySelectorAll("[data-state]");
    function apply(value) {
      for (var i = 0; i < panes.length; i += 1) {
        panes[i].hidden = panes[i].getAttribute("data-state") !== value;
      }
    }
    switcher.hidden = false;
    switcher.addEventListener("change", function (event) {
      if (event.target && event.target.name === "state") { apply(event.target.value); }
    });
    var checked = switcher.querySelector("input:checked");
    apply(checked ? checked.value : "empty");
  }

  document.documentElement.className += " js";
  showView(isView(hashId()) ? hashId() : viewFromQuery(), false);
  openDisclaimerIfTargeted();
  initStates();
  window.addEventListener("hashchange", onHashChange);
})();
