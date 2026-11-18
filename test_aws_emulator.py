"""Tests that run against AWS Emulator (S3, DynamoDB, SQS).

Before running:
  Terminal 1: start the emulator (Start-AwsEmulator, or the docker run command)
  Terminal 2: set the emulator variables (Use-AwsEmulator, or the 8 $env: lines)
Then, in Terminal 2:
  python -m pytest -v test_aws_emulator.py

A safety check stops the run if you are not connected to the emulator,
so these tests never create anything in a real AWS account.
"""

import os
import uuid

import boto3
import pytest

EMULATOR_ACCOUNT = "000000000000"


def unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@pytest.fixture(scope="session", autouse=True)
def require_emulator():
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "")
    if "127.0.0.1" not in endpoint and "localhost" not in endpoint:
        pytest.exit(
            "AWS_ENDPOINT_URL is not set to the local emulator. "
            "Set the emulator variables first. Stopping so nothing runs against real AWS.",
            returncode=1,
        )
    account = boto3.client("sts").get_caller_identity()["Account"]
    if account != EMULATOR_ACCOUNT:
        pytest.exit(
            f"Connected to account {account}, not the emulator ({EMULATOR_ACCOUNT}). Stopping.",
            returncode=1,
        )


def test_s3_upload_and_download():
    s3 = boto3.client("s3")
    bucket = unique_name("test-bucket")
    s3.create_bucket(Bucket=bucket)
    try:
        s3.put_object(Bucket=bucket, Key="hello.txt", Body=b"hello from pytest")

        body = s3.get_object(Bucket=bucket, Key="hello.txt")["Body"].read()
        assert body == b"hello from pytest"

        keys = [obj["Key"] for obj in s3.list_objects_v2(Bucket=bucket).get("Contents", [])]
        assert keys == ["hello.txt"]
    finally:
        s3.delete_object(Bucket=bucket, Key="hello.txt")
        s3.delete_bucket(Bucket=bucket)


def test_dynamodb_put_and_get_item():
    ddb = boto3.client("dynamodb")
    table = unique_name("test-table")
    ddb.create_table(
        TableName=table,
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )
    try:
        ddb.get_waiter("table_exists").wait(
            TableName=table, WaiterConfig={"Delay": 1, "MaxAttempts": 20}
        )
        ddb.put_item(
            TableName=table,
            Item={"id": {"S": "item-1"}, "msg": {"S": "hello from pytest"}},
        )

        item = ddb.get_item(TableName=table, Key={"id": {"S": "item-1"}})["Item"]
        assert item["msg"]["S"] == "hello from pytest"
    finally:
        ddb.delete_table(TableName=table)


def test_sqs_send_receive_delete():
    sqs = boto3.client("sqs")
    queue_url = sqs.create_queue(QueueName=unique_name("test-queue"))["QueueUrl"]
    try:
        sqs.send_message(QueueUrl=queue_url, MessageBody="hello from pytest")

        messages = sqs.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=2
        ).get("Messages", [])
        assert len(messages) == 1
        assert messages[0]["Body"] == "hello from pytest"

        # Receive once, keep the handle, delete straight away.
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=messages[0]["ReceiptHandle"])
    finally:
        sqs.delete_queue(QueueUrl=queue_url)
