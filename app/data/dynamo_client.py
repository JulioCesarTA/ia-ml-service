"""Cliente DynamoDB para idempotencia + sagas. SPEC §5 y §6."""
import os
import boto3
from botocore.exceptions import ClientError


def _client():
    return boto3.client(
        "dynamodb",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        endpoint_url=(os.getenv("DYNAMODB_ENDPOINT", "http://dynamodb-local:8000") or None),   # vacío = DynamoDB real en AWS
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
    )


IDEMPOTENCY_TABLE = os.getenv("DYNAMODB_TABLE_IDEMPOTENCY", "idempotency_keys")
SAGAS_TABLE = os.getenv("DYNAMODB_TABLE_SAGAS", "sagas")


def ensure_tables():
    c = _client()
    for name, key in [(IDEMPOTENCY_TABLE, "idempotencyKey"), (SAGAS_TABLE, "sagaId")]:
        try:
            c.describe_table(TableName=name)
        except ClientError:
            c.create_table(
                TableName=name,
                AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
                KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
                BillingMode="PAY_PER_REQUEST",
            )


def check_and_lock_idempotency(key: str, response_cache: dict | None = None) -> dict | None:
    """SPEC §6: ConditionExpression attribute_not_exists. Si existe, devuelve lo cacheado."""
    c = _client()
    try:
        c.put_item(
            TableName=IDEMPOTENCY_TABLE,
            Item={
                "idempotencyKey": {"S": key},
                "cachedResponse": {"S": __import__("json").dumps(response_cache or {})},
            },
            ConditionExpression="attribute_not_exists(idempotencyKey)",
        )
        return None  # primera vez
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            r = c.get_item(TableName=IDEMPOTENCY_TABLE, Key={"idempotencyKey": {"S": key}})
            raw = r["Item"]["cachedResponse"]["S"]
            return __import__("json").loads(raw)
        raise


def save_idempotency_response(key: str, response: dict) -> None:
    """Guarda la respuesta final de una operación para que un reintento con la misma clave la reciba tal cual."""
    _client().put_item(
        TableName=IDEMPOTENCY_TABLE,
        Item={"idempotencyKey": {"S": key}, "cachedResponse": {"S": __import__("json").dumps(response)}},
    )


def put_saga(saga_id: str, data: dict):
    c = _client()
    import json
    c.put_item(TableName=SAGAS_TABLE, Item={
        "sagaId": {"S": saga_id},
        "data": {"S": json.dumps(data)},
    })


def get_saga(saga_id: str) -> dict | None:
    c = _client()
    r = c.get_item(TableName=SAGAS_TABLE, Key={"sagaId": {"S": saga_id}})
    if "Item" not in r: return None
    import json
    return json.loads(r["Item"]["data"]["S"])
