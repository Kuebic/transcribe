// Playback. Clicking a Segment (or pressing Enter on it) seeks the player to the Segment's start,
// and the Segment being heard is highlighted as playback moves.
(() => {
  const player = document.querySelector("audio.player");
  const list = document.querySelector("ol.transcript");
  if (!player || !list) return;

  const segments = [...list.querySelectorAll("li.segment")];
  const starts = segments.map((segment) => Number(segment.dataset.start));
  const ends = segments.map((segment) => Number(segment.dataset.end));
  let current = null;

  // Segments come in start order; between two Segments nothing is highlighted.
  function segmentAt(time) {
    const index = starts.findLastIndex((start) => start <= time);
    return index >= 0 && time < ends[index] ? segments[index] : null;
  }

  function highlight(segment) {
    if (segment === current) return;
    current?.classList.remove("current");
    segment?.classList.add("current");
    current = segment;
  }

  function seek(segment) {
    player.currentTime = Number(segment.dataset.start);
    highlight(segment);
    player.play().catch(() => {});
  }

  list.classList.add("seekable");
  for (const segment of segments) segment.tabIndex = 0;

  list.addEventListener("click", (event) => {
    const segment = event.target.closest("li.segment");
    // A click that ends a text selection is the owner selecting text, not asking to seek.
    if (segment && !window.getSelection().toString()) seek(segment);
  });
  list.addEventListener("keydown", (event) => {
    const segment = event.target.closest("li.segment");
    if (segment && event.key === "Enter") seek(segment);
  });

  const follow = () => highlight(segmentAt(player.currentTime));
  player.addEventListener("timeupdate", follow);
  player.addEventListener("seeked", follow);
})();
