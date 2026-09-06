/* Show the chosen picture straight away, before it is uploaded.
 *
 * Picking a file and then seeing no change until after a save is unsettling -
 * people cannot tell whether it worked. The preview answers that immediately.
 */
(function () {
  "use strict";
  var input = document.getElementById("photo-input");
  var preview = document.getElementById("photo-preview");
  var name = document.getElementById("photo-name");
  var remove = document.getElementById("remove-photo");
  if (!input || !preview) return;

  input.addEventListener("change", function () {
    var file = input.files && input.files[0];
    if (!file) return;

    if (file.size > 5 * 1024 * 1024) {
      if (name) {
        name.textContent = "That image is over 5 MB — please pick a smaller one.";
        name.style.color = "var(--bad)";
      }
      input.value = "";
      return;
    }

    if (name) {
      name.textContent = file.name;
      name.style.color = "";
    }
    if (remove) remove.checked = false;

    var reader = new FileReader();
    reader.onload = function (e) {
      if (preview.tagName === "IMG") {
        preview.src = e.target.result;
      } else {
        var img = document.createElement("img");
        img.className = preview.className;
        img.id = preview.id;
        img.src = e.target.result;
        img.alt = "";
        preview.replaceWith(img);
        preview = img;
      }
    };
    reader.readAsDataURL(file);
  });
})();
