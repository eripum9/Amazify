// Amazon publishes position in roughly 120 ms steps. Interpolate only that
// short gap; a stalled player must never turn into a free-running lyrics clock.
Karaoke.PlaybackClock = function () { this.reset(); };
Karaoke.PlaybackClock.prototype.reset = function () {
  this.sample = null;
  this.sampleAt = 0;
  this.output = 0;
  this.playing = false;
};
Karaoke.PlaybackClock.prototype.read = function (position, playing, now, duration) {
  position = Math.max(0, Number(position) || 0);
  const discontinuity = this.sample === null || this.playing !== playing ||
    position < this.sample || Math.abs(position - this.output) > 350;
  if (discontinuity || position !== this.sample) {
    this.sample = position;
    this.sampleAt = now;
  }
  let value = position + (playing ? Math.max(0, Math.min(250, now - this.sampleAt)) : 0);
  if (!discontinuity && playing) value = Math.max(value, this.output);
  if (duration > 0) value = Math.min(value, duration);
  this.playing = playing;
  this.output = value;
  return value;
};
