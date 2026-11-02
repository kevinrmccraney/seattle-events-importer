from __future__ import annotations

import json
from datetime import datetime
from xml.etree import ElementTree as ET

from dateutil.parser import isoparse

from .models import Event

NS = "urn:seattle-events:v1"


def _get(item: ET.Element, name: str) -> str | None:
    node = item.find(f"{{{NS}}}{name}")
    return node.text.strip() if node is not None and node.text else None


def parse_feed(xml_bytes: bytes) -> tuple[str, datetime, list[Event]]:
    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("RSS channel missing")
    source_node = channel.find(f"{{{NS}}}source")
    generated_node = channel.find(f"{{{NS}}}generated_at")
    if source_node is None or not source_node.text:
        raise ValueError("normalized feed source missing")
    if generated_node is None or not generated_node.text:
        raise ValueError("normalized feed generated_at missing")
    source = source_node.text.strip()
    generated_at = isoparse(generated_node.text.strip())

    events: list[Event] = []
    for item in channel.findall("item"):
        guid = item.findtext("guid")
        title = item.findtext("title")
        source_event_id = _get(item, "source_event_id")
        venue = _get(item, "venue")
        start_at = _get(item, "start_at")
        event_url = _get(item, "event_url") or item.findtext("link")
        if not all((guid, title, source_event_id, venue, start_at, event_url)):
            raise ValueError("normalized RSS item missing required field")
        metadata_text = _get(item, "metadata") or "{}"
        metadata = json.loads(metadata_text)
        events.append(Event(
            id=guid.strip(), source=source, source_event_id=source_event_id,
            title=title.strip(), venue=venue, start_at=isoparse(start_at), event_url=event_url,
            end_at=isoparse(_get(item, "end_at")) if _get(item, "end_at") else None,
            ticket_url=_get(item, "ticket_url"), image_url=_get(item, "image_url"),
            description=item.findtext("description"), support=_get(item, "support"),
            promoter=_get(item, "promoter"), doors_time=_get(item, "doors_time"),
            age_restriction=_get(item, "age_restriction"), status=_get(item, "status") or "scheduled",
            sold_out=(_get(item, "sold_out") or "false").lower() == "true", metadata=metadata,
        ))
    return source, generated_at, events
