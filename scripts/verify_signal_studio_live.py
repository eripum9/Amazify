"""Probe Signal Studio layout and exercise non-playback carousel controls over CDP.

The script never starts Amazify, navigates routes, or touches transport controls.
Run it against an already-open Amazon Music window, for example:

    python scripts/verify_signal_studio_live.py --port 58963 --output .playwright-mcp/signal-qa
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from amazify.devtools import DevToolsClient, DevToolsHttp


METRICS = r"""
JSON.stringify((function () {
  var visible = function (element) {
    if (!element) return false;
    var rect = element.getBoundingClientRect();
    var style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 &&
      style.display !== "none" && style.visibility !== "hidden";
  };
  var rectOf = function (element) {
    if (!element) return null;
    var rect = element.getBoundingClientRect();
    return {
      left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom,
      width: rect.width, height: rect.height
    };
  };
  var signature = function (section) {
    if (!section) return [];
    return Array.prototype.slice.call(section.querySelectorAll(
      ".verticalTile .title, .horizontalTile .title, img.artImage"
    )).slice(0, 16).map(function (element) {
      var value = element.tagName === "IMG" ? (element.currentSrc || element.src || "") : (element.innerText || element.textContent || "").trim();
      return {value: value, left: element.getBoundingClientRect().left};
    });
  };
  var controls = Array.prototype.slice.call(document.querySelectorAll(
    "#main-content .controlContainer > .prevButton, " +
    "#main-content .controlContainer > .nextButton"
  )).filter(visible).filter(function (element) {
    var rect = element.getBoundingClientRect();
    return rect.top < window.innerHeight && rect.bottom > 0;
  });
  var headings = Array.prototype.slice.call(document.querySelectorAll(
    "#main-content h1, #main-content h2, #main-content h3, #main-content h4, " +
    "#main-content .headline_1, #main-content .headline_2, " +
    "#main-content .headline_3, #main-content .headline_4, " +
    "#main-content .miniHeaderContainer .name"
  )).filter(visible).slice(0, 24);
  var main = document.querySelector("#main-content");
  var rail = document.querySelector("#appchrome");
  var ambience = document.querySelector(".signal-studio-ambience");
  var root = document.querySelector("#caterpillar, #root, #app");
  return {
    href: location.href,
    viewport: { width: window.innerWidth, height: window.innerHeight },
    rail: rectOf(rail),
    main: rectOf(main),
    ambience: ambience ? {
      rect: rectOf(ambience),
      background: getComputedStyle(ambience).backgroundColor,
      image: getComputedStyle(ambience).backgroundImage
    } : null,
    root: root ? {
      id: root.id,
      background: getComputedStyle(root).backgroundColor
    } : null,
    controls: controls.map(function (element) {
      var rect = element.getBoundingClientRect();
      var hit = document.elementFromPoint(
        (rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2
      );
      var section = element.closest("section.container");
      return {
        direction: element.classList.contains("nextButton") ? "next" : "previous",
        title: section ? ((section.querySelector(".sectionHeader .title") || {}).innerText || "").trim() : "",
        rect: rectOf(element),
        disabled: !!element.disabled,
        hit: hit ? { tag: hit.tagName, className: String(hit.className || "") } : null,
        signature: signature(section)
      };
    }),
    headings: headings.map(function (element) {
      return {
        text: (element.innerText || element.textContent || "").trim().slice(0, 120),
        rect: rectOf(element)
      };
    })
  };
})())
""".strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=58963)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def capture(client: DevToolsClient, path: Path) -> None:
    result = client.call("Page.captureScreenshot", {"format": "png"})
    path.write_bytes(base64.b64decode(result["data"]))


def click_at(client: DevToolsClient, point: dict[str, float]) -> None:
    for event_type in ("mousePressed", "mouseReleased"):
        client.call(
            "Input.dispatchMouseEvent",
            {
                "type": event_type,
                "x": point["x"],
                "y": point["y"],
                "button": "left",
                "clickCount": 1,
            },
        )


def first_visible_next(client: DevToolsClient) -> dict[str, float] | None:
    value = client.evaluate(
        r"""
        (function () {
          var buttons = Array.prototype.slice.call(document.querySelectorAll(
            "#main-content .controlContainer > .nextButton"
          ));
          for (var index = 0; index < buttons.length; index += 1) {
            var button = buttons[index];
            var rect = button.getBoundingClientRect();
            var style = getComputedStyle(button);
            if (rect.width > 0 && rect.height > 0 && rect.top < innerHeight &&
                rect.bottom > 0 && style.display !== "none" &&
                style.visibility !== "hidden" && !button.disabled) {
              return { x: (rect.left + rect.right) / 2, y: (rect.top + rect.bottom) / 2 };
            }
          }
          return null;
        })()
        """.strip()
    )
    return value if isinstance(value, dict) else None


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    target = DevToolsHttp(args.port).wait_for_amazon_music_target(8)
    client = DevToolsClient(target)
    client.connect()
    try:
        before = json.loads(client.evaluate(METRICS))
        (args.output / "before.json").write_text(
            json.dumps(before, indent=2), encoding="utf-8"
        )
        capture(client, args.output / "before.png")

        point = first_visible_next(client)
        after: dict[str, Any] | None = None
        if point:
            click_at(client, point)
            time.sleep(0.7)
            after = json.loads(client.evaluate(METRICS))
            (args.output / "after-next.json").write_text(
                json.dumps(after, indent=2), encoding="utf-8"
            )
            capture(client, args.output / "after-next.png")

        report = {
            "target": {"title": target.title, "url": target.url, "port": args.port},
            "clickedNext": point is not None,
            "carouselChanged": bool(
                after and before.get("controls") and after.get("controls") and
                before["controls"][0].get("signature") != after["controls"][0].get("signature")
            ),
            "before": before,
            "after": after,
        }
        (args.output / "report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps({
            "href": before.get("href"),
            "clickedNext": report["clickedNext"],
            "carouselChanged": report["carouselChanged"],
            "output": str(args.output),
        }))
    finally:
        client.close()


if __name__ == "__main__":
    main()
