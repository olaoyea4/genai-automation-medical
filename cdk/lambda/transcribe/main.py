import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

client = boto3.client('transcribe')

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
    
    if event.get('Outputs') is not None:  # Its an existing transcription job so just check status, update and return

        # Get the transcribe job name from the event
        transcribe_job_name = event['ExecutionInput']['transcribe_job_name']

        # Get AWS transcribe transcription job status
        response = get_transcription_job_status(transcribe_job_name)
        event['Outputs']['TranscriptionOutput']['TranscriptionJobStatus'] = response['MedicalTranscriptionJob']['TranscriptionJobStatus']
        
        return event

    else:  # Its a new transcription job 
        # Get the transcribe job name, uri, bucket, output prefix, and language from the event

        transcribe_job_name = event['transcribe_job_name']
        transcribe_job_uri = event['transcribe_job_uri']
        transcribe_job_bucket = event['transcribe_job_bucket']
        transcribe_job_output_prefix = event['transcribe_job_output_prefix']
        transcribe_job_language = event['transcribe_job_language']

        # Transcribe audio stored in S3 bucket with AWS Transcribe medical
        response = transcribe_audio_s3(transcribe_job_name, transcribe_job_uri, transcribe_job_bucket,
            transcribe_job_output_prefix, transcribe_job_language
        )
        logger.info(response)
        if type(response) == tuple:
            response = response[0]['MedicalTranscriptionJob']
        else:
            response = response['MedicalTranscriptionJob']
        
        # filter the response and return
        filtered_response = {"ExecutionInput": event, "Outputs": {}}
        transc_out = {}
        transc_out['MedicalTranscriptionJobName'] = response['MedicalTranscriptionJobName']
        transc_out['TranscriptionJobStatus'] = response['TranscriptionJobStatus']
        transc_out['LanguageCode'] = response['LanguageCode']
        transc_out['Media'] = response['Media']
        filtered_response['Outputs']['TranscriptionOutput'] = transc_out

        return filtered_response

# Function to transcribe audio stored in S3 bucket with AWS Transcribe medical
def transcribe_audio_s3(job_name, job_uri, bucket, output_prefix, language):
    if language == 'English':
        language_code = 'en-US'
    response = client.start_medical_transcription_job(
        MedicalTranscriptionJobName=job_name,
        LanguageCode=language_code,
        Media={
            'MediaFileUri': job_uri
        },
        OutputBucketName=bucket,
        OutputKey=f"{output_prefix}/medical/{job_name}.json",
        Specialty='PRIMARYCARE',
        Type='CONVERSATION'
    ),
    return response

# Function to get AWS transcribe transcription job status
def get_transcription_job_status(job_name):
    response = client.get_medical_transcription_job(MedicalTranscriptionJobName=job_name)
    return response


