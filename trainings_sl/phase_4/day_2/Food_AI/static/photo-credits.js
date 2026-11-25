"use strict";

async function loadCredits() {
  const response = await fetch("/static/images/menu/photos.json");
  if (!response.ok) throw new Error(`Could not load photo credits (HTTP ${response.status}).`);
  const photos = await response.json();
  const list = document.querySelector("#photo-credits");
  for (const [title, photo] of Object.entries(photos)) {
    const row = document.createElement("li");
    const source = document.createElement("a");
    source.textContent = photo.author;
    source.href = photo.source;
    const license = document.createElement("a");
    license.textContent = photo.license;
    license.href = photo.license_url;
    row.append(`${title}: `, source, " · ", license, " · resized");
    list.append(row);
  }
}

loadCredits().catch(error => {
  console.error(error);
  document.querySelector("#credits-error").textContent = error.message;
});
