import boto3
from botocore.exceptions import ClientError
import logging
import os
import json

logger = logging.getLogger()
logger.setLevel(logging.INFO)

state_machine_arn = os.environ['STATE_MACHINE_ARN']
input = {}

def lambda_handler(event, context):
    logger.info(event)

    ''' Example event input format
    {
        "body": {
            "job_name": "testing-audio-hfduyrienb567",
            "job_uri": "s3://chartautomationcdkstack-s3bucket07682993-10nyd5de7j6xe/speech_20230717144101316.mp3",
            "output_location": "chartautomationcdkstack-s3bucket07682993-10nyd5de7j6xe",
            "output_prefix": "audio_transcripts",
            "language": "English"
        }
    }
    '''

    body = json.loads(event['body'])
    input['transcribe_job_name'] = body['job_name']
    input['transcribe_job_uri'] = body['job_uri']
    input['transcribe_job_bucket'] = body['output_location']
    input['transcribe_job_output_prefix'] = body['output_prefix']
    input['transcribe_job_language'] = body['language']

    # start a step function execution
    client = boto3.client('stepfunctions')
    try:
        response = client.start_execution(
            stateMachineArn=state_machine_arn, input=json.dumps(input))
        api_response = {
            "isBase64Encoded": False,
            "statusCode": 200,
            "body":json.dumps({"sm_execution_arn": response["executionArn"]}),
            "headers": {
                "content-type": "application/json"
            }
        }
        return api_response
    except ClientError as err:
        logger.error(
            "Couldn't start state machine %s. Here's why: %s: %s", state_machine_arn,
            err.response['Error']['Code'], err.response['Error']['Message'])
        raise
