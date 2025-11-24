# Usage:
#   python src/send_events.py
 
# Required env (.env or environment):
#   EVENTHUB_CONNECTION_STRING
#   EVENTHUB_NAME
#   EVENTHUB_NAMESPACE     (optional, informational)
#   ENV=local | global
# """
 
import asyncio
import json
import os
from datetime import datetime
from typing import Dict, Optional, List
 
from azure.eventhub import EventData
from azure.eventhub.aio import EventHubProducerClient
 
# # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# #  IMPORT YOUR EMAIL-EXTRACTOR LOGIC HERE
# # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
from test2 import (
    get_all_messages,
    process_single_email,
)
# # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
 
 
# # ------------------ Utilities ------------------
 
def load_env(path: str = ".env") -> None:
    """Minimal .env loader (no external dependency).
    Lines in KEY=VALUE format (quotes optional). Ignores comments/blank lines.
    """
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                continue
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # Do not override an already-set env var
            os.environ.setdefault(key, value)
 
 
def sanitize_filename(filename: str) -> str:
    """Remove characters that are invalid in file names on Windows/Linux."""
    import re
    return re.sub(r'[<>:"/\\|?*]', '_', filename)
 
 
# Load .env early
load_env()
 
# ------------------ Configuration ------------------
 
ENV = os.environ.get("ENV", "").lower()  # "local" or "global"
IS_LOCAL_ENV = (ENV == "local")
 
EVENTHUB_NAMESPACE = os.environ.get("EVENTHUB_NAMESPACE")
EVENTHUB_NAME = os.environ.get("EVENTHUB_NAME")
CONNECTION_STRING = os.environ.get("EVENTHUB_CONNECTION_STRING")
 
# Where to store JSON files when ENV=local
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "email_extracts")
 
if IS_LOCAL_ENV and not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
 
# Optional older file-based path (still here if you want to reuse it)
WEATHER_DATA_FILE = os.environ.get("WEATHER_DATA_FILE", "weather_advisories.json")
 
 
# ------------------ Optional: file-based reader (legacy) ------------------
 
def read_weather_advisories(file_path: Optional[str] = None) -> Dict:
    """
    (Legacy / optional) Read weather advisory data from a single JSON file.
 
    Not used in the email→Event pipeline below, but kept if you
    still want to send from a static JSON file sometimes.
    """
    if file_path is None:
        file_path = WEATHER_DATA_FILE
 
    if not os.path.exists(file_path):
        raise FileNotFoundError(
            f"Weather advisories file not found: {file_path}\n"
            f"Please run your data creator script first to generate the data file."
        )
 
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
 
        if not isinstance(data, dict):
            raise ValueError(f"Expected dictionary in {file_path}, got {type(data)}")
 
        print(f"✓ Loaded advisory JSON from {file_path}")
        return data
 
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {file_path}: {e}")
    except Exception as e:
        raise ValueError(f"Error reading {file_path}: {e}")
 
 
# ------------------ Sample test event factory (unchanged) ------------------
 
def create_sample_weather_event(event_id: int) -> Dict:
    """Create a sample weather event payload (for manual testing)."""
    return {
        "event_id": event_id,
        "timestamp": datetime.utcnow().isoformat(),
        "location": {
            "latitude": 40.7128 + (event_id * 0.001),
            "longitude": -74.0060 + (event_id * 0.001),
            "city": f"Testcity{event_id}",
            "country": "US",
        },
        "weather": {
            "temperature": 20 + (event_id % 15),
            "humidity": 60 + (event_id % 30),
            "pressure": 1013 + (event_id % 10),
            "wind_speed": 10 + (event_id % 20),
            "wind_direction": (event_id * 45) % 360,
            "conditions": ["sunny", "cloudy", "rainy", "stormy"][event_id % 4],
        },
        "source": "test-script",
        "version": "1.0",
    }
 
 
# ------------------ EventHub Sender helpers ------------------
 
async def send_single_event_with_producer(
    producer: EventHubProducerClient,
    event_data: Dict,
) -> None:
    """
    Send a single custom event (dict) using an already-created producer.
    """
    event_json = json.dumps(event_data)
    event_data_obj = EventData(event_json)
 
    # Simple per-event batch (still uses batching API, but instant send)
    event_data_batch = await producer.create_batch()
    event_data_batch.add(event_data_obj)
    await producer.send_batch(event_data_batch)
    print("   ✅ Event sent to EventHub")
 
 
async def send_events_batch(num_events: int = 10) -> None:
    """(Optional) Send a batch of dummy test events to Event Hub."""
    if not CONNECTION_STRING:
        raise ValueError(
            "EVENTHUB_CONNECTION_STRING environment variable not set.\n"
            "Set it in .env or export it in your shell."
        )
 
    if not EVENTHUB_NAME:
        raise ValueError("EVENTHUB_NAME environment variable not set.")
 
    print(f"Connecting to EventHub: {EVENTHUB_NAME}")
    print(f"Namespace: {EVENTHUB_NAMESPACE}")
    print(f"Preparing to send {num_events} test events...")
 
    producer = EventHubProducerClient.from_connection_string(
        conn_str=CONNECTION_STRING,
        eventhub_name=EVENTHUB_NAME,
    )
 
    try:
        async with producer:
            event_data_batch = await producer.create_batch()
            events_sent = 0
 
            for i in range(num_events):
                event_payload = create_sample_weather_event(i + 1)
                event_json = json.dumps(event_payload)
 
                try:
                    event_data_batch.add(EventData(event_json))
                    events_sent += 1
                    print(f"✓ Added test event {i + 1} to batch: {event_payload['location']['city']}")
                except ValueError:
                    print(f"Batch full. Sending {events_sent} events...")
                    await producer.send_batch(event_data_batch)
                    print("✓ Batch sent successfully!")
 
                    event_data_batch = await producer.create_batch()
                    event_data_batch.add(EventData(event_json))
                    events_sent = 1
 
            if events_sent > 0:
                print(f"Sending final batch of {events_sent} events...")
                await producer.send_batch(event_data_batch)
                print("✓ Final batch sent successfully!")
 
        print("=" * 60)
        print(f"✓ Successfully sent {num_events} test events to EventHub")
 
    except Exception as e:
        print(f"✗ Error sending test events: {e}")
        raise
    finally:
        await producer.close()
 
 
# ------------------ EMAIL → JSON → EVENT (single-pass pipeline) ------------------
 
async def send_all_advisories_from_email() -> None:
    """
    High-level pipeline (single-pass):
 
      - Fetch emails via Graph
      - For each email:
          * Extract advisory JSON using process_single_email()
          * If ENV=local → save JSON file
          * Immediately send that advisory as an Event to Azure Event Hub
 
    No separate "collect then send" phase – creation and sending happen together.
    """
    if not CONNECTION_STRING:
        raise ValueError(
            "EVENTHUB_CONNECTION_STRING environment variable not set.\n"
            "Set it in .env or export it in your shell."
        )
 
    if not EVENTHUB_NAME:
        raise ValueError("EVENTHUB_NAME environment variable not set.")
 
    print("=" * 60)
    print("📥 Collecting & Sending Weather Advisories from Emails (via Graph)")
    print(f"Environment mode: {ENV} (IS_LOCAL_ENV={IS_LOCAL_ENV})")
    print(f"EventHub: {EVENTHUB_NAME} | Namespace: {EVENTHUB_NAMESPACE}")
    print("=" * 60)
 
    all_messages = get_all_messages(page_size=50)
    total_emails = len(all_messages)
 
    print(f"Total emails fetched from Graph: {total_emails}")
 
    advisories_extracted = 0
    advisories_sent = 0
    advisories_skipped = 0
 
    # Create a single producer and reuse it for all emails
    producer = EventHubProducerClient.from_connection_string(
        conn_str=CONNECTION_STRING,
        eventhub_name=EVENTHUB_NAME,
    )
 
    try:
        async with producer:
            for idx, message in enumerate(all_messages):
                subject = message.get("subject", "No Subject")
                short_subject = subject[:80]
                print(f"\nProcessing email {idx + 1}/{total_emails}: {short_subject!r}")
 
                weather_advisory = process_single_email(message)
 
                if not weather_advisory:
                    print("   ↳ Skipped (no valid advisory extracted).")
                    advisories_skipped += 1
                    continue
 
                advisories_extracted += 1
 
                # If ENV=local → save JSON file per email
                if IS_LOCAL_ENV:
                    received_dt = message.get("receivedDateTime", "")[:10].replace("-", "_")
                    subject_clean = sanitize_filename(subject[:30] or "No_Subject")
                    filename = f"{idx + 1:03d}{received_dt}{subject_clean}.json"
                    filepath = os.path.join(OUTPUT_DIR, filename)
 
                    try:
                        with open(filepath, "w", encoding="utf-8") as f:
                            json.dump(weather_advisory, f, indent=2, ensure_ascii=False)
                        station_count = len(weather_advisory.get("stations", []))
                        print(f"   ✓ Saved advisory JSON ({station_count} station(s)) to {filepath}")
                    except Exception as e:
                        print(f"   ✗ Error saving JSON file {filepath}: {e}")
 
                else:
                    print("   (global ENV) Not writing JSON file, only sending to EventHub.")
 
                # ✅ Immediately send this advisory as an Event
                try:
                    await send_single_event_with_producer(producer, weather_advisory)
                    advisories_sent += 1
                except Exception as e:
                    print(f"   ✗ Error sending advisory event: {e}")
 
    finally:
        # producer is closed by async context manager, but keep for safety
        await producer.close()
 
    print("\nSummary:")
    print(f"  Emails scanned: {total_emails}")
    print(f"  Advisories extracted: {advisories_extracted}")
    print(f"  Advisories sent to EventHub: {advisories_sent}")
    print(f"  Emails skipped (no advisory): {advisories_skipped}")
    if IS_LOCAL_ENV:
        print(f"  JSON files directory: {OUTPUT_DIR}")
 
 
# ------------------ Entrypoint ------------------
 
def main() -> None:
    import sys
 
    print("=" * 60)
    print("Azure EventHub Weather Advisory Sender (Email → Events)")
    print("=" * 60)
    print(f"ENV = {ENV}")
    print(f"EVENTHUB_NAME = {EVENTHUB_NAME}")
    print(f"EVENTHUB_NAMESPACE = {EVENTHUB_NAMESPACE}")
    print("=" * 60)
 
    # Still keep the dummy test mode:
    # python send_events.py test 5
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        num_events = 5
        if len(sys.argv) > 2:
            try:
                num_events = int(sys.argv[2])
            except ValueError:
                print(f"Invalid num_events: {sys.argv[2]} (using default 5)")
        try:
            asyncio.run(send_events_batch(num_events))
        except KeyboardInterrupt:
            print("Interrupted by user")
        except Exception as e:
            print(f"Failed to send test events: {e}")
            sys.exit(1)
        return
 
    # Default behavior: single-pass email → JSON [+optional file] → EventHub
    try:
        asyncio.run(send_all_advisories_from_email())
    except KeyboardInterrupt:
        print("Interrupted by user")
    except Exception as e:
        print(f"Failed to process/send advisory events: {e}")
        sys.exit(1)
 
 
if __name__ == "__main__":
    main()
