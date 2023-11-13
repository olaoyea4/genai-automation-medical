import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):

    '''
    Expected event input format
    {
        "transcribe_job_name": "transcribe_job_name",
        "transcribe_job_uri": "transcribe_job_uri",
        "transcribe_job_bucket": "transcribe_job_bucket",
        "transcribe_job_output_prefix": "transcribe_job_output_prefix",
        "transcribe_job_language": "transcribe_job_language",
        "bedrock_model_result": "xxxxxx"
    }
    '''

    logger.info(event)
    bedrock_model_result = event['Outputs']['BedrockOutput']['bedrock_model_result']
    entities = detect_entities(bedrock_model_result)

    event['Outputs']['ComprehendMedicalOutput'] = {}
    event['Outputs']['ComprehendMedicalOutput']['entities'] = entities
    
    return event

# Function to detect entities in a document with AWS Comprehend Medical
def detect_entities(document):
    comprehend = boto3.client(service_name='comprehendmedical')
    try:
        response = comprehend.detect_entities_v2(
            Text=document,
        )
        print(response)
    except Exception as e:
        raise e
    return response['Entities']