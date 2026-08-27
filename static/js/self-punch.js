/* Attach the browser's location to a punch, then submit the form.
 *
 * The button never submits on its own: it asks for a position first, shows the
 * person what is happening while the phone works it out, and only then posts.
 * If the location is refused we say so plainly rather than silently sending a
 * punch with nothing attached.
 */
(function () {
  "use strict";

  var form = document.getElementById("punch-form");
  if (!form) return;

  var button = document.getElementById("punch-button");
  var statusBox = document.getElementById("punch-status");
  var latField = document.getElementById("id_latitude");
  var lngField = document.getElementById("id_longitude");
  var accField = document.getElementById("id_accuracy_m");
  var errField = document.getElementById("id_location_error");
  var requireLocation = form.dataset.requireLocation === "1";

  function say(message, kind) {
    statusBox.textContent = message;
    statusBox.className = "msg " + (kind || "info");
    statusBox.hidden = false;
  }

  function lock(text) {
    button.disabled = true;
    button.dataset.original = button.dataset.original || button.textContent;
    button.textContent = text;
  }

  function unlock() {
    button.disabled = false;
    if (button.dataset.original) button.textContent = button.dataset.original;
  }

  form.addEventListener("submit", function (event) {
    if (form.dataset.ready === "1") return;      // second pass - let it through
    event.preventDefault();

    if (!navigator.geolocation) {
      errField.value = "This browser cannot share a location";
      if (requireLocation) {
        say("This browser cannot share a location, so the punch cannot be recorded here. Please use the card reader or ask an admin to add the punch.", "error");
        return;
      }
      form.dataset.ready = "1";
      form.submit();
      return;
    }

    lock("Finding your location…");
    say("Getting your location. Allow it if your browser asks.", "info");

    navigator.geolocation.getCurrentPosition(
      function (position) {
        latField.value = position.coords.latitude.toFixed(6);
        lngField.value = position.coords.longitude.toFixed(6);
        accField.value = Math.round(position.coords.accuracy || 0);
        lock("Saving…");
        form.dataset.ready = "1";
        form.submit();
      },
      function (error) {
        unlock();
        var reason = {
          1: "Location permission was denied.",
          2: "Your location could not be worked out. Try moving near a window.",
          3: "Getting your location took too long."
        }[error.code] || "Your location could not be read.";
        errField.value = reason;

        if (requireLocation) {
          say(reason + " A location is required for a web punch — turn it on for this site and try again.", "error");
        } else {
          say(reason + " Punching without a location.", "warning");
          form.dataset.ready = "1";
          form.submit();
        }
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
    );
  });
})();
