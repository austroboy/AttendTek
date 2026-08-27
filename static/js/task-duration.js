/* Fill the hours and minutes boxes from a single tap.
 *
 * Most log entries land on the same handful of lengths, so offering those
 * directly saves the employee two fiddly inputs on a phone. Typing exact
 * numbers still works for everything else.
 */
(function () {
  "use strict";
  var chips = document.querySelectorAll("[data-duration]");
  if (!chips.length) return;

  var hoursField = document.getElementById("id_hours");
  var minutesField = document.getElementById("id_minutes");
  if (!hoursField || !minutesField) return;

  chips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      var total = parseInt(chip.dataset.duration, 10);
      hoursField.value = Math.floor(total / 60);
      minutesField.value = total % 60;
      chips.forEach(function (c) { c.classList.remove("dark"); });
      chip.classList.add("dark");
    });
  });
})();
