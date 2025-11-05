import json
from pathlib import Path
from pprint import pprint

from datetime import datetime, timedelta


user_names = {}
for user in Path("data/raw_users.tsv").read_text().splitlines():
    user_id, user_name = user.split("\t")
    user_names[int(user_id)] = user_name

markets = {}
market_header, *market_entries = Path("data/raw_market.tsv").read_text().splitlines()
market_keys = market_header.split("\t")
for entry in market_entries:
    d = dict(zip(market_keys, entry.split("\t")))
    market_id = d["Market ID"] = int(d["Market ID"])
    d.setdefault("Detailed Criteria", "")
    markets[market_id] = d


def seconds_before(time_str: str, s=1) -> str:
    time = datetime.strptime(time_str, "%m/%d/%Y %H:%M:%S")
    one_sec_before = time - timedelta(seconds=s)
    return one_sec_before.strftime("%m/%d/%Y %H:%M:%S")


json_contents = []
created_users = set()
open_markets = set()
closed_markets = set()
counter = 0
header, *contents = Path("data/raw_ledger.tsv").read_text().splitlines()
header_keys = header.split("\t")
for line in contents:
    line_values = line.split("\t")
    d = dict(zip(header_keys, line_values))

    user_id = int(d["User Id"])
    if user_id not in created_users:
        created_users.add(user_id)
        initial_balance = 10_000.0
        json_event = {
            "#": len(json_contents),
            "timestamp": seconds_before(d["Timestamp"], s=2),
            "type": "user_update",
            "author": d["email"],
            "info": {
                "user_id": user_id,
                "user_name": user_names[user_id],
                "discord_id": "",
                "reason": "new user",
            },
        }
        json_contents.append(json_event)

        json_event = {
            "#": len(json_contents),
            "timestamp": seconds_before(d["Timestamp"], s=1),
            "type": "balance_update",
            "author": d["email"],
            "info": {
                "user_id": user_id,
                "delta": initial_balance,
                "old_balance": 0.0,
                "new_balance": initial_balance,
                "reason": "initial balance",
            },
        }
        json_contents.append(json_event)

    market_id = int(d["Market Id"])
    if market_id not in open_markets:
        open_markets.add(market_id)
        md = markets[market_id]
        json_event = {
            "#": len(json_contents),
            "timestamp": seconds_before(d["Timestamp"], s=10),
            "type": "market_update",
            "author": "ricardo.vieira@pymc-labs.com",
            "info": {
                "market_id": market_id,
                "question": md["Question"]
                .replace("\n", " ")
                .replace("  ", " ")
                .strip(),
                "open_date": md["Opens on"],
                "close_date": md["Closes on"],
                "resolve_date": md["Resolved on"],
                "liquidity": 10,
                "detailed_criteria": md["Detailed Criteria"],
                "status": "open",
                "reason": "new market",
            },
        }
        json_contents.append(json_event)

    event_type = "trade" if d["Transaction type"] == "user trade" else "resolution"

    if event_type == "resolution" and market_id not in closed_markets:
        closed_markets.add(market_id)
        md = markets[market_id]
        resolved_type = d["Transaction type"].replace(" ", "_")

        json_event = {
            "#": len(json_contents),
            "timestamp": seconds_before(d["Timestamp"], s=1),
            "type": "market_update",
            "author": "ricardo.vieira@pymc-labs.com",
            "info": {
                "market_id": market_id,
                "question": md["Question"].replace("\n", " ").replace("  ", " "),
                "open_date": md["Opens on"],
                "close_date": md["Closes on"],
                "resolve_date": md["Resolved on"],
                "liquidity": 10,
                "detailed_criteria": md["Detailed Criteria"],
                "status": resolved_type,
                "reason": "",
            },
        }
        json_contents.append(json_event)

    json_event = {
        "#": len(json_contents),
        # Ensures consistent formatting
        "timestamp": seconds_before(d["Timestamp"], s=0),
        "type": event_type,
        "author": d["email"],
        "info": {
            "user_id": user_id,
            "market_id": market_id,
            "share_type": d["Share Type"],
            "quantity": int(d["Quantity"]),
            "cost": float(d["TotalCost"]),
            "old_balance": float(d["prevBalance"]),
            "new_balance": float(d["newBalance"]),
        },
    }
    if event_type == "resolution":
        json_event["info"]["resolution"] = d["Transaction type"].replace(
            "resolved ", ""
        )
    json_contents.append(json_event)

json_lines = [json.dumps(line) for line in json_contents]
Path("data/ledger.json").write_text("\n".join(json_lines), encoding="utf-8")
