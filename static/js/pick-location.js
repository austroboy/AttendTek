/* Fill the office latitude/longitude boxes from wherever the admin is standing. */
(function () {
  "use strict";
  var button = document.getElementById("use-my-location");
  if (!button) return;

  button.addEventListener("click", function () {
    var note = document.getElementById("location-note");
    if (!navigator.geolocation) {
      note.textContent = "This browser cannot share a location.";
      return;
    }
    button.disabled = true;
    note.textContent = "Reading your location…";
    navigator.geolocation.getCurrentPosition(
      function (p) {
        document.getElementById("id_latitude").value = p.coords.latitude.toFixed(6);
        document.getElementById("id_longitude").value = p.coords.longitude.toFixed(6);
        note.textContent = "Filled in from where you are now (±" + Math.round(p.coords.accuracy) + " m). Do this while sitting in the office.";
        button.disabled = false;
      },
      function () {
        note.textContent = "Could not read your location. Type the coordinates by hand.";
        button.disabled = false;
      },
      { enableHighAccuracy: true, timeout: 15000 }
    );
  });
})();
