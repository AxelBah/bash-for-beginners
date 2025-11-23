# Delivery routing CLI (Geoapify + Google Sheets)

This lightweight Python app reads delivery requests from a Google Sheet, geocodes the postcodes with Geoapify, and builds a feasible route for each delivery day. It now treats the `desired_date` as the **latest allowable delivery date**, automatically grouping nearby postcodes into shared delivery days before their deadlines. It prints a per-day summary showing the stop order, drive and service time, and whether the day fits inside your working hours.

## Requirements

- Python 3.10+
- A Google service account with access to the sheet you want to read
- A Geoapify API key

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

## Preparing your Google Sheet

The CLI expects a header row with at least the following columns:

- `recipient`
- `postcode`
- `desired_date` (ISO or common date formats such as `DD/MM/YYYY`) — **interpreted as the latest acceptable delivery date**
- `notes` (optional)

Any additional columns are ignored. Example range: `Sheet1!A1:D99`.

## Running the planner

```bash
python -m delivery_routing.delivery_planner \
  --sheet-id <GOOGLE_SHEET_ID> \
  --range "Sheet1!A1:D99" \
  --service-account path/to/service-account.json \
  --geoapify-key $GEOAPIFY_API_KEY \
  --depot "10 Downing Street, London" \
  --country gb \
  --service-minutes 12 \
  --workday-minutes 480
```

Key flags:

- `--sheet-id`: The ID from your Google Sheet URL.
- `--range`: Range to read (including header row).
- `--service-account`: Path to your Google Cloud service account JSON file with Sheets access.
- `--geoapify-key`: Geoapify API key (or set `GEOAPIFY_API_KEY`).
- `--depot`: Address/postcode to start and end routes.
- `--country`: Optional country code to narrow geocoding results.
- `--service-minutes`: Minutes spent at each stop.
- `--workday-minutes`: Maximum minutes allowed per day (drive + service).

The output shows each delivery day with the stop order and whether it fits within the workday limit.

## How it works

1. Read delivery rows from the Google Sheet via the Sheets API.
2. Geocode the depot and all unique delivery postcodes with Geoapify.
3. Greedily cluster deliveries whose postcodes are within ~12 km of one another so nearby stops share the same delivery day.
4. Assign each cluster a delivery day on or before the earliest `desired_date` deadline in that cluster.
5. Use Geoapify's route matrix to estimate drive times between all stops in the cluster.
6. Build a nearest-neighbor route for each day and flag feasibility based on drive + service time.

## Environment variables

- `GEOAPIFY_API_KEY`: Optional way to provide the Geoapify key without the CLI flag.
