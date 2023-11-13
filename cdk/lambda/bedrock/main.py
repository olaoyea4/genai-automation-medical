import boto3
import logging
import json

logger = logging.getLogger()
logger.setLevel(logging.INFO)

session = boto3.Session()
bedrock = session.client(service_name='bedrock-runtime', region_name='us-east-1')
s3 = session.client('s3')

bedrock_model_id = "anthropic.claude-v2"

def lambda_handler(event, context):

    '''
    Expected event input format
    {
        "transcribe_job_name": "transcribe_job_name",
        "transcribe_job_uri": "transcribe_job_uri",
        "transcribe_job_bucket": "transcribe_job_bucket",
        "transcribe_job_output_prefix": "transcribe_job_output_prefix",
        "transcribe_job_language": "transcribe_job_language"
    }
    '''
    logger.info(event)
    
    body = event['ExecutionInput']
    language = body['transcribe_job_language']
    bucket_name = body['transcribe_job_bucket']
    s3_file_name = body['transcribe_job_output_prefix']+'/medical/'+body['transcribe_job_name']+'.json'
    s3_file_object = s3.get_object(Bucket=bucket_name, Key=s3_file_name)
    s3_file_content = s3_file_object['Body'].read().decode('utf-8')
    json_obj = json.loads(s3_file_content)
    full_transcript = json_obj['results']['transcripts'][0]['transcript']

    command = 'Summarize this conversation in '+language+'. Highlight the key observations and acion items in as much details possible'
    prompt_text = full_transcript+'. '+command.lower()

    transcript_summarization = call_bedrock_model(prompt_text)
    result = transcript_summarization.replace("$","\$")

    event['Outputs']['BedrockOutput'] = {}
    event['Outputs']['BedrockOutput']['bedrock_model_result'] = result

    return event

def call_bedrock_model(prompt_text, max_tokens_to_sample=1024):
    body = {
        "prompt": f"\n\nHuman: {prompt_text}\n\nAssistant:",
        "max_tokens_to_sample": max_tokens_to_sample
    }
    body_string = json.dumps(body)
    body = bytes(body_string, 'utf-8')
    response = bedrock.invoke_model(
        modelId = bedrock_model_id,
        contentType = "application/json",
        accept = "application/json",
        body = body)
    response_lines = response['body'].readlines()
    json_str = response_lines[0].decode('utf-8')
    json_obj = json.loads(json_str)
    result_text = json_obj['completion']
    return result_text

