"""Opt-in visual QA against an already-running Amazon Music DevTools target.

Run with the installed daemon stopped, then restart it afterwards. This changes
only the injected runtime, uses a temporary plugin profile, and never overwrites
installed plugins. Synthetic provider data is explicitly labelled in reports.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from amazify.devtools import DevToolsClient, DevToolsHttp
from amazify.lyrics_provider import LyricsProviderService
from amazify.native_bridge import NativeBindingBridge
from amazify.plugin_manager import PluginManager
from amazify.runtime import build_cleanup_script, build_runtime_script


class FixtureProvider:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.loads = 0
        self.delay = 0.0

    def status(self) -> dict[str, Any]:
        return {"ok": True, "providers": ["synthetic-qa-fixture"]}

    def load(self, track: dict[str, Any], key: str, *, cancel_event: threading.Event | None = None) -> dict[str, Any]:
        self.loads += 1
        if self.delay:
            if cancel_event is not None: cancel_event.wait(self.delay)
            else: time.sleep(self.delay)
        if self.mode == "error":
            raise OSError("Deliberate QA provider outage")
        lines = []
        for i in range(30):
            words = [
                {"text": "Testing ", "startMs": i * 6000, "endMs": i * 6000 + 2000},
                {"text": "lyrics ", "startMs": i * 6000 + 2000, "endMs": i * 6000 + 4000},
                {"text": "presentation", "startMs": i * 6000 + 4000, "endMs": i * 6000 + 6000},
            ]
            lines.append({"text": "Testing lyrics presentation", "startMs": i * 6000, "endMs": i * 6000 + 6000, "words": words})
        return {"ok": True, "status": "ready" if self.mode == "rich" else "no-lyrics", "trackKey": track["key"], "payload": {"schemaVersion": 1, "type": "syllable", "trackKey": track["key"], "source": "synthetic-qa-fixture", "lines": lines}}

    def cancel(self, key: str) -> dict[str, Any]:
        return {"ok": True}

    def close(self) -> None:
        pass

    def clear_cache(self) -> dict[str, Any]:
        return {"ok": True}


METRICS = """JSON.stringify((function(){
  var wrapper=document.querySelector('.nowPlayingView .lyricsWrapper');
  var host=document.querySelector('.amazify-karaoke-host');
  var native=wrapper&&Array.from(wrapper.querySelectorAll('ul.lyricsScroller')).find(function(n){return !n.closest('.amazify-karaoke-host')});
  var rich=host&&host.querySelector('.lyricsText');
  var normal=native&&native.querySelector('.lyricsText');
  function style(n){if(!n)return null;var s=getComputedStyle(n);return {font:s.font,color:s.color,lineHeight:s.lineHeight,letterSpacing:s.letterSpacing,display:s.display};}
  return {hosts:document.querySelectorAll('.amazify-karaoke-host').length,
    nativeVisible:!!(native&&native.getClientRects().length),
    lyricsRect:wrapper&&JSON.parse(JSON.stringify(wrapper.getBoundingClientRect())),
    centered:document.querySelector('#transportContainer').classList.contains('amazify-true-big-mode-no-lyrics'),
    trackRect:(function(){var n=document.querySelector('.nowPlayingView .track');return n&&JSON.parse(JSON.stringify(n.getBoundingClientRect()))})(),
    ownedRegion:!!document.querySelector('.amazify-karaoke-region'),
    presentation:host&&host.dataset.presentation, native:style(native),
    nativeText:style(normal), richText:style(rich), token:style(host&&host.querySelector('.amazify-karaoke-token')),
    currentNative:style(native&&native.querySelector('.current .lyricsText')), currentRich:style(host&&host.querySelector('.current .lyricsText')),
    enhanced:wrapper&&wrapper.classList.contains('amazify-karaoke-enhanced'),
    body:document.body.className, version:window.Amazify&&window.Amazify.version,
    errors:Array.from(document.querySelectorAll('[data-amazify-plugin-error]')).map(function(n){return n.textContent})};
})())"""


def pump_for(client: DevToolsClient, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        client.pump(timeout=0.1)


def toggle_plugin(client: DevToolsClient, plugin_id: str) -> None:
    client.evaluate('document.querySelector(".amazify-header-button").click()')
    client.evaluate('document.querySelector(\'[data-amazify-open="marketplace"]\').click()')
    pump_for(client, 0.5)
    selector = f'[data-amazify-toggle-plugin="{plugin_id}"]'
    position = json.loads(client.evaluate(f'''JSON.stringify((function(){{
        var node=document.querySelector({json.dumps(selector)});node.scrollIntoView();
        var r=node.getBoundingClientRect();return {{x:r.left+r.width/2,y:r.top+r.height/2}};
    }})())'''))
    for event in ("mousePressed", "mouseReleased"):
        client.call("Input.dispatchMouseEvent", {"type": event, **position, "button": "left", "clickCount": 1})
    pump_for(client, 1)
    client.evaluate('document.querySelector(".amazify-close").click()')
    pump_for(client, 0.5)


def toggle_lyrics_setting(client: DevToolsClient) -> bool:
    client.evaluate('document.querySelector(".amazify-header-button").click()')
    client.evaluate('document.querySelector(\'[data-amazify-open="marketplace"]\').click()')
    pump_for(client, 0.5)
    client.evaluate('document.querySelector(\'[data-amazify-open-plugin-settings="amazify.true-big-mode"]\').click()')
    selector = '[data-amazify-plugin-setting="amazify.true-big-mode"][data-amazify-plugin-setting-id="showLyrics"]'
    position = json.loads(client.evaluate(f'''JSON.stringify((function(){{
      var n=document.querySelector({json.dumps(selector)});n.scrollIntoView();
      var r=n.getBoundingClientRect();return {{x:r.left+r.width/2,y:r.top+r.height/2}};
    }})())'''))
    for event in ("mousePressed", "mouseReleased"):
        client.call("Input.dispatchMouseEvent", {"type": event, **position, "button": "left", "clickCount": 1})
    pump_for(client, 0.5)
    enabled = client.evaluate(f'document.querySelector({json.dumps(selector)}).getAttribute("aria-pressed")==="true"')
    client.evaluate('document.querySelector(".amazify-close").click()')
    pump_for(client, 3)
    return enabled


def exercise_settings(client: DevToolsClient, provider: FixtureProvider) -> dict[str, Any]:
    loads = provider.loads
    assert toggle_lyrics_setting(client) is False
    hidden = json.loads(client.evaluate(METRICS))
    assert hidden["hosts"] == 0 and hidden["centered"] and not hidden["ownedRegion"], hidden
    assert client.evaluate('getComputedStyle(document.querySelector(".nowPlayingView.x4 .lyricsContainer")).visibility') == "hidden"
    assert toggle_lyrics_setting(client) is True
    pump_for(client, 3)
    assert json.loads(client.evaluate(METRICS))["hosts"] == 1
    assert provider.loads == loads, "Settings change should reuse retained lyrics"
    assert toggle_lyrics_setting(client) is False
    toggle_plugin(client, "amazify.karaoke-lyrics")
    toggle_plugin(client, "amazify.karaoke-lyrics")
    pump_for(client, 5)
    assert provider.loads == loads, "Hidden lyrics must not contact the provider on activation"
    assert json.loads(client.evaluate(METRICS))["hosts"] == 0
    # Disabling the presentation releases its suppression claim, even if its
    # persisted setting is still off. Normal lyrics become active again.
    toggle_plugin(client, "amazify.true-big-mode")
    pump_for(client, 5)
    normal = json.loads(client.evaluate(METRICS))
    assert normal["hosts"] == 1 and normal["presentation"] == "normal", normal
    toggle_plugin(client, "amazify.true-big-mode")
    assert toggle_lyrics_setting(client) is True
    return {"hiddenNoProviderLoads": True, "retainedDataReused": True, "normalViewResumes": True}


def exercise_interactions(client: DevToolsClient, provider: FixtureProvider) -> dict[str, Any]:
    loads = provider.loads
    client.evaluate('document.querySelectorAll(".amazify-karaoke-line")[3].click()')
    pump_for(client, 2)
    position = client.evaluate('document.querySelector("#transportContainer").__vue__.playbackProgress.currentTime')
    assert abs(position - 18000) < 1500, {"seekPosition": position}
    point = json.loads(client.evaluate('''JSON.stringify((function(){
      var r=document.querySelector('.amazify-karaoke-host').getBoundingClientRect();
      return {x:r.left+r.width/2,y:r.top+r.height/2};
    })())'''))
    client.call("Input.dispatchMouseEvent", {"type": "mouseWheel", **point, "deltaX": 0, "deltaY": 230})
    pump_for(client, 0.2)
    assert client.evaluate('document.querySelector(".amazify-karaoke-host").classList.contains("is-manual-scroll")')
    pump_for(client, 5.5)
    centered_error = client.evaluate('''(function(){
      var host=document.querySelector('.amazify-karaoke-host'), row=host.querySelector('.current');
      var a=host.getBoundingClientRect(),b=row.getBoundingClientRect();
      return Math.abs((a.top+a.bottom)/2-(b.top+b.bottom)/2);
    })()''')
    assert centered_error < 8, {"activeLineCenterError": centered_error}
    client.evaluate('window.__amazifyKaraokeQA=document.querySelector(".amazify-karaoke-host");document.querySelector(".nowPlayingView .closeButtonWrapper").click()')
    pump_for(client, 1)
    assert json.loads(client.evaluate(METRICS))["hosts"] == 0
    client.evaluate('document.querySelector("#transportContainer").__vue__.showNowPlaying()')
    pump_for(client, 2)
    assert client.evaluate('window.__amazifyKaraokeQA===document.querySelector(".amazify-karaoke-host")')
    assert provider.loads == loads
    before = client.evaluate('document.querySelector("#transportContainer").__vue__.track.asin')
    client.evaluate('document.querySelector("#transport .nextButton, #transport .next").click()')
    pump_for(client, 4)
    after = client.evaluate('document.querySelector("#transportContainer").__vue__.track.asin')
    client.evaluate('if(document.querySelector("#transportContainer").__vue__.playerModel.state==="PLAYING")document.querySelector("#transport .playPause").click()')
    assert after != before and provider.loads == loads + 1
    assert json.loads(client.evaluate(METRICS))["hosts"] == 1
    client.evaluate('delete window.__amazifyKaraokeQA')
    return {"clickSeekMs": position, "manualScrollRecenters": True, "reopenRetainsRenderer": True, "trackSwitch": True}


def exercise_lifecycle(client: DevToolsClient, provider: FixtureProvider, presentation: str, native_missing: bool = False) -> dict[str, Any]:
    assert json.loads(client.evaluate(METRICS))["hosts"] == 1
    toggle_plugin(client, "amazify.karaoke-lyrics")
    if native_missing: pump_for(client, 2)
    disabled = json.loads(client.evaluate(METRICS))
    assert disabled["hosts"] == 0 and (native_missing or disabled["nativeVisible"]) and not disabled["enhanced"] and not disabled["ownedRegion"], disabled
    if native_missing and presentation in ("big", "both"):
        assert disabled["centered"], disabled
    toggle_plugin(client, "amazify.karaoke-lyrics")
    if native_missing: pump_for(client, 6)
    assert json.loads(client.evaluate(METRICS))["hosts"] == 1
    if presentation in ("big", "both"):
        client.evaluate('window.__amazifyKaraokeQA=document.querySelector(".amazify-karaoke-host")')
        loads = provider.loads
        toggle_plugin(client, "amazify.true-big-mode")
        assert client.evaluate('window.__amazifyKaraokeQA===document.querySelector(".amazify-karaoke-host")')
        assert json.loads(client.evaluate(METRICS))["presentation"] == "normal"
        toggle_plugin(client, "amazify.true-big-mode")
        assert json.loads(client.evaluate(METRICS))["presentation"] == "true-big-mode"
        assert provider.loads == loads
        client.evaluate('delete window.__amazifyKaraokeQA')
    return {"disableRestoresNative": True, "reenableSingleRenderer": True, "hostClaimPreserved": presentation in ("big", "both")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--presentation", choices=("native", "signal", "big", "both"), default="native")
    parser.add_argument("--lyrics", choices=("off", "rich", "missing", "error", "live"), default="rich")
    parser.add_argument("--seconds", type=float, default=5)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--lifecycle", action="store_true", help="Exercise real marketplace enable/disable controls in the temporary profile")
    parser.add_argument("--native-missing", action="store_true", help="Temporarily simulate absent Amazon lyrics; restore transport metadata on exit")
    parser.add_argument("--settings-test", action="store_true", help="Exercise True Big Mode Show lyrics and provider suspension; restore personal settings")
    parser.add_argument("--interactions", action="store_true", help="Seek, manually scroll, reopen and advance one real track (ends paused)")
    args = parser.parse_args()
    output = ROOT / "build" / "karaoke-qa"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="AmazifyKaraokeQA-") as directory:
        state = Path(directory)
        manager = PluginManager(state / "plugins", state / "plugins_state.json", catalog_url=(ROOT / "plugin_catalog.json").as_uri(), allow_local_catalog=True)
        manager.ensure_sample_plugins(ROOT / "sample_plugins")
        if args.presentation in ("signal", "both"):
            manager.enable("amazify.theme.signal-studio")
        if args.presentation in ("big", "both"):
            manager.enable("amazify.true-big-mode")
        if args.lyrics != "off":
            manager.enable("amazify.karaoke-lyrics")
        provider = LyricsProviderService(state) if args.lyrics == "live" else FixtureProvider(args.lyrics)
        if args.native_missing and isinstance(provider, FixtureProvider): provider.delay = 4
        client = DevToolsClient(DevToolsHttp(args.port).wait_for_amazon_music_target())
        client.connect()
        saved_settings = client.evaluate('localStorage.getItem("amazify.plugin.settings.v1")')
        bridge = NativeBindingBridge(client, manager, lyrics_provider=provider)  # type: ignore[arg-type]
        bridge.install()
        try:
            if args.width and args.height:
                client.call("Emulation.setDeviceMetricsOverride", {"width": args.width, "height": args.height, "deviceScaleFactor": 1, "mobile": False})
            if args.native_missing:
                client.evaluate('''(function(){
                  var t=document.querySelector('#transportContainer').__vue__.track;
                  var has=t.hasLyrics,data=t.lyricsData;
                  window.__amazifyKaraokeRestoreNative=function(){t.hasLyrics=has;t.lyricsData=data;};
                  t.hasLyrics=false;t.lyricsData=null;
                })()''')
                pump_for(client, 0.5)
            script = build_runtime_script(bridge_url="", bridge_token="", plugins=manager.runtime_snapshot(), native_session_nonce=bridge.session_nonce, native_response_callback=bridge.response_callback_name)
            client.evaluate(script)
            client.evaluate('document.querySelector("#transportContainer").__vue__.showNowPlaying()')
            samples = []
            if args.native_missing and args.lyrics == "rich" and args.presentation in ("big", "both"):
                started = time.monotonic()
                while time.monotonic() - started < args.seconds:
                    pump_for(client, 0.2)
                    sample = json.loads(client.evaluate(METRICS))
                    rect = sample["trackRect"]
                    if rect: samples.append({"at": round(time.monotonic()-started, 2), "x": rect["left"]+rect["width"]/2, "centered": sample["centered"]})
            else:
                pump_for(client, args.seconds)
            metrics = json.loads(client.evaluate(METRICS))
            metrics["providerMode"] = args.lyrics
            metrics["loads"] = getattr(provider, "loads", None)
            if args.lyrics == "rich":
                assert metrics["hosts"] == 1 and not metrics["nativeVisible"], metrics
                assert metrics["lyricsRect"]["height"] > 100 and metrics["lyricsRect"]["top"] < (args.height or 1080), metrics
                for property_name in ("font", "lineHeight", "letterSpacing"):
                    if metrics["nativeText"]:
                        assert metrics["nativeText"][property_name] == metrics["richText"][property_name] == metrics["token"][property_name], metrics
                if args.native_missing and args.presentation in ("big", "both"):
                    assert not metrics["centered"], metrics
                    assert metrics["trackRect"]["right"] < args.width / 2 + 100, metrics
                    centered_x = args.width / 2
                    final_x = samples[-1]["x"]
                    assert any(abs(sample["x"] - centered_x) < 4 and sample["at"] < 4 for sample in samples), samples
                    assert len([sample for sample in samples if sample["at"] > 4 and final_x + 10 < sample["x"] < centered_x - 10]) >= 3, samples
                    metrics["transitionSamples"] = samples
            elif args.lyrics in ("off", "missing", "error"):
                assert metrics["hosts"] == 0 and (args.native_missing or metrics["nativeVisible"]) and not metrics["enhanced"], metrics
                if args.native_missing and args.presentation in ("big", "both"):
                    assert metrics["centered"], metrics
            if args.lifecycle:
                assert isinstance(provider, FixtureProvider) and args.lyrics == "rich"
                metrics["lifecycle"] = exercise_lifecycle(client, provider, args.presentation, args.native_missing)
            if args.settings_test:
                assert isinstance(provider, FixtureProvider) and args.lyrics == "rich" and args.presentation in ("big", "both")
                metrics["settings"] = exercise_settings(client, provider)
            if args.interactions:
                assert isinstance(provider, FixtureProvider) and args.lyrics == "rich" and not args.native_missing
                metrics["interactions"] = exercise_interactions(client, provider)
            name = f"{args.presentation}-{args.lyrics}-{'no-amazon-' if args.native_missing else ''}{args.width or 'window'}"
            screenshot = client.call("Page.captureScreenshot", {"format": "png"})
            (output / f"{name}.png").write_bytes(base64.b64decode(screenshot["data"]))
            (output / f"{name}.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
            print(json.dumps(metrics))
            print(output / f"{name}.png")
        finally:
            client.evaluate(build_cleanup_script())
            if saved_settings is None:
                client.evaluate('localStorage.removeItem("amazify.plugin.settings.v1")')
            else:
                client.evaluate(f'localStorage.setItem("amazify.plugin.settings.v1",{json.dumps(saved_settings)})')
            client.evaluate('delete window.__amazifyKaraokeQA')
            if args.native_missing:
                client.evaluate('if(window.__amazifyKaraokeRestoreNative)window.__amazifyKaraokeRestoreNative();delete window.__amazifyKaraokeRestoreNative')
            if args.width and args.height:
                client.call("Emulation.clearDeviceMetricsOverride")
            client.close()


if __name__ == "__main__":
    main()
