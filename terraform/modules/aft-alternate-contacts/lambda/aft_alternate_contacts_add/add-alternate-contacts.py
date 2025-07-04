'''
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
'''
import json
import logging
import os
from time import sleep
import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config

SSM_AFT_REQUEST_METADATA_PATH = "/aft/resources/ddb/aft-request-metadata-table-name"
SSM_CT_MANAGEMENT_ACCOUNT_ID_PATH = "/aft/account/ct-management/account-id"
AFT_REQUEST_METADATA_EMAIL_INDEX = "emailIndex"

boto3_config = Config(
   retries = {
      'max_attempts': 10,
      'mode': 'adaptive'
   }
)

session = boto3.Session()
logger = logging.getLogger()
if 'log_level' in os.environ:
    logger.setLevel(os.environ['log_level'])
    logger.info("Log level set to %s" % logger.getEffectiveLevel())
else:
    logger.setLevel(logging.INFO)

def lookup_aft_request_metadata(ct_parameters):
  try:
    # look up SSM for the dynamoDB metadata table
    ssm_client = session.client("ssm")
    ssm_response = ssm_client.get_parameter(
      Name=SSM_AFT_REQUEST_METADATA_PATH)
    table_name = ssm_response["Parameter"]["Value"]
    logger.info("Found metadata table : {}".format(table_name))

    # look up item in the dynamoDB table - return the account id
    ddb_client = session.resource("dynamodb")
    aft_request_metadata_table = ddb_client.Table(table_name)
    account_email = ct_parameters["AccountEmail"]
    query_response = aft_request_metadata_table.query(
      IndexName=AFT_REQUEST_METADATA_EMAIL_INDEX,
      KeyConditionExpression=Key("email").eq(account_email))
    account_id = query_response["Items"][0]["id"]
    logger.info("Account id found")

    return account_id

  except Exception as e:
    logger.exception("Error on lookup_aft_request_metadata - {}".format(e))
    raise

def update_alternate_contact(account_id, contact_payload):
  try:
    account_client = session.client("account", config=boto3_config)
    for contact_type, contact_detail in contact_payload.items():
      logger.info("Add alternate contact {}".format(contact_type))
      account_response = account_client.put_alternate_contact(
          AccountId=account_id,
          AlternateContactType=str(contact_type).upper(),
          EmailAddress=contact_detail["email-address"],
          Name=contact_detail["name"],
          PhoneNumber=contact_detail["phone-number"],
          Title=contact_detail["title"]
      )
      sleep(1)
    return True
  except Exception as e:
    logger.exception("Error on update_alternate_contact - {}".format(e))
    raise

def is_ct_management_account_id(account_id):
  try:
    # check if the account_id == CT Management account id
    ssm_client = session.client("ssm")
    ssm_response = ssm_client.get_parameter(
      Name=SSM_CT_MANAGEMENT_ACCOUNT_ID_PATH)
    ct_management_account_id = ssm_response["Parameter"]["Value"]
    if account_id == ct_management_account_id:
      logger.info("This is the CT Management Account id")
      return True
  except Exception as e:
    logger.exception("Error on is_ct_management_account_id - {}".format(e))
    raise

def lambda_handler(event, context):
  try:
      logger.info("AFT Account Alternate Contact - Handler Start")
      logger.debug(json.dumps(event))
      payload = event["payload"]
      action = event["action"]
      ct_parameters = payload["control_tower_parameters"]
      logger.debug("{} - {}".format(action, payload))

      if action == "add":
          logger.info("Look up metadata table from {}".format(SSM_AFT_REQUEST_METADATA_PATH))
          account_id = lookup_aft_request_metadata(ct_parameters)
          if is_ct_management_account_id(account_id):
            # skip if the account_id == CT Management account id
            logger.error("Unable to add alternate contact to CT Management Account, skipping")
            update_status = True
          else:
            update_status = update_alternate_contact(account_id, payload["alternate_contact"])
          return update_status
      else:
          raise Exception(
              "Incorrect Command Passed to Lambda Function. Input: {action}. Expected: 'extract' or 'add'"
          )

  except Exception as e:
      logger.exception("Error on AFT Acount Alternate contact - {}".format(e))
      raise
