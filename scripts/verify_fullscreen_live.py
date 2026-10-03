"""Isolated fullscreen QA against an already-running Amazon Music DevTools target.

Stop the installed daemon before running. Uses only a temporary plugin profile;
restores localStorage settings, Now Playing visibility, and the native frame.
No track changes, playback commands, installation writes, or app restarts.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from ctypes import wintypes

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from amazify.devtools import DevToolsClient, DevToolsHttp
from amazify.fullscreen import WindowsDesktop
from amazify.native_bridge import NativeBindingBridge
from amazify.plugin_manager import PluginManager
from amazify.runtime import build_cleanup_script, build_runtime_script


METRICS = r"""JSON.stringify((function(){
  function measure(selector) {
    var n=document.querySelector(selector);if(!n)return null;
    var r=n.getBoundingClientRect(),s=getComputedStyle(n);
    return {rect:{left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height},
      position:s.position,top:s.top,right:s.right,bottom:s.bottom,left:s.left,
      transform:s.transform,display:s.display,visibility:s.visibility,
      inline:n.getAttribute('style')};
  }
  return {viewport:{width:innerWidth,height:innerHeight,outerWidth:outerWidth,outerHeight:outerHeight},
    fullscreen:!!(document.fullscreenElement||document.webkitFullscreenElement),
    supportsInset:CSS.supports('inset','0'),body:document.body.className,
    transportClass:document.querySelector('#transportContainer').className,
    container:measure('#transportContainer'),transport:measure('#transport'),
    content:measure('#transport .content'),controls:measure('#transport .playbackControls'),
    play:measure('#transport .playPause'),progress:measure('#transport .slider.progressBar'),
    errors:Array.from(document.querySelectorAll('[data-amazify-plugin-error]')).map(function(n){return n.textContent;})};
})())"""

EXIT_FULLSCREEN = """(function(){
  if(!(document.fullscreenElement||document.webkitFullscreenElement||document.msFullscreenElement))return;
  var exit=document.exitFullscreen||document.webkitExitFullscreen||document.msExitFullscreen;
  if(typeof exit!=='function')throw Error('Browser fullscreen exit is unavailable');
  exit.call(document);
})()"""


def pump_for(client: DevToolsClient, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        client.pump(timeout=0.1)


def frame_data(state: dict[str, Any]) -> dict[str, Any]:
    def rect(r: Any) -> list[int]:
        return [r.left, r.top, r.right, r.bottom]
    p = state['placement']
    return {'rect': rect(state['rect']), 'normalRect': rect(p.rcNormalPosition),
            'showCmd': p.showCmd, 'style': state['style'], 'exstyle': state['exstyle']}


def click(client: DevToolsClient, selector: str) -> None:
    point = client.evaluate(f'''(function(){{
      var n=document.querySelector({json.dumps(selector)});
      if(!n)throw Error('Missing QA click target');
      var r=n.getBoundingClientRect();return {{x:r.left+r.width/2,y:r.top+r.height/2}};
    }})()''')
    for event in ('mousePressed', 'mouseReleased'):
        client.call('Input.dispatchMouseEvent', {'type': event, **point, 'button': 'left', 'clickCount': 1})


def f11(client: DevToolsClient) -> None:
    for event in ('keyDown', 'keyUp'):
        client.call('Input.dispatchKeyEvent', {'type': event, 'key': 'F11', 'code': 'F11',
                    'windowsVirtualKeyCode': 122, 'nativeVirtualKeyCode': 122})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'build' / 'fullscreen-qa')
    parser.add_argument('--observe', action='store_true', help='Record failures without a failing exit code')
    parser.add_argument('--cycles', type=int, default=2)
    parser.add_argument('--maximized', action='store_true', help='Test a maximized frame, then restore the original placement')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    desktop = WindowsDesktop()
    desktop.api.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    candidates = desktop.candidates()
    if len(candidates) != 1:
        raise RuntimeError('QA requires a unique Amazon Music window')
    original_frame = desktop.capture(candidates[0])
    client = DevToolsClient(DevToolsHttp(args.port).wait_for_amazon_music_target(5))
    client.connect()
    keys = ('amazify.runtime.settings.v1', 'amazify.plugin.settings.v1')
    saved_settings = {key: client.evaluate(f'localStorage.getItem({json.dumps(key)})') for key in keys}
    initial = json.loads(client.evaluate(METRICS))
    if initial['fullscreen']:
        client.close()
        raise RuntimeError('Exit existing browser fullscreen before isolated QA')
    was_now_playing = 'nowPlayingShowing' in initial['transportClass']
    report: dict[str, Any] = {'initial': initial, 'originalFrame': frame_data(original_frame),
                             'samples': {}, 'failures': []}

    def capture(name: str, screenshot: bool = True) -> dict[str, Any]:
        metrics = json.loads(client.evaluate(METRICS))
        metrics['frame'] = frame_data(desktop.capture(candidates[0]))
        rect = wintypes.RECT()
        if not desktop.api.GetClientRect(candidates[0], ctypes.byref(rect)):
            raise OSError('Could not measure native client area')
        metrics['nativeClient'] = {'width': rect.right - rect.left, 'height': rect.bottom - rect.top}
        report['samples'][name] = metrics
        if screenshot:
            result = client.call('Page.captureScreenshot', {'format': 'png'})
            (args.output / f'{name}.png').write_bytes(base64.b64decode(result['data']))
        print(json.dumps({'sample': name, 'viewport': metrics['viewport'], 'fullscreen': metrics['fullscreen'],
                          'frame': metrics['frame'], 'transport': metrics['transport'],
                          'controls': metrics['controls']}), flush=True)
        return metrics

    def check_normal(name: str, metrics: dict[str, Any], baseline: dict[str, Any]) -> None:
        failures = []
        if metrics['fullscreen'] or metrics['frame'] != baseline['frame'] or metrics['viewport'] != baseline['viewport'] or metrics['nativeClient'] != baseline['nativeClient']:
            failures.append('window/viewport restoration')
        if metrics['errors']:
            failures.append('plugin errors')
        for control in ('transport', 'content', 'controls', 'play', 'progress'):
            value = metrics[control]
            if not value or value['rect']['height'] <= 0 or value['rect']['top'] < -1 or value['rect']['bottom'] > metrics['viewport']['height'] + 1:
                failures.append(f'{control} clipped or missing')
        report['failures'].extend(f'{name}: {failure}' for failure in failures)

    bridge = None
    try:
        client.evaluate(build_cleanup_script())
        pump_for(client, 0.5)
        if args.maximized:
            desktop.api.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            desktop.api.ShowWindow(candidates[0], 3)
            pump_for(client, 1)
        client.evaluate('''localStorage.setItem('amazify.runtime.settings.v1',JSON.stringify({
          fullscreenShortcut:true,autoCheckUpdates:false,autoCheckAppUpdates:false}));
          localStorage.setItem('amazify.plugin.settings.v1',JSON.stringify({
          'amazify.true-big-mode':{autoFullscreen:true}}));
          if(document.querySelector('.nowPlayingView .closeButtonWrapper'))
            document.querySelector('.nowPlayingView .closeButtonWrapper').click();''')
        with tempfile.TemporaryDirectory(prefix='AmazifyFullscreenQA-') as directory:
            profile = Path(directory)
            manager = PluginManager(profile / 'plugins', profile / 'plugins_state.json',
                                    catalog_url=(ROOT / 'plugin_catalog.json').as_uri(), allow_local_catalog=True)
            manager.ensure_sample_plugins(ROOT / 'sample_plugins')
            manager.enable('amazify.theme.signal-studio')
            manager.enable('amazify.true-big-mode')
            def inject() -> None:
                nonlocal bridge
                client.evaluate(build_cleanup_script())
                pump_for(client, 0.5)
                if bridge:
                    bridge.close()
                # Runtime reply callbacks are deliberately non-configurable.
                # Each replacement therefore needs a fresh bridge/session.
                bridge = NativeBindingBridge(client, manager)
                bridge.install()
                client.evaluate(build_runtime_script(bridge_url='', bridge_token='',
                  plugins=manager.runtime_snapshot(), native_session_nonce=bridge.session_nonce,
                  native_response_callback=bridge.response_callback_name))
                pump_for(client, 2)

            inject()
            baseline = capture('signal-normal')
            for cycle in range(args.cycles):
                f11(client)
                pump_for(client, 2)
                entered = capture(f'f11-{cycle}-entered')
                if not entered['fullscreen'] or bridge.fullscreen.saved is None:
                    report['failures'].append(f'f11-{cycle}: did not enter native/browser fullscreen')
                f11(client)
                pump_for(client, 2)
                exited = capture(f'f11-{cycle}-exited')
                check_normal(f'f11-{cycle}-exited', exited, baseline)
            capture('tbm-normal')
            for cycle in range(args.cycles):
                click(client, '#transport .trackMetadataWrapper .albumArt')
                pump_for(client, 3)
                entered = capture(f'tbm-{cycle}-entered')
                if not entered['fullscreen'] or bridge.fullscreen.saved is None or 'amazify-true-big-mode-active' not in entered['body']:
                    report['failures'].append(f'tbm-{cycle}: did not enter native/browser TBM fullscreen')
                click(client, '.nowPlayingView .closeButtonWrapper')
                pump_for(client, 2)
                exited = capture(f'tbm-{cycle}-exited')
                check_normal(f'tbm-{cycle}-exited', exited, baseline)
    finally:
        try:
            try:
                # F11 sessions are user-owned, so runtime/plugin cleanup alone
                # cannot release them when a test fails between enter and exit.
                client.evaluate(EXIT_FULLSCREEN)
                pump_for(client, 1)
            finally:
                client.evaluate(build_cleanup_script())
                pump_for(client, 1)
        finally:
            try:
                if bridge:
                    bridge.close()
                desktop.restore(original_frame)
                for key, value in saved_settings.items():
                    expression = (f'localStorage.removeItem({json.dumps(key)})' if value is None else
                                  f'localStorage.setItem({json.dumps(key)},{json.dumps(value)})')
                    client.evaluate(expression)
                if was_now_playing:
                    client.evaluate('document.querySelector("#transportContainer").__vue__.showNowPlaying()')
                else:
                    client.evaluate('''if(document.querySelector('.nowPlayingView .closeButtonWrapper'))
                      document.querySelector('.nowPlayingView .closeButtonWrapper').click()''')
                pump_for(client, 1)
                report['restored'] = capture('restored', screenshot=False)
                report['settingsRestored'] = all(client.evaluate(f'localStorage.getItem({json.dumps(key)})') == value
                                                  for key, value in saved_settings.items())
                if report['restored']['fullscreen']:
                    report['failures'].append('browser fullscreen still active after restoration')
                if not report['settingsRestored'] or report['restored']['frame'] != report['originalFrame']:
                    report['failures'].append('original settings/frame not restored')
            finally:
                client.close()
                (args.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'failures': report['failures'], 'output': str(args.output)}))
    if report['failures'] and not args.observe:
        raise AssertionError(report['failures'])


if __name__ == '__main__':
    main()
