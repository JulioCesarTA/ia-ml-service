"""DynamoDB para idempotencia + sagas (puerto AlmacenSagas). SPEC §5 y §6.

Los nombres de tabla y la forma de los ítems no deben cambiar: hay datos en producción.
"""
import json
import os

import boto3
from botocore.exceptions import ClientError


def _client():
    return boto3.client(
        "dynamodb",
        # En producción es DynamoDB real de AWS (DYNAMODB_ENDPOINT con la URL de AWS), con un usuario IAM que solo ve estas dos tablas.
        # La URL debe ir explícita: el pod tiene AWS_ENDPOINT_URL apuntando a LocalStack, para SNS y SQS.
        # En desarrollo local (docker compose) sigue siendo DynamoDB Local.
        region_name=os.getenv("DYNAMODB_REGION") or os.getenv("AWS_REGION", "us-east-1"),
        endpoint_url=(os.getenv("DYNAMODB_ENDPOINT", "http://dynamodb-local:8000") or None),
        aws_access_key_id=os.getenv("DYNAMODB_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.getenv("DYNAMODB_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
    )


IDEMPOTENCY_TABLE = os.getenv("DYNAMODB_TABLE_IDEMPOTENCY", "idempotency_keys")
SAGAS_TABLE = os.getenv("DYNAMODB_TABLE_SAGAS", "sagas")


class AlmacenSagasDynamo:
    def asegurar_tablas(self) -> None:
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

    def bloquear_idempotencia(self, clave: str, respuesta: dict | None = None) -> dict | None:
        """SPEC §6: ConditionExpression attribute_not_exists. Si existe, devuelve lo cacheado."""
        c = _client()
        try:
            c.put_item(
                TableName=IDEMPOTENCY_TABLE,
                Item={
                    "idempotencyKey": {"S": clave},
                    "cachedResponse": {"S": json.dumps(respuesta or {})},
                },
                ConditionExpression="attribute_not_exists(idempotencyKey)",
            )
            return None  # primera vez
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                r = c.get_item(TableName=IDEMPOTENCY_TABLE, Key={"idempotencyKey": {"S": clave}})
                raw = r["Item"]["cachedResponse"]["S"]
                return json.loads(raw)
            raise

    def guardar_respuesta_idempotencia(self, clave: str, respuesta: dict) -> None:
        """Guarda la respuesta final de una operación para que un reintento con la misma clave la reciba tal cual."""
        _client().put_item(
            TableName=IDEMPOTENCY_TABLE,
            Item={"idempotencyKey": {"S": clave}, "cachedResponse": {"S": json.dumps(respuesta)}},
        )

    def guardar_saga(self, saga_id: str, datos: dict) -> None:
        _client().put_item(TableName=SAGAS_TABLE, Item={
            "sagaId": {"S": saga_id},
            "data": {"S": json.dumps(datos)},
        })

    def obtener_saga(self, saga_id: str) -> dict | None:
        r = _client().get_item(TableName=SAGAS_TABLE, Key={"sagaId": {"S": saga_id}})
        if "Item" not in r:
            return None
        return json.loads(r["Item"]["data"]["S"])
