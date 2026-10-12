"""Typed Doc00 v1.1 agent records, separate from model scores."""

from dataclasses import dataclass

from sentinelward.adapters.alert_publisher import stable_identity
from sentinelward.contracts import RecordMessage
from sentinelward.ports import FoundationStore


@dataclass
class MqttRecordPublisher:
    store: FoundationStore

    async def publish_record(self, record: RecordMessage) -> None:
        identity = stable_identity(record.record_id, record.model_dump_json())
        await self.store.enqueue_outbox(
            delivery_key=f"record:{identity}",
            destination="mqtt:ward/record",
            payload={"topic": "ward/record", "body": record.model_dump(mode="json"), "qos": 1},
            correlation_id=record.record_id,
        )
