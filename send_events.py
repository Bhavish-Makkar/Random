
#!/usr/bin/env python3
"""
Azure Event Hubs – Weather Test Event Sender

This script consolidates the code you provided into a single runnable program.
It supports sending a batch of sample weather events or a single event to an
Azure Event Hub using the connection string from a .env file / environment.

Usage:
  python src/send_events.py [num_events]
  # default num_events = 10

Environment variables (loaded from .env if present):
  EVENTHUB_CONNECTION_STRING  (required)
  EVENTHUB_NAME               (required)
  EVENTHUB_NAMESPACE          (optional, informational)
"""

import asyncio
import json
import os
from datetime import datetime
from typing import Dict, Optional

from azure.eventhub import EventData
from azure.eventhub.aio import EventHubProducerClient


# ------------------ Utilities ------------------

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


# Load .env early
load_env()

# ------------------ Configuration ------------------
EVENTHUB_NAMESPACE = os.environ.get("EVENTHUB_NAMESPACE")
EVENTHUB_NAME = os.environ.get("EVENTHUB_NAME")
CONNECTION_STRING = os.environ.get("EVENTHUB_CONNECTION_STRING")
WEATHER_DATA_FILE = os.environ.get("WEATHER_DATA_FILE", "weather_advisories.json")


 


# ------------------ Data Factory ------------------

def read_weather_advisories(file_path: Optional[str] = None) -> Dict:
    """
    Read weather advisory data from JSON file.
    
    Args:
        file_path: Path to the weather advisories JSON file.
                   If None, uses WEATHER_DATA_FILE from environment or default.
    
    Returns:
        Dictionary containing weather advisory data with keys:
        - created_at: ISO timestamp when data was created
        - total_stations: Number of stations in the data
        - stations: List of station advisory dictionaries
    
    Raises:
        FileNotFoundError: If the JSON file doesn't exist
        json.JSONDecodeError: If the file contains invalid JSON
        ValueError: If the file structure is invalid
    """
    if file_path is None:
        file_path = WEATHER_DATA_FILE
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(
            f"Weather advisories file not found: {file_path}\n"
            f"Please run create_data.py first to generate the data file."
        )
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Validate structure
        if not isinstance(data, dict):
            raise ValueError(f"Expected dictionary in {file_path}, got {type(data)}")
        
        if 'stations' not in data:
            raise ValueError(f"Missing 'stations' key in {file_path}")
        
        if not isinstance(data['stations'], list):
            raise ValueError(f"'stations' must be a list, got {type(data['stations'])}")
        
        print(f"✓ Successfully loaded {len(data.get('stations', []))} station advisories from {file_path}")
        return data
    
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {file_path}: {e}")
    except Exception as e:
        raise ValueError(f"Error reading {file_path}: {e}")

def create_sample_weather_event(event_id: int) -> Dict:
    """Create a sample weather event payload."""
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


# ------------------ Senders ------------------

async def send_single_event(event_data: Optional[Dict] = None) -> None:
    """Send a single custom event to Event Hub."""
    if not CONNECTION_STRING:
        raise ValueError(
            "EVENTHUB_CONNECTION_STRING environment variable not set.\n"
            "Set it in .env or export it in your shell."
        )

    if event_data is None:
        event_data = read_weather_advisories()

    print(f"Sending single event to EventHub: {EVENTHUB_NAME}")
    
    producer = EventHubProducerClient.from_connection_string(
        conn_str=CONNECTION_STRING,
        eventhub_name=EVENTHUB_NAME,
    )

    try:
        async with producer:
            event_data_batch = await producer.create_batch()
            event_json = json.dumps(event_data)
            event_data_batch.add(EventData(event_json))
            await producer.send_batch(event_data_batch)
            print("✓ Single event sent successfully")
    except Exception as e:
        print(f"✗ Error sending events: {e}")
        raise
    finally:
        await producer.close()


async def send_events_batch(num_events: int = 10) -> None:
    """Send a batch of test events to Event Hub."""
    if not CONNECTION_STRING:
        raise ValueError(
            "EVENTHUB_CONNECTION_STRING environment variable not set.\n"
            "Set it in .env or export it in your shell."
        )

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
                    print(f"✓ Added event {i + 1} to batch: {event_payload['location']['city']}")
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

        print("" + "=" * 60)
        print(f"✓ Successfully sent {num_events} test events to EventHub")

    except Exception as e:
        print(f"✗ Error sending event: {e}")
        raise
    finally:
        await producer.close()


# ------------------ Entrypoint ------------------

def main() -> None:
    import sys

    print("" + "=" * 60)
    print("Azure EventHub Test Event Sender")
    print("=" * 60 + "")

    num_events = 10
    if len(sys.argv) > 1:
        try:
            num_events = int(sys.argv[1])
        except ValueError:
            print(f"Invalid number of events: {sys.argv[1]}")
            print("Usage: python src/send_events.py [num_events]")
            sys.exit(1)

    try:
        asyncio.run(send_single_event())
    except KeyboardInterrupt:
        print("Interrupted by user")
    except Exception as e:
        print(f"Failed to send events: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()


# Now what I want you that I have script of extracting json data from email body of every particular email, now what I want you that you should use this script in this current script and do the following update 
# 1 st update when the env is global (in .env file ENV parameter is global) then simply extract the json from tabular data and send through events, no need to create and store json file in folder

#and if the ENV parameter is local then follow the full process (extract the json-> create the json file->and store and then sengt through events 
