import json
import sqlite3

from core.schema import SchemaBuilder
from models.revive import Revive, ReviveRequest
from modules.revives.parser import ReviveParser
from repositories.revive_request_repository import ReviveRequestRepository


class DummyDb:

    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.cursor = self.connection.cursor()

    def execute(self, sql, params=()):
        self.cursor.execute(sql, params)
        return self.cursor

    def executemany(self, sql, values):
        self.cursor.executemany(sql, values)

    def commit(self):
        self.connection.commit()

    def fetchall(self):
        return self.cursor.fetchall()

    def select(self, sql, params=()):
        self.execute(sql, params)
        return self.fetchall()

    def insert(self, table, values):
        columns = ",".join(values.keys())
        placeholders = ",".join("?" for _ in values)
        self.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
            tuple(values.values()),
        )
        self.commit()

    def table_exists(self, table_name):
        rows = self.select(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        return bool(rows)


class DummyLogger:

    def info(self, *_args, **_kwargs):
        return None


def test_revive_parser_reads_full_payload():
    data = {
        "id": 17699594,
        "timestamp": 1784336201,
        "result": "success",
        "chance": 87.95,
        "reviver_id": 3408347,
        "reviver_name": "JeffBezas",
        "reviver_faction": 49431,
        "reviver_factionname": "Glory to Saints",
        "target_id": 430598,
        "target_name": "-Plutonium-",
        "target_faction": 0,
        "target_factionname": None,
        "target_hospital_reason": "Hospitalized by ...",
        "target_early_discharge": 0,
        "target_last_action": {
            "status": "Offline",
            "timestamp": 1674316991,
        },
    }

    parsed = ReviveParser.parse(data)

    assert parsed.revive_id == 17699594
    assert parsed.reviver_name == "JeffBezas"
    assert parsed.target_name == "-Plutonium-"
    assert parsed.target_last_action_status == "Offline"
    assert parsed.target_last_action_timestamp == 1674316991
    assert json.loads(parsed.raw_payload)["target_id"] == 430598


def test_revive_request_matches_successful_revive():
    db = DummyDb()
    logger = DummyLogger()
    schema = SchemaBuilder(db, logger)
    schema.create(Revive)
    schema.create(ReviveRequest)

    db.insert(
        "revives",
        {
            "revive_id": 1001,
            "timestamp": 2000,
            "result": "success",
            "chance": 90.0,
            "reviver_id": 123,
            "reviver_name": "Medic",
            "reviver_faction_id": 1,
            "reviver_faction_name": "Faction",
            "target_id": 555,
            "target_name": "Target",
            "target_faction_id": 0,
            "target_faction_name": "",
            "target_hospital_reason": "",
            "target_early_discharge": 0,
            "target_last_action_status": "Offline",
            "target_last_action_timestamp": 0,
            "raw_payload": "{}",
        },
    )

    repo = ReviveRequestRepository(db)
    repo.create_request(
        {
            "request_id": "req-1",
            "requested_timestamp": 1900,
            "created_at": 1901,
            "requester_id": 999,
            "requester_name": "Caller",
            "target_id": 555,
            "target_name": "Target",
            "source": "external",
            "status": "pending",
            "fulfilled_revive_id": None,
            "revived_timestamp": None,
            "fulfilled_at": None,
            "fulfilled_by_id": None,
            "fulfilled_by_name": None,
            "matched_at": None,
            "notified_at": None,
            "notes": None,
            "raw_payload": None,
        }
    )

    matched = repo.reconcile_against_database(window_seconds=600, limit=10)
    rows = repo.list_requests(status="all", limit=10)

    assert matched == 1
    assert rows[0]["status"] == "fulfilled"
    assert rows[0]["fulfilled_revive_id"] == 1001
    assert rows[0]["fulfilled_by_name"] == "Medic"
    assert rows[0]["revived_timestamp"] == 2000


def test_revive_request_reconcile_can_return_fulfilled_rows():
    db = DummyDb()
    logger = DummyLogger()
    schema = SchemaBuilder(db, logger)
    schema.create(Revive)
    schema.create(ReviveRequest)

    db.insert(
        "revives",
        {
            "revive_id": 1002,
            "timestamp": 2100,
            "result": "success",
            "chance": 91.0,
            "reviver_id": 124,
            "reviver_name": "Medic Two",
            "reviver_faction_id": 1,
            "reviver_faction_name": "Faction",
            "target_id": 556,
            "target_name": "Target Two",
            "target_faction_id": 0,
            "target_faction_name": "",
            "target_hospital_reason": "",
            "target_early_discharge": 0,
            "target_last_action_status": "Offline",
            "target_last_action_timestamp": 0,
            "raw_payload": "{}",
        },
    )

    repo = ReviveRequestRepository(db)
    repo.create_request(
        {
            "request_id": "req-2",
            "requested_timestamp": 2000,
            "created_at": 2001,
            "requester_id": 999,
            "requester_name": "Caller",
            "target_id": 556,
            "target_name": "Target Two",
            "source": "external",
            "status": "pending",
            "fulfilled_revive_id": None,
            "revived_timestamp": None,
            "fulfilled_at": None,
            "fulfilled_by_id": None,
            "fulfilled_by_name": None,
            "matched_at": None,
            "notified_at": None,
            "notes": None,
            "raw_payload": None,
        }
    )

    matched_rows = repo.reconcile_against_database(window_seconds=600, limit=10, return_rows=True)

    assert len(matched_rows) == 1
    assert matched_rows[0]["request_id"] == "req-2"
    assert matched_rows[0]["fulfilled_by_name"] == "Medic Two"


def test_revive_request_notifications_mark_rows_notified():
    db = DummyDb()
    logger = DummyLogger()
    schema = SchemaBuilder(db, logger)
    schema.create(Revive)
    schema.create(ReviveRequest)

    repo = ReviveRequestRepository(db)
    repo.create_request(
        {
            "request_id": "req-notify",
            "requested_timestamp": 1900,
            "created_at": 1901,
            "requester_id": 999,
            "requester_name": "Caller",
            "target_id": 555,
            "target_name": "Target",
            "source": "external",
            "status": "fulfilled",
            "fulfilled_revive_id": 1001,
            "revived_timestamp": 2000,
            "fulfilled_at": 2000,
            "fulfilled_by_id": 123,
            "fulfilled_by_name": "Medic",
            "matched_at": 2001,
            "notified_at": None,
            "notes": None,
            "raw_payload": None,
        }
    )

    rows = repo.get_unnotified_fulfilled(requester_id=999, limit=10)
    assert len(rows) == 1
    assert rows[0]["request_id"] == "req-notify"

    repo.mark_notified([rows[0]["request_id"]])
    rows_after = repo.get_unnotified_fulfilled(requester_id=999, limit=10)
    assert rows_after == []


def test_revive_request_dedupes_across_sources_for_same_requester():
    db = DummyDb()
    logger = DummyLogger()
    schema = SchemaBuilder(db, logger)
    schema.create(Revive)
    schema.create(ReviveRequest)

    repo = ReviveRequestRepository(db)

    first_id = repo.create_request(
        {
            "request_id": "req-source-a",
            "requested_timestamp": 3000,
            "created_at": 3001,
            "requester_id": 999,
            "requester_name": "Caller",
            "target_id": 555,
            "target_name": "Target",
            "source": "discord-bot",
            "status": "pending",
            "fulfilled_revive_id": None,
            "revived_timestamp": None,
            "fulfilled_at": None,
            "fulfilled_by_id": None,
            "fulfilled_by_name": None,
            "matched_at": None,
            "notified_at": None,
            "notes": None,
            "raw_payload": None,
        }
    )

    second_id = repo.create_request(
        {
            "request_id": "req-source-b",
            "requested_timestamp": 3030,
            "created_at": 3031,
            "requester_id": 999,
            "requester_name": "Caller",
            "target_id": 555,
            "target_name": "Target",
            "source": "tampermonkey-local",
            "status": "pending",
            "fulfilled_revive_id": None,
            "revived_timestamp": None,
            "fulfilled_at": None,
            "fulfilled_by_id": None,
            "fulfilled_by_name": None,
            "matched_at": None,
            "notified_at": None,
            "notes": None,
            "raw_payload": None,
        }
    )

    rows = repo.list_requests(status="all", limit=10)

    assert first_id == "req-source-a"
    assert second_id == "req-source-a"
    assert len(rows) == 1


def test_revive_request_does_not_dedupe_across_different_requesters():
    db = DummyDb()
    logger = DummyLogger()
    schema = SchemaBuilder(db, logger)
    schema.create(Revive)
    schema.create(ReviveRequest)

    repo = ReviveRequestRepository(db)

    first_id = repo.create_request(
        {
            "request_id": "req-user-a",
            "requested_timestamp": 4000,
            "created_at": 4001,
            "requester_id": 100,
            "requester_name": "Caller A",
            "target_id": 777,
            "target_name": "Target",
            "source": "discord-bot",
            "status": "pending",
            "fulfilled_revive_id": None,
            "revived_timestamp": None,
            "fulfilled_at": None,
            "fulfilled_by_id": None,
            "fulfilled_by_name": None,
            "matched_at": None,
            "notified_at": None,
            "notes": None,
            "raw_payload": None,
        }
    )

    second_id = repo.create_request(
        {
            "request_id": "req-user-b",
            "requested_timestamp": 4040,
            "created_at": 4041,
            "requester_id": 200,
            "requester_name": "Caller B",
            "target_id": 777,
            "target_name": "Target",
            "source": "tampermonkey-local",
            "status": "pending",
            "fulfilled_revive_id": None,
            "revived_timestamp": None,
            "fulfilled_at": None,
            "fulfilled_by_id": None,
            "fulfilled_by_name": None,
            "matched_at": None,
            "notified_at": None,
            "notes": None,
            "raw_payload": None,
        }
    )

    rows = repo.list_requests(status="all", limit=10)

    assert first_id == "req-user-a"
    assert second_id == "req-user-b"
    assert len(rows) == 2